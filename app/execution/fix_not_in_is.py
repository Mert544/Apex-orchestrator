"""fix not in is — rewrite ``not a in b`` to ``a not in b`` (E713/E714).

The classic readability cleanup: Python negates a membership/identity test in
two equivalent ways, and only one reads as English::

    not a in b      ->  a not in b      (E713)
    not a is b      ->  a is not b      (E714)

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.UnaryOp(op=ast.Not, operand=X)`` where ``X`` is an
    ``ast.Compare`` with EXACTLY ONE operator (``len(X.ops) == 1``) that is
    ``ast.In`` or ``ast.Is`` — chained compares (``not a in b in c``) and any
    other operator (``not a == b``, ``not a < b``) are left untouched;
  - the whole ``UnaryOp`` lives on a SINGLE line (``lineno == end_lineno``) so
    the column-span splice is trivially correct — multi-line ``UnaryOp`` nodes
    are skipped;
  - the replacement is rebuilt from the ORIGINAL source segments of the compare's
    left operand and its single comparator (so attribute/subscript operands and
    any inner formatting survive), joined with `` not in `` / `` is not ``. A
    redundant paren pair around the operand (``not (a in b)``) is dropped as a
    natural consequence — the splice replaces the entire ``UnaryOp`` span.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Conservative by design —
any source segment that can't be recovered skips that occurrence, and the
rewritten module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left (sorted by ``(lineno,
col_offset)`` descending) so earlier offsets stay valid even when two negations
share a line or one is nested in another. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_column_rewrites,
    is_fixture_path,
    splice_operand,
)
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_fix_not_in_is"]


# The single-operator compare ops we negate, mapped to their negated text.
_NEGATED: dict[type[ast.cmpop], str] = {
    ast.In: " not in ",
    ast.Is: " is not ",
}

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


def _try_unaryop(node: ast.UnaryOp, source: str) -> _Rewrite | None:
    """If ``node`` is ``not a in b`` / ``not a is b`` (single-operator), return
    its rewrite, else None."""
    if not isinstance(node.op, ast.Not):
        return None
    compare = node.operand
    if not isinstance(compare, ast.Compare):
        return None
    if len(compare.ops) != 1:  # chained compare — never a partial rewrite
        return None
    joiner = _NEGATED.get(type(compare.ops[0]))
    if joiner is None:  # not In/Is — leave == < etc. alone
        return None
    if node.lineno != node.end_lineno:  # only single-line splices
        return None

    left = splice_operand(source, compare.left)
    right = splice_operand(source, compare.comparators[0])
    if left is None or right is None:  # can't recover source — skip
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    f"{left}{joiner}{right}")


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every negated single-operator ``in``/``is`` compare in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp):
            rw = _try_unaryop(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid (handles two on a line and one nested in another)."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_fix_not_in_is(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module fix-not-in-is plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every
    ``not a in b`` to ``a not in b`` and ``not a is b`` to ``a is not b`` whose
    shape matches exactly (single operator, single line, recoverable operands).
    An empty plan (no new_contents, no blockers) means nothing matched — a no-op,
    not a failure."""
    plan = RenamePlan(old=module_rel, new="fix-not-in-is")
    if _is_fixture_path(module_rel):
        return plan
    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan
    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="rewrite")
