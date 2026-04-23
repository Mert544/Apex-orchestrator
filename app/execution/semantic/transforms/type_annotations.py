from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)
    modified = False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is None:
                lineno = node.lineno - 1
                line = lines[lineno]
                stripped = line.rstrip()
                if stripped.endswith(":"):
                    if "->" not in stripped:
                        new_line = stripped[:-1] + " -> None:\n"
                        lines[lineno] = new_line
                        modified = True
                        break

    if not modified:
        return None

    new_content = "".join(lines)
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="add_type_annotations",
        rationale=[f"Added missing return type annotation in {rel_path}."],
    )
