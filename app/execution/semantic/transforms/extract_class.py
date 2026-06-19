from __future__ import annotations

import ast


from ..result import SemanticPatchResult
from .base import _get_indent


def _find_first_class(tree: ast.AST) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            return node
    return None


def _resolve_indents(lines: list[str], target_class: ast.ClassDef) -> tuple[str, str]:
    base_indent = (
        _get_indent(lines[target_class.lineno - 1])
        if target_class.lineno - 1 < len(lines)
        else ""
    )
    return base_indent, base_indent + "    "


def _normalize_method(method_lines: list[str], body_indent: str) -> list[str]:
    normalized = []
    for line in method_lines:
        if line.strip():
            normalized.append(line[len(body_indent):] if line.startswith(body_indent) else line)
        else:
            normalized.append("\n")
    return normalized


def _collect_extracted(
    target_class: ast.ClassDef,
    lines: list[str],
    methods: list[str],
    body_indent: str,
) -> list[str]:
    extracted_methods: list[str] = []
    for item in target_class.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in methods:
            start = item.lineno - 1
            end = getattr(item, "end_lineno", item.lineno)
            extracted_methods.extend(_normalize_method(lines[start:end], body_indent))
    return extracted_methods


def _build_class_text(
    base_indent: str,
    body_indent: str,
    new_class_name: str,
    base_class: str | None,
    extracted_methods: list[str],
) -> str:
    base = f"({base_class})" if base_class else ""
    new_class_lines = [f"{base_indent}class {new_class_name}{base}:\n"]
    for line in extracted_methods:
        new_class_lines.append(body_indent + line)
    if not new_class_lines[-1].endswith("\n"):
        new_class_lines[-1] += "\n"
    return "".join(new_class_lines)


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
    except (SyntaxError, RecursionError, MemoryError):
        return None

    target_class = _find_first_class(tree)
    if target_class is None:
        return None

    lines = source.splitlines(keepends=True)
    base_indent, body_indent = _resolve_indents(lines, target_class)
    extracted_methods = _collect_extracted(target_class, lines, methods, body_indent)
    if not extracted_methods:
        return None

    new_class_text = _build_class_text(
        base_indent, body_indent, new_class_name, base_class, extracted_methods
    )

    class_start = target_class.lineno - 1
    new_source = "".join(lines[:class_start] + [new_class_text + "\n"] + lines[class_start:])

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="extract_class",
        rationale=[f"Extracted methods {methods} into class '{new_class_name}' in {rel_path}."],
    )
