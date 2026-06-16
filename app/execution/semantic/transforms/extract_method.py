from __future__ import annotations

import ast


from ..result import SemanticPatchResult
from .base import _get_indent


def _find_target_node(tree: ast.AST, target_function: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_function:
            return node
    return None


def _normalize_block(block_lines: list[str], min_indent: int) -> list[str]:
    normalized_block = []
    for line in block_lines:
        if line.strip():
            normalized_block.append(line[min_indent:])
        else:
            normalized_block.append("\n")
    return normalized_block


def _detect_return_var(normalized_block: list[str]) -> str:
    return_var = ""
    try:
        block_tree = ast.parse("".join(normalized_block))
        for node in ast.walk(block_tree):
            if (isinstance(node, ast.Assign)) and (node.targets and isinstance(node.targets[0], ast.Name)):
                return_var = node.targets[0].id
    except SyntaxError:
        pass
    return return_var


def _build_function_lines(base_indent: str, body_indent: str,
                          new_function_name: str, param_str: str,
                          normalized_block: list[str], return_var: str) -> list[str]:
    new_func_lines = [
        f"{base_indent}def {new_function_name}({param_str}):\n",
    ]
    for line in normalized_block:
        if line.endswith("\n"):
            new_func_lines.append(body_indent + line)
        else:
            new_func_lines.append(body_indent + line + "\n")
    if return_var:
        new_func_lines.append(f"{body_indent}return {return_var}\n")
    new_func_lines.append("\n")
    return new_func_lines


def _build_call_line(body_indent: str, new_function_name: str,
                     param_str: str, return_var: str) -> str:
    if return_var:
        return f"{body_indent}{return_var} = {new_function_name}({param_str})\n"
    return f"{body_indent}{new_function_name}({param_str})\n"


def _resolve_target(source: str, lines: list[str], start_line: int,
                    end_line: int, new_function_name: str,
                    target_function: str):
    """Validate inputs and locate the target function node, or ``None``."""
    if start_line < 1 or end_line < start_line or not new_function_name or not target_function:
        return None
    if end_line > len(lines):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return _find_target_node(tree, target_function)


def _block_indents(block_lines: list[str], lines: list[str], target_lineno: int):
    """Return ``(min_indent, base_indent, body_indent)`` for the block, or ``None``."""
    indents = [len(_get_indent(line)) for line in block_lines if line.strip()]
    if not indents:
        return None
    min_indent = min(indents)
    base_indent = _get_indent(lines[target_lineno - 1])
    return min_indent, base_indent, base_indent + "    "


def apply(
    rel_path: str,
    source: str,
    start_line: int,
    end_line: int,
    new_function_name: str,
    target_function: str,
    parameters: list[str],
) -> SemanticPatchResult | None:
    lines = source.splitlines(keepends=True)
    target_node = _resolve_target(
        source, lines, start_line, end_line, new_function_name, target_function,
    )
    if target_node is None:
        return None

    start_idx = start_line - 1
    end_idx = end_line - 1
    block_lines = lines[start_idx:end_idx + 1]
    if not block_lines:
        return None

    indent_info = _block_indents(block_lines, lines, target_node.lineno)
    if indent_info is None:
        return None
    min_indent, base_indent, body_indent = indent_info

    normalized_block = _normalize_block(block_lines, min_indent)
    return_var = _detect_return_var(normalized_block)

    param_str = ", ".join(parameters) if parameters else ""
    new_func_lines = _build_function_lines(
        base_indent, body_indent, new_function_name, param_str,
        normalized_block, return_var,
    )
    call_line = _build_call_line(body_indent, new_function_name, param_str, return_var)

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
