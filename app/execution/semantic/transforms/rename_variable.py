from __future__ import annotations

import ast

from ..result import SemanticPatchResult


class RenameTransformer(ast.NodeTransformer):
    def __init__(self, target: str, old: str, new: str):
        self.target = target
        self.old = old
        self.new = new
        self.in_target = False
        self.nested_depth = 0
        self.changed = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # type: ignore[misc]
        if node.name == self.target and self.nested_depth == 0:
            self.in_target = True
            self.nested_depth += 1
            result = self.generic_visit(node)
            self.in_target = False
            self.nested_depth -= 1
            return result
        if self.in_target:
            return node
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # type: ignore[misc]
        return self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if self.in_target and node.id == self.old:
            node.id = self.new
            self.changed = True
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        if self.in_target and node.arg == self.old:
            node.arg = self.new
            self.changed = True
        return node


def apply(
    rel_path: str, source: str, old_name: str, new_name: str, target_function: str
) -> SemanticPatchResult | None:
    if not old_name or not new_name or not target_function:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    transformer = RenameTransformer(target_function, old_name, new_name)
    new_tree = transformer.visit(tree)
    if not transformer.changed:
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
        transform_type="rename_variable",
        rationale=[f"Renamed '{old_name}' -> '{new_name}' in {target_function} ({rel_path})."],
    )
