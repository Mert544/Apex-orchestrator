from __future__ import annotations

import ast

from ..result import SemanticPatchResult


class InlineTransformer(ast.NodeTransformer):
    def __init__(self, target: str, var: str):
        self.target = target
        self.var = var
        self.in_target = False
        self.assignment_node: ast.Assign | None = None
        self.changed = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # type: ignore[misc]
        if node.name == self.target:
            self.in_target = True
            result = self.generic_visit(node)
            self.in_target = False
            if self.assignment_node and isinstance(result, ast.FunctionDef):
                new_body = [s for s in result.body if s is not self.assignment_node]
                result.body = new_body
                self.changed = True
            return result
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # type: ignore[misc]
        return self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if self.in_target and self.assignment_node and node.id == self.var:
            return self.assignment_node.value
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        if self.in_target and not self.assignment_node:
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == self.var
            ):
                if isinstance(node.value, (ast.Name, ast.Constant, ast.BinOp)):
                    self.assignment_node = node
                    return node
        return self.generic_visit(node)


def apply(rel_path: str, source: str, var_name: str, target_function: str) -> SemanticPatchResult | None:
    if not var_name or not target_function:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    transformer = InlineTransformer(target_function, var_name)
    new_tree = transformer.visit(tree)
    if not transformer.changed or transformer.assignment_node is None:
        return None
    try:
        new_source = ast.unparse(new_tree)
    except Exception:
        return None
    if source.endswith("\n") and not new_source.endswith("\n"):
        new_source += "\n"
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="inline_variable",
        rationale=[f"Inlined variable '{var_name}' in {target_function} ({rel_path})."],
    )
