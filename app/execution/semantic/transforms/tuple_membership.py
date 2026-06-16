from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def _is_side_effect_free_chain(node: ast.AST) -> bool:
    """A Name or attribute chain rooted at a Name, with no calls/subscripts."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _is_simple_operand(node: ast.AST) -> bool:
    """Right-hand side must be a simple, side-effect-free value."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_side_effect_free_chain(node)
    return False


def _rewrite_or(node: ast.BoolOp) -> ast.Compare | None:
    """Return an `x in (...)` Compare for a qualifying `or` BoolOp, else None."""
    if not isinstance(node.op, ast.Or):
        return None
    if len(node.values) < 2:
        return None

    left_ref: ast.AST | None = None
    rights: list[ast.AST] = []

    for term in node.values:
        if not isinstance(term, ast.Compare):
            return None
        # exactly one `==` comparison: `left == right`
        if len(term.ops) != 1 or not isinstance(term.ops[0], ast.Eq):
            return None
        left = term.left
        right = term.comparators[0]
        if not _is_side_effect_free_chain(left):
            return None
        if not _is_simple_operand(right):
            return None
        if left_ref is None:
            left_ref = left
        elif ast.dump(left) != ast.dump(left_ref):
            return None
        rights.append(right)

    if left_ref is None or len(rights) < 2:
        return None

    return ast.Compare(
        left=left_ref,
        ops=[ast.In()],
        comparators=[ast.Tuple(elts=rights, ctx=ast.Load())],
    )


class _MembershipTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        rewritten = _rewrite_or(node)
        if rewritten is not None:
            self.changed = True
            return ast.copy_location(rewritten, node)
        return node


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    transformer = _MembershipTransformer()
    new_tree = transformer.visit(tree)
    if not transformer.changed:
        return None

    ast.fix_missing_locations(new_tree)
    try:
        new_content = ast.unparse(new_tree)
    except (ValueError, AttributeError):
        return None

    # Re-parse to guarantee the rewrite is well-formed.
    try:
        ast.parse(new_content)
    except SyntaxError:
        return None

    if new_content == source:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="tuple_membership",
        rationale=[f"Rewrote chained '==' or-comparisons as 'in' membership in {rel_path}."],
    )
