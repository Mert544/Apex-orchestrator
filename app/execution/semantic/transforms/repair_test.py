from __future__ import annotations

import ast

from typing import Any

from ..result import SemanticPatchResult


def apply(rel_path: str, source: str, repair: dict[str, Any]) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)
    modified = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            if node.msg is None:
                lineno = node.lineno - 1
                line = lines[lineno]
                stripped = line.rstrip()
                content = stripped.lstrip()
                indent = stripped[: len(stripped) - len(content)]
                if content.startswith("assert "):
                    expr = content[7:]
                    if not expr.endswith('"') and "#" not in expr:
                        new_content = f'{content}, "Assertion failed: {expr}"'
                        new_line = indent + new_content + "\n"
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
        transform_type="repair_test_assertion",
        rationale=[f"Added assertion message for better test diagnostics in {rel_path}."],
    )
