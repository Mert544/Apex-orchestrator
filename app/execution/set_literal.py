"""Set-literal — rewrite ``set([...])`` / ``set((...))`` into a set literal ``{...}``.

A small, surgical modernization: a ``set`` call whose sole argument is a
non-empty list or tuple LITERAL is exactly a set display::

    set([1, 2, 3])    -> {1, 2, 3}
    set((1, 2))       -> {1, 2}
    set([a[0], b])    -> {a[0], b}

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.Call`` whose func is a BARE ``ast.Name`` ``set`` (an
    attribute like ``builtins.set`` is left alone);
  - it has EXACTLY ONE positional argument, no keyword args and no star-args;
  - that argument is a NON-EMPTY ``ast.List`` or ``ast.Tuple`` literal whose
    elements include no ``ast.Starred`` (so ``set([*a])`` is never touched);
  - the whole Call lives on a SINGLE line so the column-span splice is
    trivially correct — multi-line calls are skipped.

Deliberately untouched: ``set()`` (the empty call — ``{}`` is a *dict*, not a
set), ``set(x)`` / ``set(gen for ...)`` (the argument is a name, call, or
comprehension, not a literal), and ``frozenset(...)`` (a different builtin).

Elements keep their ORIGINAL source text (via ``ast.get_source_segment``), in
order and without de-duplication — ``set([1, 1])`` becomes ``{1, 1}``, which is
the same set. If any element's source segment can't be recovered, that
occurrence is skipped.

Edits are column-span replacements of the whole Call located by the AST (no
unparse round-trip), so comments and formatting elsewhere survive untouched.
Rewrites are applied bottom-up and right-to-left within a line so earlier column
offsets stay valid when several occurrences share a line. The rewritten module
must re-parse or the whole plan blocks. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import apply_column_rewrites, is_fixture_path
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_set_literal"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _set_call_arg(node: ast.AST) -> ast.List | ast.Tuple | None:
    """If ``node`` is a bare ``set(<list/tuple literal>)`` call eligible for
    rewriting, return its single list/tuple argument, else None.

    Eligible means: func is a bare ``Name`` ``set``; exactly one positional arg;
    no keywords and no star-args; the arg is a NON-EMPTY ``List``/``Tuple``
    literal with no starred element."""
    if not isinstance(node, ast.Call):
        return None
    if not (isinstance(node.func, ast.Name) and node.func.id == "set"):
        return None
    if len(node.args) != 1 or node.keywords:
        return None
    arg = node.args[0]
    if not isinstance(arg, (ast.List, ast.Tuple)):
        return None
    if not arg.elts:  # empty literal — set([]) / set(()) collapses to set(), skip
        return None
    if any(isinstance(elt, ast.Starred) for elt in arg.elts):
        return None
    return arg


def _try_call(node: ast.Call, source: str) -> _Rewrite | None:
    """If ``node`` is a rewritable ``set([...])`` call on a single line, return
    its set-literal rewrite, else None."""
    arg = _set_call_arg(node)
    if arg is None:
        return None
    if node.lineno != node.end_lineno:  # multi-line call — skip to stay safe
        return None

    elements: list[str] = []
    for elt in arg.elts:
        seg = ast.get_source_segment(source, elt)
        if seg is None:  # can't recover an element's text — skip this occurrence
            return None
        elements.append(seg)

    replacement = "{" + ", ".join(elements) + "}"
    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    replacement)


def _contains(outer: _Rewrite, inner: _Rewrite) -> bool:
    """True if ``inner``'s span lies strictly within ``outer``'s span on the
    same line — i.e. a nested ``set([...])`` inside another ``set([...])``."""
    return (
        outer.lineno == inner.lineno
        and outer.col <= inner.col
        and inner.end_col <= outer.end_col
        and (outer.col, outer.end_col) != (inner.col, inner.end_col)
    )


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every rewritable ``set([...])`` / ``set((...))`` call in ``tree``.

    A rewrite REPLACES the whole call's column span, and an element keeps its
    ORIGINAL source text — so when a ``set([...])`` is nested inside another, the
    outer replacement already carries the inner call verbatim (still a valid,
    equivalent expression). Applying the inner rewrite as well would splice two
    overlapping spans and corrupt the line, so any rewrite contained in another
    is dropped: the outer one wins, the inner text rides along unchanged."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            rw = _try_call(node, source)
            if rw is not None:
                rewrites.append(rw)
    return [
        rw for rw in rewrites
        if not any(_contains(other, rw) for other in rewrites if other is not rw)
    ]


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_set_literal(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module set-literal plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every
    ``set([...])`` / ``set((...))`` call over a non-empty list/tuple literal into
    a set display ``{...}``. An empty plan (no new_contents, no blockers) means
    nothing matched — a no-op, not a failure."""
    plan = RenamePlan(old=module_rel, new="set-literal")
    if _is_fixture_path(module_rel):
        return plan

    root = Path(project_root)
    path = root / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {module_rel}")
        return plan

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        plan.blockers.append(f"{module_rel} doesn't parse: {e}")
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: set-literal rewrite would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
