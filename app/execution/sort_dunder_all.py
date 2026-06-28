"""Sort + de-duplicate an existing module-level ``__all__`` of string literals.

The ORDER of ``__all__`` never affects ``from m import *`` (it determines only
WHICH names are exported, not in what order they bind), so sorting an ``__all__``
list/tuple of string literals into canonical (lexicographic) order — and dropping an
accidental duplicate — is behaviour-IDENTICAL: nothing observable changes. It is the
public-surface analogue of ``sort-imports``: a readability tidy a careful author
keeps by hand. Where a linter only FLAGS an unsorted ``__all__``,
:func:`sort_module_all` rewrites it, deterministically and for free.

DISTINCT from wire-module-exports (which CREATES an ``__all__`` on a module that has
NONE): this one SORTS an ``__all__`` that ALREADY exists. The two are mutually
exclusive on any given module by construction — a module has either zero ``__all__``
(only wire-module-exports may act) or one (only sort-dunder-all may act) — so they
never edit the same module, and because wire-module-exports emits an already-sorted
``__all__``, sort-dunder-all is a byte-identical no-op on a freshly-wired one (they
compose to a stable fixpoint).

REFUSES (returns ``None``, an honest no-op) unless ``__all__`` is a PLAIN literal
``list``/``tuple`` of string-literal elements. A computed ``__all__`` (a name, a
``BinOp`` ``_BASE + [...]``, a ``list(...)`` / ``sorted(...)`` call, a
comprehension), an ``__all__ += [...]`` (``AugAssign``), an
``__all__.append(...)`` / ``.extend(...)`` / ``.insert(...)`` call, a conditional
re-binding, a second ``__all__`` store, a non-string element, more than one
``__all__``, an already-canonical list, or unparseable source → REFUSE. Sorting only
the literal fragment of a dynamically-assembled ``__all__`` could change the
exported set the dynamic part depends on, so the whole module is refused when any
mutation of ``__all__`` exists anywhere (over-approximate toward refusal).

Deterministic (``sorted(set(...))`` is total and locale-independent over ``str``;
pure AST walk + line splice, no clock/random), stdlib-only, zero-token, idempotent
(an already-canonical ``__all__`` is a byte-identical no-op). Reuses
:func:`app.execution.dataclass_rewrite.rejoin_guarded` for the "splice, preserve
newline, re-``ast.parse`` guard" epilogue.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import rejoin_guarded

__all__ = [
    "sort_module_all",
    "all_is_sortable",
]


def _is_all_name(node: ast.expr) -> bool:
    """True when ``node`` is the bare name ``__all__``."""
    return isinstance(node, ast.Name) and node.id == "__all__"


def _all_assign_value(stmt: ast.stmt) -> ast.expr | None:
    """The value node a top-level ``__all__`` assignment binds, or ``None`` when
    ``stmt`` is not an ``__all__`` assignment.

    Matches an ``ast.Assign`` with a SINGLE bare-``Name`` ``__all__`` target, or an
    ``ast.AnnAssign`` with a bare-``Name`` ``__all__`` target AND a value (``__all__:
    list[str] = [...]``). Mirrors the detection shape of
    ``module_exports.has_module_all``."""
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) == 1 and _is_all_name(stmt.targets[0]):
            return stmt.value
        return None
    if isinstance(stmt, ast.AnnAssign) and stmt.value is not None and _is_all_name(
            stmt.target):
        return stmt.value
    return None


def _find_all_assignments(tree: ast.Module) -> list[ast.stmt]:
    """Every top-level ``__all__`` assignment statement (``Assign`` / ``AnnAssign``),
    in source order. More than one means an ambiguous / dynamically-assembled
    ``__all__`` the caller refuses."""
    return [stmt for stmt in tree.body if _all_assign_value(stmt) is not None]


def _string_elements(value: ast.expr) -> list[str] | None:
    """The element strings of ``value`` when it is a PLAIN ``List`` / ``Tuple``
    literal whose elements are ALL string ``ast.Constant``s, in source order; else
    ``None`` (a computed value, or any non-string / starred / nested element)."""
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    names: list[str] = []
    for el in value.elts:
        if not (isinstance(el, ast.Constant) and isinstance(el.value, str)):
            return None
        names.append(el.value)
    return names


def _has_all_augassign(tree: ast.Module) -> bool:
    """True when an ``__all__ += ...`` (``ast.AugAssign`` targeting ``__all__``)
    appears ANYWHERE in ``tree`` (including under an ``if TYPE_CHECKING:`` guard)."""
    return any(isinstance(node, ast.AugAssign) and _is_all_name(node.target)
               for node in ast.walk(tree))


def _stores_all(node: ast.AST) -> bool:
    """True when ``node`` is a ``__all__`` ``Store`` target anywhere in the tree —
    a bare ``Name('__all__')`` in ``Store`` context (a plain or augmented assign, a
    ``for``/``with`` target). Used to count distinct binding sites."""
    return (isinstance(node, ast.Name) and node.id == "__all__"
            and isinstance(node.ctx, ast.Store))


def _all_store_count(tree: ast.Module) -> int:
    """How many times ``__all__`` is STORED anywhere in ``tree`` — a second store
    (a conditional re-binding, a re-assignment) means the surface is assembled
    dynamically and the caller refuses."""
    return sum(1 for node in ast.walk(tree) if _stores_all(node))


def _is_all_mutation_call(node: ast.AST) -> bool:
    """True when ``node`` is an ``__all__.append(...)`` / ``.extend(...)`` /
    ``.insert(...)`` call — a dynamic in-place mutation of the export list."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and _is_all_name(node.func.value)
            and node.func.attr in ("append", "extend", "insert"))


