"""Simplify boolean ternaries — collapse ``True if c else False``.

The EXPRESSION-level sibling of :mod:`app.execution.bool_return` (which only
handles boolean *if-statements*). A conditional expression whose two arms are
the differing boolean constants ``True``/``False`` is just a boolean coercion of
its test::

    True if c else False          -> bool(c)
    False if c else True          -> not (c)

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.IfExp`` whose ``body`` and ``orelse`` are BOTH the exact
    boolean Constants ``True``/``False`` (never ``1``/``0``, never any other
    value) and they DIFFER — ``True if c else True`` and ``a if c else b`` are
    left alone;
  - the ternary must live on a SINGLE line (``lineno == end_lineno``) so the
    column-span splice is trivially correct — multi-line ``IfExp`` is skipped;
  - the test's ORIGINAL source text is recovered via ``ast.get_source_segment``
    and wrapped in parens, so the result parses correctly whatever the test's
    precedence — ``True if a and b else False`` -> ``bool(a and b)``;
  - if the test segment can't be recovered, that occurrence is skipped.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Rewrites are applied
bottom-up and right-to-left within a line so earlier offsets stay valid (so two
ternaries on one line, or a ternary nested in a larger expression, are handled).
The rewritten module must re-parse or the whole plan blocks.

Conservative by design — any ambiguity skips that occurrence, never a guess.
Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import apply_column_rewrites, is_fixture_path
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_simplify_ternary_bool"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


def _exact_bool(node: ast.AST) -> bool | None:
    """``True``/``False`` if ``node`` is exactly that boolean Constant, else
    None. ``1``/``0`` and any non-bool constant yield None — ``True is 1`` is a
    value coincidence we never trade on."""
    if isinstance(node, ast.Constant) and node.value is True:
        return True
    if isinstance(node, ast.Constant) and node.value is False:
        return False
    return None


def _replacement(body_val: bool, test_src: str) -> str:
    """The replacement for ``<body> if c else <orelse>``. ``True``/``False`` ->
    ``bool(c)``; ``False``/``True`` -> ``not (c)``. The test is always wrapped
    in parens so precedence is preserved regardless of the test's shape."""
    if body_val:
        return f"bool({test_src})"
    return f"not ({test_src})"


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _try_ifexp(node: ast.IfExp, source: str) -> _Rewrite | None:
    """If ``node`` is a simplifiable boolean ternary, return its rewrite, else
    None."""
    if node.lineno != node.end_lineno:
        return None
    body_val = _exact_bool(node.body)
    orelse_val = _exact_bool(node.orelse)
    if body_val is None or orelse_val is None or body_val == orelse_val:
        return None
    test_src = ast.get_source_segment(source, node.test)
    if test_src is None:
        return None
    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    _replacement(body_val, test_src))


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every simplifiable boolean ternary in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp):
            rw = _try_ifexp(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_simplify_ternary_bool(project_root: str | Path,
                               module_rel: str) -> RenamePlan:
    """Build the single-module simplify-ternary-bool plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every exact
    ``True if c else False`` / ``False if c else True`` ternary in the file into
    ``bool(c)`` / ``not (c)``. An empty plan means nothing matched (a no-op, not
    a failure)."""
    plan = RenamePlan(old=module_rel, new="simplify-ternary-bool")
    if _is_fixture_path(module_rel):
        return plan

    path = Path(project_root) / module_rel
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
            f"{module_rel}: simplification would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
