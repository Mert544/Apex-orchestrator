from __future__ import annotations

import ast

from typing import Any

from ..result import SemanticPatchResult
from .base import _get_indent


def apply(
    rel_path: str,
    source: str,
    methods: list[str],
    new_class_name: str,
    base_class: str | None,
) -> SemanticPatchResult | None:
    if not methods or not new_class_name:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    target_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            target_class = node
            break
    if target_class is None:
        return None

    lines = source.splitlines(keepends=True)
    extracted_methods = []
    remaining_body = []
    base_indent = _get_indent(lines[target_class.lineno - 1]) if target_class.lineno - 1 < len(lines) else ""
    body_indent = base_indent + "    "

    for item in target_class.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in methods:
            start = item.lineno - 1
            end = getattr(item, "end_lineno", item.lineno)
            method_lines = lines[start:end]
            normalized = []
            for line in method_lines:
                if line.strip():
                    normalized.append(line[len(body_indent):] if line.startswith(body_indent) else line)
                else:
                    normalized.append("\n")
            extracted_methods.extend(normalized)
        else:
            remaining_body.append(item)

    if not extracted_methods:
        return None

    base = f"({base_class})" if base_class else ""
    new_class_lines = [f"{base_indent}class {new_class_name}{base}:\n"]
    for line in extracted_methods:
        new_class_lines.append(body_indent + line)
    if not new_class_lines[-1].endswith("\n"):
        new_class_lines[-1] += "\n"
    new_class_text = "".join(new_class_lines)

    class_start = target_class.lineno - 1
    class_end = getattr(target_class, "end_lineno", target_class.lineno)
    new_lines = lines[:class_start] + [new_class_text + "\n"] + lines[class_start:]
    new_source = "".join(new_lines)

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="extract_class",
        rationale=[f"Extracted methods {methods} into class '{new_class_name}' in {rel_path}."],
    )
