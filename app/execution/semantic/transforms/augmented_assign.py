from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_rewrite_transformer as _run_rewrite_transformer

# Binary operators that have a corresponding in-place (augmented) form.
_AUG_OPS: tuple[type[ast.operator], ...] = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
    ast.RShift,
    ast.LShift,
)


def _rewrite_node(node: ast.Assign) -> ast.AugAssign | None:
    """Return an AugAssign for `x = x <op> rhs`, else None.

    Safety conditions (deliberately strict):
      * Exactly one target.
      * Target AND the binop's LEFT operand are both bare ``Name`` nodes with
        the same identifier. We refuse attribute/subscript targets such as
        ``obj.x = obj.x + 1`` because ``obj.x += 1`` would evaluate ``obj``
        only once for the AugAssign whereas the original evaluates it twice;
        if ``obj`` is a property / has side effects, semantics differ.
      * The repeated name must be on the LEFT of the binop. ``x = a + x`` is
        NOT rewritten: for non-commutative ops (``-``, ``/``, ``**`` ...) the
        result differs, and even for ``+`` an overloaded type dispatches
        ``__add__``/``__radd__`` differently from ``__iadd__``.
    """
    if len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        return None
    value = node.value
    if not isinstance(value, ast.BinOp):
        return None
    if not isinstance(value.op, _AUG_OPS):
        return None
    left = value.left
    if not isinstance(left, ast.Name):
        return None
    if left.id != target.id:
        return None
    new_target = ast.Name(id=target.id, ctx=ast.Store())
    return ast.AugAssign(target=new_target, op=value.op, value=value.right)


class _AugAssignTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        rewritten = _rewrite_node(node)
        if rewritten is None:
            return node
        self.changed = True
        return ast.copy_location(rewritten, node)


def apply(rel_path: str, source: str) -> SemanticPatchResult | None:
    tree = _parse_or_none(source)
    if tree is None:
        return None

    transformer = _AugAssignTransformer()
    new_source = _run_rewrite_transformer(tree, transformer, source)
    if new_source is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="augmented_assign",
        rationale=[f"Rewrote `x = x <op> y` as augmented assignment in {rel_path}."],
    )
