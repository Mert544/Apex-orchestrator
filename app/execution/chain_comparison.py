"""Chain comparison — rewrite ``a < b and b < c`` into ``a < b < c``.

A small, surgical modernization: two comparisons joined by ``and`` that share an
identical, side-effect-free MIDDLE operand are exactly one Python comparison
chain, which evaluates that middle operand once instead of twice::

    a < b and b < c        -> a < b < c
    a <= b and b <= c      -> a <= b <= c
    x > y and y > z        -> x > y > z
    a == b and b == c      -> a == b == c

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the whole expression is an ``ast.BoolOp(op=ast.And)`` with EXACTLY TWO
    values, both ``ast.Compare`` and each with exactly ONE operator
    (``len(ops) == 1``);
  - writing the first ``X op1 Y`` and the second ``Y2 op2 Z``, the shared middle
    must be identical (``ast.dump(Y) == ast.dump(Y2)``) AND side-effect-free — a
    bare ``Name``, an attribute-chain of Names (``x.n.m``), or a ``Constant``.
    A ``Call``/``Subscript`` middle is NEVER chained: chaining evaluates the
    middle once, so a side-effecting middle would change behaviour;
  - ``op1`` and ``op2`` must be in the SAME monotonic family so the chain is
    equivalent — both in ``{Lt, LtE}``, both in ``{Gt, GtE}``, or both ``Eq``.
    Mixed directions, ``!=``, ``is`` and ``in`` are skipped;
  - the BoolOp must live on a SINGLE line so the column-span splice is trivially
    correct — multi-line BoolOps are skipped.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. The rewrite reuses the
ORIGINAL source segments for ``X``, ``Y`` and ``Z`` and the literal operator
texts (``<``, ``<=``, ``>``, ``>=``, ``==``). Conservative by design — any
source segment that can't be recovered skips that occurrence, and the rewritten
module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left within a line so earlier
offsets stay valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_column_rewrites,
    splice_operand,
)
from app.execution._transform_base import plan_single_module_rewrite
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_chain_comparison"]

# Literal source text for each chainable comparison operator.
_OP_TEXT: dict[type, str] = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
}

# Each operator's monotonic family. op1 and op2 must share a family for the
# chain to be equivalent to the ``and`` it replaces.
_OP_FAMILY: dict[type, str] = {
    ast.Lt: "lt",
    ast.LtE: "lt",
    ast.Gt: "gt",
    ast.GtE: "gt",
    ast.Eq: "eq",
}



class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _is_side_effect_free(node: ast.AST) -> bool:
    """True for an operand whose double evaluation is observably identical to a
    single evaluation: a bare ``Name``, an attribute-chain of Names (``x.n.m``),
    or a ``Constant``. A ``Call``/``Subscript`` (or anything containing one) is
    rejected — chaining would change how many times it runs."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_side_effect_free(node.value)
    return False


def _pair_of_comparisons(node: ast.BoolOp) -> tuple[ast.Compare, ast.Compare] | None:
    """The two single-line ``and``-ed values when each is an ``ast.Compare`` with
    exactly one operator, else None — the structural gate before operators."""
    if not isinstance(node.op, ast.And):
        return None
    if node.lineno != node.end_lineno:
        return None
    if len(node.values) != 2:
        return None
    left, right = node.values
    if not (isinstance(left, ast.Compare) and isinstance(right, ast.Compare)):
        return None
    if len(left.ops) != 1 or len(right.ops) != 1:
        return None
    return left, right


def _same_family(op1: type, op2: type) -> bool:
    """True iff both operators are chainable and share a monotonic family, so the
    chain is equivalent to the ``and`` it replaces."""
    if op1 not in _OP_FAMILY or op2 not in _OP_FAMILY:
        return False
    return _OP_FAMILY[op1] == _OP_FAMILY[op2]


def _shared_middle(
        left: ast.Compare, right: ast.Compare) -> bool:
    """True iff left's right comparator and right's left operand are an identical
    (by ``ast.dump``) side-effect-free middle — the once-evaluated chain pivot."""
    middle_left = left.comparators[0]
    if ast.dump(middle_left) != ast.dump(right.left):
        return False
    return _is_side_effect_free(middle_left)


def _try_boolop(node: ast.BoolOp, source: str) -> _Rewrite | None:
    """If ``node`` is a chainable ``X op1 Y and Y op2 Z`` BoolOp, return its
    rewrite, else None."""
    pair = _pair_of_comparisons(node)
    if pair is None:
        return None
    left, right = pair

    op1 = type(left.ops[0])
    op2 = type(right.ops[0])
    if not _same_family(op1, op2):
        return None

    if not _shared_middle(left, right):
        return None

    x_src = splice_operand(source, left.left)
    y_src = splice_operand(source, left.comparators[0])
    z_src = splice_operand(source, right.comparators[0])
    if x_src is None or y_src is None or z_src is None:
        return None

    text = f"{x_src} {_OP_TEXT[op1]} {y_src} {_OP_TEXT[op2]} {z_src}"
    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset, text)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every chainable comparison BoolOp in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp):
            rw = _try_boolop(node, source)
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


def plan_chain_comparison(project_root: str | Path,
                          module_rel: str) -> RenamePlan:
    """Build the single-module chain-comparison plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every exact
    ``X op1 Y and Y op2 Z`` shape (shared side-effect-free middle, same operator
    family) into the comparison chain ``X op1 Y op2 Z``. An empty plan means
    nothing matched — a no-op, not a failure."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="chain-comparison",
        collect=_collect_rewrites,
        apply=_apply,
        reparse_phrase="chaining")
