"""Remove unused imports — drop module-level imports nothing references.

A small, surgical refactor: a top-level ``import``/``from x import ...`` whose
bound name is never used anywhere else in the module is dead weight. Apex
removes exactly those bindings and nothing else:

  - ``import os`` where ``os`` never appears       -> the line is deleted;
  - ``from x import a, b`` where only ``b`` is used -> rewritten ``from x import b``
    (surviving names keep their ORIGINAL order);
  - ``from x import a, b`` where neither is used    -> the whole statement is
    deleted (its full ``lineno..end_lineno`` span, parentheses included).

A bound name is the ``asname`` if present, else the local name:
``import a.b.c`` binds ``a``; ``import a.b as c`` binds ``c``;
``from x import y as z`` binds ``z``. A name counts as *used* if it appears as
an ``ast.Name`` load, or as the head of any attribute chain, anywhere in the
module other than the import statement itself — plus any name listed as a string
in a module-level ``__all__`` (treated as used, conservatively).

Conservative by design — any ambiguity is left alone, never guessed:
  - a package ``__init__.py`` is REFUSED outright (a top-level import there is a
    presumptive public re-export, so dropping it can shrink the package's public
    API — see :func:`_is_package_init`);
  - only TOP-LEVEL (module body) imports are considered;
  - ``from __future__ import ...`` is never touched;
  - a star import (``from x import *``) makes the whole module a no-op — names
    could be bound through it, so removing anything is too risky;
  - imports inside ``try``/``except`` or any non-module-body scope are ignored;
  - a statement with a trailing ``# noqa`` on its line is left as written;
  - the rewritten module must re-parse, or the whole plan blocks.

Edits are line-span replacements applied bottom-up so earlier line numbers stay
valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)

__all__ = ["plan_remove_unused_imports", "strip_unused_imports"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its imports are often deliberate
    boilerplate). A local copy — importing this from health_score created a
    health_score <-> dedup import cycle, and the grade now reads dedup."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _is_package_init(path: str) -> bool:
    """Is ``path`` a package ``__init__.py``? A top-level import there is
    presumptively a public RE-EXPORT (the standard package-init convention:
    ``from .submod import Foo`` surfaces ``Foo`` as the package's public name),
    so it reads as "imported, never used locally" yet IS the public API. Pruning
    it would silently drop the package's exports — a buyer-facing pilot caught
    exactly this on an ``__init__.py`` whose re-exports carried NO module-level
    ``__all__`` (so the ``__all__`` keep-set could not protect them) while the
    suite stayed green (it imported the submodules directly). Refusing every
    ``__init__.py`` (matching ruff's lenient ``__init__.py`` default and this
    module's soundness-over-recall posture) trades a rare unused-import false
    negative there for never dropping a real re-export."""
    return Path(path.replace("\\", "/")).name == "__init__.py"


def _bound_name(alias: ast.alias) -> str:
    """The local name an import alias binds: the asname if present, else the
    head of the (possibly dotted) imported name (``import a.b.c`` binds ``a``)."""
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0]


def _attr_head(node: ast.Attribute) -> ast.AST:
    """The root of an attribute chain (``a.b.c`` -> the ``a`` node)."""
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur


def _used_names(tree: ast.Module, import_nodes: set[int]) -> set[str]:
    """Every name referenced in ``tree`` outside the import statements: any
    ``ast.Name`` load id and the head id of any attribute chain. Nodes belonging
    to a top-level import (identified by ``id()``) are skipped so a binding does
    not count as its own use."""
    skip: set[int] = set()
    for node in tree.body:
        if id(node) in import_nodes:
            for sub in ast.walk(node):
                skip.add(id(sub))

    used: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            head = _attr_head(node)
            if isinstance(head, ast.Name):
                used.add(head.id)
    return used


def _all_names(tree: ast.Module) -> set[str]:
    """String entries of a module-level ``__all__`` list/tuple — treated as
    used so an export is never pruned."""
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = node.targets
        if not (len(targets) == 1 and isinstance(targets[0], ast.Name)
                and targets[0].id == "__all__"):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple)):
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
    return names


def _has_star_import(tree: ast.Module) -> bool:
    """Does any statement (anywhere) do ``from x import *``? If so the whole
    module is a no-op — names could be bound through the star."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.ImportFrom)) and (any(alias.name == "*" for alias in node.names)):
            return True
    return False


def _has_noqa(lines: list[str], lineno: int, end_lineno: int) -> bool:
    """Does any source line of the statement carry a ``# noqa`` comment?"""
    for i in range(lineno - 1, end_lineno):
        if "# noqa" in lines[i]:
            return True
    return False


class _Rewrite:
    """One located edit: replace lines [lo, hi] (1-based, inclusive) with
    ``text`` (which may be None to delete the span entirely)."""

    __slots__ = ("lo", "hi", "text")

    def __init__(self, lo: int, hi: int, text: str | None) -> None:
        self.lo = lo
        self.hi = hi
        self.text = text


def _is_prunable_import(node: ast.AST) -> bool:
    """A module-body import we may consider for pruning: a plain ``import`` or a
    ``from x import ...`` that is neither ``from __future__`` nor a star import
    (those are always left alone)."""
    if isinstance(node, ast.ImportFrom):
        return node.module != "__future__" and not any(
            alias.name == "*" for alias in node.names)
    return isinstance(node, ast.Import)


def _survivors(node: ast.Import | ast.ImportFrom, used: set[str],
               keep: set[str]) -> list[ast.alias]:
    """The aliases on ``node`` whose bound name is used or kept (original order
    preserved)."""
    return [
        alias for alias in node.names
        if _bound_name(alias) in used or _bound_name(alias) in keep
    ]


def _alias_text(alias: ast.alias) -> str:
    """Render one alias as it appears in an import list (``a`` or ``a as b``)."""
    if alias.asname is None:
        return alias.name
    return f"{alias.name} as {alias.asname}"


def _rewrite_text(node: ast.Import | ast.ImportFrom,
                  survivors: list[ast.alias], newline: str) -> str:
    """The replacement import statement keeping only ``survivors``."""
    indent = " " * node.col_offset
    parts = ", ".join(_alias_text(alias) for alias in survivors)
    if isinstance(node, ast.Import):
        return f"{indent}import {parts}{newline}"
    prefix = "." * node.level + (node.module or "")
    return f"{indent}from {prefix} import {parts}{newline}"


def _rewrite_for(node: ast.Import | ast.ImportFrom, lines: list[str],
                 used: set[str], keep: set[str]) -> _Rewrite | None:
    """The single edit pruning unused names from ``node``, or ``None`` when the
    statement is skipped (noqa-marked or nothing unused)."""
    if _has_noqa(lines, node.lineno, node.end_lineno):
        return None
    survivors = _survivors(node, used, keep)
    if len(survivors) == len(node.names):
        return None  # nothing unused on this statement
    if not survivors:
        return _Rewrite(node.lineno, node.end_lineno, None)
    newline = "\n" if lines[node.end_lineno - 1].endswith("\n") else ""
    return _Rewrite(node.lineno, node.end_lineno,
                    _rewrite_text(node, survivors, newline))


def _collect_rewrites(tree: ast.Module, lines: list[str], used: set[str],
                      keep: set[str]) -> list[_Rewrite]:
    """Every unused-import removal in the module body. ``keep`` holds names that
    must never be pruned (``__all__`` exports)."""
    rewrites: list[_Rewrite] = []
    for node in tree.body:
        if not _is_prunable_import(node):
            continue
        rewrite = _rewrite_for(node, lines, used, keep)
        if rewrite is not None:
            rewrites.append(rewrite)
    return rewrites


def _apply(lines: list[str], rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up so earlier line numbers stay valid. A ``None``
    text deletes the span; otherwise it replaces it with a single line."""
    out = list(lines)
    for rw in sorted(rewrites, key=lambda r: r.lo, reverse=True):
        if rw.text is None:
            out[rw.lo - 1:rw.hi] = []
        else:
            out[rw.lo - 1:rw.hi] = [rw.text]
    return "".join(out)


def _compute_import_rewrites(tree: ast.Module, source: str) -> tuple[list[str], list]:
    """The shared core: locate every unused-import rewrite for an already-parsed
    module. Returns ``(lines, rewrites)`` — the ``keepends`` source lines and the
    line-span rewrites — so both the path-free :func:`strip_unused_imports` and the
    plan-building :func:`plan_remove_unused_imports` apply one detector."""
    import_nodes = {
        id(node) for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    used = _used_names(tree, import_nodes)
    keep = _all_names(tree)

    lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, lines, used, keep)
    return lines, rewrites


def strip_unused_imports(source: str) -> str | None:
    """Return ``source`` with its unused TOP-LEVEL imports removed, or ``None``
    when there is nothing safe to remove.

    This is the path-free core that :func:`plan_remove_unused_imports` (and other
    transforms, e.g. dedup-extract gate-cleaning its own output) reuse: it applies
    the exact same conservative detector — ``from __future__`` and star-import
    modules are never touched, ``# noqa`` lines and non-module-body imports are
    left alone, and ``__all__`` exports are kept. ``None`` means "leave as-is":
    the source doesn't parse, a star import makes the module a no-op, nothing was
    unused, or the cleaned source would not re-parse.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    if _has_star_import(tree):
        return None  # too risky — names could be bound via the star (no-op)

    lines, rewrites = _compute_import_rewrites(tree, source)
    if not rewrites:
        return None  # nothing unused

    new_source = _apply(lines, rewrites)
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError):
        return None  # never emit broken source
    if new_source == source:
        return None
    return new_source


def plan_remove_unused_imports(project_root: str | Path,
                               module_rel: str) -> RenamePlan:
    """Build the single-module unused-import removal plan, or its blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    Top-level imports whose bound name is referenced nowhere else in the module
    are dropped; an empty plan means nothing was unused (a no-op, not a
    failure)."""
    plan = RenamePlan(old=module_rel, new="remove-unused-imports")
    if _is_package_init(module_rel):
        return plan  # public re-export surface — never prune a package __init__.py
    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    if _has_star_import(tree):
        return plan  # too risky — names could be bound via the star (no-op)

    lines, rewrites = _compute_import_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(lines, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="removal")
