from __future__ import annotations

import ast

from pathlib import Path

from ..result import SemanticPatchResult


def apply(rel_path: str, source: str, class_name: str, new_module: str) -> SemanticPatchResult | None:
    if not class_name or not new_module:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    class_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name]
    if not class_nodes:
        return None
    class_node = class_nodes[0]

    lines = source.splitlines(keepends=True)
    start = class_node.lineno - 1
    end = getattr(class_node, "end_lineno", class_node.lineno)
    class_lines = lines[start:end]
    class_text = "".join(class_lines)

    new_module_content = class_text
    if not new_module_content.endswith("\n"):
        new_module_content += "\n"

    module_path = new_module.replace('/', '.').replace('\\', '.').rstrip('.py')
    import_line = f"from {module_path} import {class_name}\n"
    new_lines = lines[:start] + [import_line] + lines[end:]
    new_source = "".join(new_lines)

    return SemanticPatchResult(
        patch_requests=[
            {
                "path": rel_path,
                "new_content": new_source,
                "expected_old_content": source,
            },
            {
                "path": new_module,
                "new_content": new_module_content,
                "expected_old_content": None,
            },
        ],
        transform_type="move_class",
        rationale=[f"Moved class '{class_name}' to {new_module} and replaced with import."],
    )
