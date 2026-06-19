"""Constructive seeding signal: where a project is HALF-BUILT.

Apex is a project-DEVELOPMENT assistant, so the most on-brand signal is not a
smell to scrub but a contract you STARTED and did not finish — "you began a
protocol, now complete it". This module names those gaps; it never writes them.

The bar is deliberately high: a false positive here erodes Apex's whole value
proposition, so this scan flags ONLY the Python contract gaps that are
unambiguous from a single file's AST, and stays silent on everything fuzzy:

  - ``__eq__`` defined but NO ``__hash__`` — the canonical contract gap. A class
    that overrides equality without ``__hash__`` becomes UNHASHABLE in Python 3
    (instances can't be set members or dict keys). Flagged ONLY when the class is
    a clean ``object`` subclass we can reason about statically: empty/``object``
    bases, NOT a ``@dataclass``/``@attr.s`` (those auto-generate ``__hash__``),
    NOT a body that sets ``__hash__ = None`` (deliberately unhashable), and NOT a
    body that already defines ``__hash__``.
  - ``__enter__`` without ``__exit__`` (and the reverse) — a half-built context
    manager protocol.
  - ``__aenter__`` without ``__aexit__`` (and the reverse) — the async pair.

Anything where a one-sided definition is legitimately common (e.g. ``to_dict``
without ``from_dict``) is intentionally NOT flagged.

Deterministic (results sorted by ``(module, line, class)``; no time/random),
stdlib-only, pure AST. Walks source files through the canonical
:mod:`app.engine.skip_dirs` exclusion and skips test/example/fixture files, so an
all-clean repo yields ``[]`` and downstream seeding stays byte-identical.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["incomplete_protocols", "render_completeness_markdown"]

# The unambiguous "method A implies method B" pairs. Each entry names the
# protocol, the method that MUST be present given its partner, and the partner
# whose presence triggers the requirement. Direction matters for the context
# managers (either half implies the other), so both directions are listed.
_PAIR_PROTOCOLS: tuple[tuple[str, str, str], ...] = (
    # protocol label, the method that must exist, the method that demands it
    ("context-manager", "__exit__", "__enter__"),
    ("context-manager", "__enter__", "__exit__"),
    ("async-context-manager", "__aexit__", "__aenter__"),
    ("async-context-manager", "__aenter__", "__aexit__"),
)

# Decorators that auto-synthesise ``__hash__`` (or otherwise make the eq/hash
# contract the framework's job, not the author's) — so an ``__eq__`` under them
# is NOT a gap. Matched on the trailing attribute name only (``dataclass``,
# ``dataclasses.dataclass``, ``attr.s``, ``attrs.define`` all reduce to a known
# leaf) so the guard holds regardless of import style.
_AUTO_HASH_DECORATORS = frozenset({
    "dataclass", "s", "attrs", "define", "frozen", "mutable", "attributes",
})


def _decorator_leaf(node: ast.expr) -> str:
    """The bare decorator name, ignoring call-args and the module prefix.

    ``@dataclass`` -> ``dataclass``; ``@dataclasses.dataclass`` -> ``dataclass``;
    ``@attr.s(slots=True)`` -> ``s``; ``@attrs.define`` -> ``define``.
    """
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _has_auto_hash_decorator(cls: ast.ClassDef) -> bool:
    return any(_decorator_leaf(d) in _AUTO_HASH_DECORATORS
               for d in cls.decorator_list)


def _is_plain_object_class(cls: ast.ClassDef) -> bool:
    """True only for a class with empty bases or exactly ``object``.

    A non-``object`` base may supply ``__hash__``/``__eq__`` we can't see
    statically, so a subclass is never flagged for the eq/hash gap (it might
    legitimately inherit a hash). Keyword bases (``metaclass=...``) also make the
    class non-trivial, so they disqualify it.
    """
    if cls.keywords:
        return False
    if not cls.bases:
        return True
    return all(isinstance(b, ast.Name) and b.id == "object" for b in cls.bases)


def _direct_method_names(cls: ast.ClassDef) -> set[str]:
    """Names of methods defined DIRECTLY in this class body (sync or async)."""
    return {
        stmt.name
        for stmt in cls.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _assigns_hash_none(cls: ast.ClassDef) -> bool:
    """True if the body assigns ``__hash__`` — e.g. ``__hash__ = None`` (the
    deliberately-unhashable idiom). Any direct assignment to the name means the
    author handled hashing explicitly, so the class is not a gap."""
    for stmt in cls.body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        else:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name) and tgt.id == "__hash__":
                return True
    return False


def _class_gap(cls: ast.ClassDef) -> tuple[str, str, str] | None:
    """The (protocol, have, missing) gap for one class, or None when complete.

    Eq/hash takes precedence (the canonical contract); then the context-manager
    pairs in declaration order. At most one gap per class so a single class never
    floods the signal.
    """
    methods = _direct_method_names(cls)

    # Eq/hash: the canonical, highest-value gap.
    if (
        "__eq__" in methods
        and "__hash__" not in methods
        and _is_plain_object_class(cls)
        and not _has_auto_hash_decorator(cls)
        and not _assigns_hash_none(cls)
    ):
        return ("equality/hash", "__eq__", "__hash__")

    # Context-manager pairs (sync then async), either half implying the other.
    for protocol, must_have, trigger in _PAIR_PROTOCOLS:
        if trigger in methods and must_have not in methods:
            return (protocol, trigger, must_have)

    return None


def _iter_classdefs(tree: ast.AST):
    """Yield EVERY ClassDef in the module — top-level and nested."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield node


def _is_excluded(rel: str) -> bool:
    """Skip test/example/fixture files — their half-built classes are noise."""
    p = rel.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in f"/{p}"
        or "/test/" in f"/{p}"
        or "/examples/" in f"/{p}"
        or "/example/" in f"/{p}"
        or "/fixtures/" in f"/{p}"
        or p.startswith(("tests/", "test/", "examples/", "example/", "fixtures/"))
    )


def incomplete_protocols(root: str) -> list[dict]:
    """Half-implemented Python contract pairs across the project's source.

    Walks every ``.py`` file under ``root`` (through the canonical skip-dir
    exclusion), parses each, and emits one entry per class with an unambiguous
    protocol gap. Conservative by construction — see the module docstring for the
    exact pairs flagged and every false-positive guard.

    Each entry: ``{"module", "class", "line", "protocol", "have", "missing"}``.
    Sorted by ``(module, line, class)`` for deterministic, reproducible output;
    an all-clean repo yields ``[]``.
    """
    root_path = Path(root)
    out: list[dict] = []
    for path in iter_source_files(root_path, "*.py"):
        rel = str(path.relative_to(root_path))
        if _is_excluded(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        rel_norm = rel.replace("\\", "/")
        for cls in _iter_classdefs(tree):
            gap = _class_gap(cls)
            if gap is None:
                continue
            protocol, have, missing = gap
            out.append({
                "module": rel_norm,
                "class": cls.name,
                "line": cls.lineno,
                "protocol": protocol,
                "have": have,
                "missing": missing,
            })
    out.sort(key=lambda e: (e["module"], e["line"], e["class"]))
    return out


def render_completeness_markdown(items: list[dict]) -> str:
    """A short clause naming the half-built protocols to finish.

    Empty string when there are none, so callers can append it unconditionally
    and an all-clean repo's output stays byte-identical.
    """
    if not items:
        return ""
    parts = [
        f"`{it['class']}` ({it['module']}:{it['line']}) — defines "
        f"{it['have']} but no {it['missing']}"
        for it in items
    ]
    return "Incomplete protocols (finish what you started): " + "; ".join(parts) + "."
