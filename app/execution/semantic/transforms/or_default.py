from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_splice_rewrite as _run_splice_rewrite


def _pure_expr(node: ast.expr) -> bool:
    """True only for expressions that are safe to evaluate exactly once instead
    of twice — a Name, or a chain of attribute accesses bottoming out in a Name.

    A ``a if a else b`` ternary evaluates ``a`` for the test AND (when truthy)
    re-uses the same ``a`` value, but ``a or b`` evaluates ``a`` a single time.
    The rewrite is only value-identical when ``a`` is side-effect-free and yields
    the same object each read, so calls, subscripts, comprehensions, etc. are
    refused (their second evaluation might differ or have side effects).
    """
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _pure_expr(node.value)
    return False


def _same_expr(a: ast.expr, b: ast.expr) -> bool:
    """Structural equality for two pure (Name/Attribute-chain) expressions."""
    if type(a) is not type(b):
        return False
    if isinstance(a, ast.Name) and isinstance(b, ast.Name):
        return a.id == b.id
    if isinstance(a, ast.Attribute) and isinstance(b, ast.Attribute):
        return a.attr == b.attr and _same_expr(a.value, b.value)
    return False


class _OrDefaultTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_IfExp(self, node: ast.IfExp) -> ast.AST:
        # Recurse first so nested ternaries still rewrite.
        self.generic_visit(node)
        test = node.test
        if not _pure_expr(test):
            return node
        if not _same_expr(test, node.body):
            return node
        new_node = ast.BoolOp(op=ast.Or(), values=[node.body, node.orelse])
        self.changed = True
        return ast.copy_location(new_node, node)


def apply(rel_path: str, source: str, title: str = "") -> SemanticPatchResult | None:
    tree = _parse_or_none(source)
    if tree is None:
        return None

    transformer = _OrDefaultTransformer()
    new_source = _run_splice_rewrite(tree, transformer, source)
    if new_source is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="or_default",
        rationale=[f"Rewrote `a if a else b` into `a or b` in {rel_path}."],
    )
