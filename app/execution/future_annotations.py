"""Insert ``from __future__ import annotations`` into a module that USES type
annotations but does not yet defer their evaluation.

The honest gap this closes: a student or team writes modern, fully-typed code —
``def f(x: int) -> Foo:``, ``count: int = 0``, ``items: list[Bar]`` — but forgets
the one line that makes those annotations *lazy*: ``from __future__ import
annotations`` (PEP 563). Without it every annotation is EVALUATED at definition
time, so a forward reference, a not-yet-imported name, or an expensive subscript
costs real import-time work (and can ``NameError`` outright). With it, every
annotation becomes a string that is only resolved on demand. ``add_future_annotations``
LANDS exactly that one-line, behaviour-preserving modernization — deterministically,
for free, no LLM.

The rewrite is minimal and idempotent:

  - a module with NO ``from __future__`` import gets a fresh
    ``from __future__ import annotations`` inserted after its docstring (before the
    first real statement, the canonical spot a ``__future__`` import must occupy);
  - a module that ALREADY imports something from ``__future__`` (e.g. ``from
    __future__ import division``) has that existing import WIDENED in place to add
    ``annotations`` (names kept sorted), never a second ``__future__`` line.

It REFUSES (returns ``None`` — an honest no-op, lands nothing) when the module:

  - uses NO annotations at all (nothing to defer — adding the import would be noise);
  - already imports ``annotations`` from ``__future__`` (idempotent — a second run
    is a byte-identical no-op);
  - does not parse (never rewrite broken source).

The single runtime risk — code that EAGERLY resolves its own annotations at import
time via ``typing.get_type_hints()`` (which, with lazy annotations, evaluates the
now-stringized annotation in a context where a forward-only name may be undefined)
— is caught by the objective layer's full-suite gate + byte-for-byte rollback, the
same engine every objective uses. The result is re-``ast.parse``d before it is
returned, so a malformed rewrite is dropped rather than landed.

Deterministic (pure AST walk + line splice, no clock/random), stdlib-only,
zero-token. Reuses the shared helpers from :mod:`app.execution.dataclass_rewrite`:
``_import_insertion_index`` (which itself calls ``_skip_docstring``) so a
``__future__`` line lands in exactly the canonical spot — a fresh-insert is
placement-identical to the dataclass import insert — and ``rejoin_guarded`` for the
common "splice, preserve the trailing newline, re-``ast.parse`` guard" epilogue.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded

__all__ = [
    "add_future_annotations",
    "module_uses_annotations",
    "has_future_annotations",
]

_FUTURE_PREFIX = "from __future__ import "


def _arg_has_annotation(args: ast.arguments) -> bool:
    """True when ANY parameter of a function signature carries an annotation —
    regular, positional-only, keyword-only, ``*args`` or ``**kwargs``."""
    every = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    if args.vararg is not None:
        every.append(args.vararg)
    if args.kwarg is not None:
        every.append(args.kwarg)
    return any(a.annotation is not None for a in every)


def _node_uses_annotation(node: ast.AST) -> bool:
    """True when a single AST node IS a type-annotation use: a function with a
    return type or any annotated parameter, or a variable annotation
    (``x: T`` / ``x: T = v``)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.returns is not None or _arg_has_annotation(node.args)
    return isinstance(node, ast.AnnAssign)


def module_uses_annotations(source: str) -> bool:
    """True when ``source`` uses at least one type annotation anywhere — a return
    type, an annotated parameter, or an ``AnnAssign``. ``False`` on a syntax
    error (nothing to defer in source we cannot parse)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    return any(_node_uses_annotation(n) for n in ast.walk(tree))


def _future_import_index(lines: list[str]) -> int | None:
    """Index of the FIRST top-level ``from __future__ import ...`` line, or
    ``None`` when the module imports nothing from ``__future__``."""
    for i, line in enumerate(lines):
        if line.strip().startswith(_FUTURE_PREFIX):
            return i
    return None


def _imported_future_names(line: str) -> set[str]:
    """The feature names a ``from __future__ import a, b`` line imports."""
    return {
        name.strip()
        for name in line.split("import", 1)[1].split(",")
        if name.strip()
    }


def has_future_annotations(source: str) -> bool:
    """True when ``source`` already imports ``annotations`` from ``__future__``."""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(_FUTURE_PREFIX) and "annotations" in _imported_future_names(stripped):
            return True
    return False


def _widen_future_import(lines: list[str], idx: int) -> list[str]:
    """Add ``annotations`` to the existing ``from __future__ import ...`` at
    ``idx`` (names kept sorted), preserving the line's leading indentation."""
    line = lines[idx]
    indent = line[: len(line) - len(line.lstrip())]
    names = _imported_future_names(line) | {"annotations"}
    new_lines = list(lines)
    new_lines[idx] = f"{indent}{_FUTURE_PREFIX}" + ", ".join(sorted(names))
    return new_lines


def _insert_future_import(lines: list[str]) -> list[str]:
    """Insert a fresh ``from __future__ import annotations`` at the canonical
    spot — after a module docstring, before the first real statement — keeping a
    blank line before the code that follows."""
    insert_at = _import_insertion_index(lines)
    block = [f"{_FUTURE_PREFIX}annotations"]
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def add_future_annotations(source: str) -> str | None:
    """Add ``from __future__ import annotations`` to ``source``, or ``None`` when
    nothing changes.

    Inserts a fresh import (no ``__future__`` line present) or widens an existing
    ``from __future__ import ...`` to include ``annotations``. Returns ``None`` —
    an honest no-op — when the module uses no annotations, already imports
    ``annotations``, or does not parse. Deterministic and idempotent; the result
    is re-``ast.parse``d before return so a malformed rewrite is dropped rather
    than landed."""
    try:
        ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None  # never rewrite broken source
    if has_future_annotations(source):
        return None  # already deferred — idempotent no-op
    if not module_uses_annotations(source):
        return None  # nothing to defer — adding the import would be pure noise

    lines = source.splitlines()
    future_idx = _future_import_index(lines)
    if future_idx is not None:
        out_lines = _widen_future_import(lines, future_idx)
    else:
        out_lines = _insert_future_import(lines)
    return rejoin_guarded(source, out_lines)
