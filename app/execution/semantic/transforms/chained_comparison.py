"""Merge two ``and``-joined comparisons that share a middle term into a chain.

Rewrites ``a < b and b < c`` into the equivalent chained comparison
``a < b < c`` (and the analogous ``>``, ``<=``, ``>=``, ``==`` chains) but ONLY
when the rewrite is provably semantics-preserving:

* the expression is exactly ``BoolOp(And, [Compare, Compare])`` where each
  ``Compare`` is a *single* comparison (one operator, two operands);
* the right operand of the first compare is STRUCTURALLY EQUAL to the left
  operand of the second compare (the shared middle term);
* that middle term is side-effect-free and re-evaluation-safe (a ``Name``, an
  attribute chain over names, or a constant -- never a call, subscript, walrus,
  comprehension, etc.); and
* the two operators point in a compatible direction so that the chain is legal
  and means the same thing (both non-decreasing, both non-increasing, or both
  equality).

Anything else returns ``None`` (refuse). The rewritten source is re-parsed and a
no-op result is rejected, so the file is never corrupted.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_rewrite_transformer as _run_rewrite_transformer

# Operators that may legally chain together. The middle term is evaluated once
# in the chain, so we only merge when both arms point the same way (or are both
# ``==``). Mixing e.g. ``<`` with ``>`` would change meaning, so it is refused.
_DIRECTION = {
    ast.Lt: "up",
    ast.LtE: "up",
    ast.Gt: "down",
    ast.GtE: "down",
    ast.Eq: "eq",
}


def _is_side_effect_free(node: ast.expr) -> bool:
    """True if ``node`` is a Name / attribute-chain / constant with no calls."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Attribute):
        return _is_side_effect_free(node.value)
    return False


def _structurally_equal(a: ast.expr, b: ast.expr) -> bool:
    """Compare two expression nodes for structural equality (ignoring positions)."""
    return ast.dump(a, annotate_fields=True) == ast.dump(b, annotate_fields=True)


def _has_side_effect(node: ast.expr) -> bool:
    """True if any sub-expression could carry a side effect or fail re-eval safety.

    We are deliberately conservative: a chain like ``f() < b and b < c`` is
    refused even though ``f`` only appears once, because the outer terms become
    part of a single chained expression and we want a clear, auditable rule that
    no calls / subscripts / walrus / comprehensions participate in the merge.
    """
    unsafe = (
        ast.Call,
        ast.Subscript,
        ast.NamedExpr,
        ast.Await,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.Yield,
        ast.YieldFrom,
    )
    return any(isinstance(sub, unsafe) for sub in ast.walk(node))


def _both_single_compares(node: ast.BoolOp):
    """Return ``(left, right)`` if the BoolOp is two single ``and``-joined compares.

    A single compare has exactly one operator and one comparator. Returns None
    unless every structural precondition holds.
    """
    if not isinstance(node.op, ast.And):
        return None
    if len(node.values) != 2:
        return None
    left, right = node.values
    if not isinstance(left, ast.Compare) or not isinstance(right, ast.Compare):
        return None
    if len(left.ops) != 1 or len(left.comparators) != 1:
        return None
    if len(right.ops) != 1 or len(right.comparators) != 1:
        return None
    return left, right


def _compatible_directions(left_op: ast.cmpop, right_op: ast.cmpop) -> bool:
    """True if both operators are chainable and point the same way (or both ==)."""
    if type(left_op) not in _DIRECTION or type(right_op) not in _DIRECTION:
        return False
    return _DIRECTION[type(left_op)] == _DIRECTION[type(right_op)]


def _safe_shared_middle(middle_a: ast.expr, middle_b: ast.expr) -> bool:
    """True if the two middle terms match and the middle is re-evaluation-safe."""
    if not _structurally_equal(middle_a, middle_b):
        return False
    return _is_side_effect_free(middle_a)


def _merge_boolop(node: ast.BoolOp) -> ast.Compare | None:
    """Return the merged chained ``Compare`` for a mergeable BoolOp, else None."""
    arms = _both_single_compares(node)
    if arms is None:
        return None
    left, right = arms

    left_op = left.ops[0]
    right_op = right.ops[0]
    if not _compatible_directions(left_op, right_op):
        return None

    # Shared middle term: right operand of first compare == left operand of second.
    middle_a = left.comparators[0]
    if not _safe_shared_middle(middle_a, right.left):
        return None

    # No participating operand may carry a side effect: the merge folds all four
    # operand slots into one expression, so we refuse if anything is unsafe.
    if any(_has_side_effect(op) for op in (left.left, middle_a, right.comparators[0])):
        return None

    chained = ast.Compare(
        left=left.left,
        ops=[left_op, right_op],
        comparators=[middle_a, right.comparators[0]],
    )
    return ast.copy_location(chained, node)


class _ChainTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        # Recurse first so nested BoolOps inside operands are handled too.
        self.generic_visit(node)
        merged = _merge_boolop(node)
        if merged is not None:
            self.changed = True
            return merged
        return node


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    tree = _parse_or_none(source)
    if tree is None:
        return None

    transformer = _ChainTransformer()
    new_source = _run_rewrite_transformer(tree, transformer, source)
    if new_source is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="chained_comparison",
        rationale=[f"Merged and-joined comparisons into a chain in {rel_path}."],
    )
