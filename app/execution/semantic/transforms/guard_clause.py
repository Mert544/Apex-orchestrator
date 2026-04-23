from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.args.args:
                continue
            first_arg = node.args.args[0].arg
            lineno = node.lineno - 1
            indent = _get_indent(lines[lineno]) if lineno < len(lines) else "    "
            body_start = node.body[0].lineno - 1
            guard = f'{indent}    if not {first_arg}:\n{indent}        raise ValueError("{first_arg} is required")\n'
            if f"if not {first_arg}:" in source:
                continue
            new_lines = lines[:body_start] + [guard] + lines[body_start:]
            new_content = "".join(new_lines)
            return SemanticPatchResult(
                patch_requests=[{
                    "path": rel_path,
                    "new_content": new_content,
                    "expected_old_content": source,
                }],
                transform_type="add_guard_clause",
                rationale=[f"Added input guard for '{first_arg}' in {rel_path}."],
            )
    return None
