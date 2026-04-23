from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node) is None:
                lines = source.splitlines(keepends=True)
                lineno = node.lineno - 1
                indent = _get_indent(lines[lineno]) if lineno < len(lines) else ""
                body_indent = indent + "    "
                docstring = f'{body_indent}"""{title.strip(".")}."""\n'
                insert_at = lineno + 1
                if insert_at < len(lines) and lines[insert_at].strip().startswith('"""'):
                    continue
                new_lines = lines[:insert_at] + [docstring] + lines[insert_at:]
                new_content = "".join(new_lines)
                return SemanticPatchResult(
                    patch_requests=[{
                        "path": rel_path,
                        "new_content": new_content,
                        "expected_old_content": source,
                    }],
                    transform_type="add_docstring",
                    rationale=[f"Added missing docstring to {node.name} in {rel_path}."],
                )
    return None
