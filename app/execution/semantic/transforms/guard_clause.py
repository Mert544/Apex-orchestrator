from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent


def _is_docstring(stmt: ast.stmt) -> bool:
    # A bare string constant as the first statement is the function docstring.
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _guard_arg(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    # Guard a real input — not the instance/class receiver. `if not self`
    # in __init__ is meaningless (self is never None) and can even call
    # __bool__/__len__ on a half-built object.
    for a in node.args.args:
        if a.arg not in ("self", "cls"):
            return a.arg
    return None


def _insert_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    # Insert the guard AFTER a leading docstring, otherwise the docstring
    # is demoted to a dead string expression and the function loses its
    # __doc__. body[0] is the docstring when it is a bare string constant.
    first_stmt = node.body[0]
    if not _is_docstring(first_stmt):
        return first_stmt.lineno - 1
    if len(node.body) > 1:
        return node.body[1].lineno - 1
    return first_stmt.end_lineno or first_stmt.lineno


def _build_result(
    rel_path: str, source: str, lines: list[str],
    indent: str, first_arg: str, insert_line: int,
) -> SemanticPatchResult:
    guard = f'{indent}    if not {first_arg}:\n{indent}        raise ValueError("{first_arg} is required")\n'
    new_lines = lines[:insert_line] + [guard] + lines[insert_line:]
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(new_lines),
            "expected_old_content": source,
        }],
        transform_type="add_guard_clause",
        rationale=[f"Added input guard for '{first_arg}' in {rel_path}."],
    )


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first_arg = _guard_arg(node)
        if first_arg is None or f"if not {first_arg}:" in source:
            continue
        lineno = node.lineno - 1
        indent = _get_indent(lines[lineno]) if lineno < len(lines) else "    "
        return _build_result(
            rel_path, source, lines, indent, first_arg, _insert_line(node),
        )
    return None
