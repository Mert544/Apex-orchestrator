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
            # Guard a real input — not the instance/class receiver. `if not self`
            # in __init__ is meaningless (self is never None) and can even call
            # __bool__/__len__ on a half-built object.
            arg_names = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
            if not arg_names:
                continue
            first_arg = arg_names[0]
            lineno = node.lineno - 1
            indent = _get_indent(lines[lineno]) if lineno < len(lines) else "    "
            # Insert the guard AFTER a leading docstring, otherwise the docstring
            # is demoted to a dead string expression and the function loses its
            # __doc__. body[0] is the docstring when it is a bare string constant.
            first_stmt = node.body[0]
            anchor = first_stmt
            if (
                isinstance(first_stmt, ast.Expr)
                and isinstance(first_stmt.value, ast.Constant)
                and isinstance(first_stmt.value.value, str)
            ):
                anchor = node.body[1] if len(node.body) > 1 else first_stmt
                insert_line = (
                    anchor.lineno - 1 if anchor is not first_stmt
                    else (first_stmt.end_lineno or first_stmt.lineno)
                )
            else:
                insert_line = anchor.lineno - 1
            guard = f'{indent}    if not {first_arg}:\n{indent}        raise ValueError("{first_arg} is required")\n'
            if f"if not {first_arg}:" in source:
                continue
            new_lines = lines[:insert_line] + [guard] + lines[insert_line:]
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