def _has_all_mutation_call(tree: ast.Module) -> bool:
    """True when an ``__all__.append/.extend/.insert(...)`` call appears anywhere."""
    return any(_is_all_mutation_call(node) for node in ast.walk(tree))


def _all_is_dynamically_assembled(tree: ast.Module) -> bool:
    """True when ``__all__`` is mutated/re-bound anywhere — an ``__all__ += ...``,
    more than one ``Store`` of ``__all__``, or an ``.append/.extend/.insert`` call.
    Such a module is refused: sorting the literal fragment could change the exported
    set the dynamic part depends on (over-approximate toward refusal)."""
    return (_has_all_augassign(tree) or _all_store_count(tree) > 1
            or _has_all_mutation_call(tree))


def _container_brackets(value: ast.expr) -> tuple[str, str]:
    """The opening/closing brackets for ``value``'s container kind: ``("[", "]")``
    for a list, ``("(", ")")`` for a tuple."""
    return ("(", ")") if isinstance(value, ast.Tuple) else ("[", "]")


def _render_all_block(indent: str, value: ast.expr, names: list[str]) -> list[str]:
    """The source lines of a canonical ``__all__`` declaration for ``names``,
    preserving ``value``'s container kind (list vs tuple) and the header ``indent``
    — one quoted name per line with a trailing comma (the shape wire-module-exports
    emits). A single-element tuple's trailing comma makes it a valid ``("a",)``."""
    open_b, close_b = _container_brackets(value)
    block = [f"{indent}__all__ = {open_b}"]
    block.extend(f'{indent}    "{name}",' for name in names)
    block.append(f"{indent}{close_b}")
    return block


def resplice_all_names(source: str, stmt: ast.stmt, new_names: list[str]) -> str | None:
    """Re-render the ``__all__`` statement ``stmt`` in ``source`` with element list
    ``new_names``, preserving its container kind and header indentation — the shared
    "splice the new ``__all__`` block back in, guard the result" tail of BOTH
    public-surface ``__all__`` rewriters (``sort_module_all`` reorders, the
    dedup-dunder-all transform de-dupes; they differ ONLY in how ``new_names`` is
    derived). Splices the statement's whole line span and runs the standard
    :func:`~app.execution.dataclass_rewrite.rejoin_guarded` epilogue (preserve the
    trailing newline; ``None`` on a no-op or non-re-parsing result). One source of
    truth, so neither caller re-copies the index arithmetic."""
    value = _all_assign_value(stmt)
    lines = source.splitlines()
    start = stmt.lineno - 1
    end = getattr(stmt, "end_lineno", stmt.lineno)
    header = lines[start]
    indent = header[: len(header) - len(header.lstrip())]
    out_lines = list(lines)
    out_lines[start:end] = _render_all_block(indent, value, new_names)  # type: ignore[arg-type]
    return rejoin_guarded(source, out_lines)


def _sortable_all(source: str) -> tuple[ast.Module, ast.stmt, list[str]] | None:
    """The ``(tree, stmt, current_names)`` of a module with exactly ONE plain
    string-literal ``__all__`` that is NOT dynamically assembled, or ``None``.

    The shared gate of both public functions: parse (``None`` on failure), find the
    single top-level ``__all__`` (``None`` for zero or more than one), require its
    value be a plain literal of string literals (``None`` otherwise), and reject any
    dynamic mutation of ``__all__`` anywhere (``None``). Does NOT decide whether a
    change is needed — the caller compares against the canonical order."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    assignments = _find_all_assignments(tree)
    if len(assignments) != 1:
        return None  # zero (nothing to sort) or many (ambiguous) — refuse
    stmt = assignments[0]
    names = _string_elements(_all_assign_value(stmt))  # type: ignore[arg-type]
    if names is None:
        return None  # computed __all__ or a non-string element — refuse
    if _all_is_dynamically_assembled(tree):
        return None  # __all__ += / .append / second store — refuse
    return tree, stmt, names


def all_is_sortable(source: str) -> bool:
    """True iff ``source`` has a single plain string-literal ``__all__`` that is NOT
    already canonical (i.e. ``sorted(set(...))`` differs from the current order, so
    there is a real change to make). ``False`` on any refusal or an already-canonical
    list. Pure (no clock/random)."""
    gated = _sortable_all(source)
    if gated is None:
        return False
    _tree, _stmt, names = gated
    return sorted(set(names)) != names


def sort_module_all(source: str) -> str | None:
    """Sort + de-duplicate the module-level ``__all__`` in ``source``, or ``None``
    when nothing changes.

    Runs the shared gate (single plain string-literal ``__all__``, no dynamic
    mutation), computes ``canonical = sorted(set(current))``, and — when it differs
    from the current order — re-renders the whole ``__all__`` statement's line span
    (preserving the container kind and the header indentation) and returns the
    re-``ast.parse``d result. An already-canonical list, a computed/dynamic
    ``__all__``, a non-string element, or unparseable source yields ``None``.
    Deterministic and idempotent."""
    gated = _sortable_all(source)
    if gated is None:
        return None
    _tree, stmt, current = gated
    canonical = sorted(set(current))
    if canonical == current:
        return None  # already sorted AND de-duplicated — byte-identical no-op
    return resplice_all_names(source, stmt, canonical)
