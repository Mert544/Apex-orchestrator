from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def apply(rel_path: str, source: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                used_names.add(node.value.id)

    unused_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            all_unused = True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    if name in used_names:
                        all_unused = False
                        break
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name in used_names:
                        all_unused = False
                        break
                if module.split(".")[0] in used_names:
                    all_unused = False
            if all_unused:
                for lineno in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                    unused_lines.add(lineno)

    if not unused_lines:
        return None

    lines = source.splitlines(keepends=True)
    new_lines = [line for i, line in enumerate(lines, start=1) if i not in unused_lines]
    new_content = "".join(new_lines)
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="organize_imports",
        rationale=[f"Removed {len(unused_lines)} unused import lines in {rel_path}."],
    )
