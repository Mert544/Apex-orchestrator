from __future__ import annotations

import ast

from typing import Any

from ..result import SemanticPatchResult
from .base import _get_indent


def apply(
    rel_path: str,
    source: str,
    start_line: int,
    end_line: int,
    new_function_name: str,
    target_function: str,
    parameters: list[str],
) -> SemanticPatchResult | None:
    if start_line < 1 or end_line < start_line or not new_function_name or not target_function:
        return None
    lines = source.splitlines(keepends=True)
    if end_line > len(lines):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_function:
            target_node = node
            break
    if target_node is None:
        return None

    start_idx = start_line - 1
    end_idx = end_line - 1
    block_lines = lines[start_idx:end_idx + 1]
    if not block_lines:
        return None

    indents = [len(_get_indent(line)) for line in block_lines if line.strip()]
    if not indents:
        return None
    min_indent = min(indents)
    base_indent = _get_indent(lines[target_node.lineno - 1])
    body_indent = base_indent + "    "

    normalized_block = []
    for line in block_lines:
        if line.strip():
            normalized_block.append(line[min_indent:])
        else:
            normalized_block.append("\n")

    return_var = ""
    try:
        block_tree = ast.parse("".join(normalized_block))
        for node in ast.walk(block_tree):
            if isinstance(node, ast.Assign):
                if node.targets and isinstance(node.targets[0], ast.Name):
                    return_var = node.targets[0].id
    except SyntaxError:
        pass

    param_str = ", ".join(parameters) if parameters else ""
    new_func_lines = [
        f"{base_indent}def {new_function_name}({param_str}):\n",
    ]
    for line in normalized_block:
        if line.endswith("\n"):
            new_func_lines.append(body_indent + line)
        else:
            new_func_lines.append(body_indent + line + "\n")
    if return_var:
        new_func_lines.append(f"{body_indent}    return {return_var}\n")
    new_func_lines.append("\n")

    if return_var:
        call_line = f"{body_indent}{return_var} = {new_function_name}({param_str})\n"
    else:
        call_line = f"{body_indent}{new_function_name}({param_str})\n"

    insert_at = target_node.lineno - 1
    new_lines = lines[:insert_at] + new_func_lines + lines[insert_at:start_idx] + [call_line] + lines[end_idx + 1:]
    new_content = "".join(new_lines)

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="extract_method",
        rationale=[f"Extracted lines {start_line}-{end_line} into {new_function_name} in {rel_path}."],
    )
