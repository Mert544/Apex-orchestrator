from __future__ import annotations

import ast


def _get_indent(line: str) -> str:
    stripped = line.lstrip()
    if stripped:
        return line[: line.index(stripped)]
    return line


def import_insert_index(tree: ast.Module) -> int:
    """The 0-based line index where a new top-level import may be safely inserted.

    Inserting at line 0 breaks a file that opens with ``from __future__ import
    annotations`` — a future import must be the first statement, so the generated
    code fails to compile. This returns the index *after* the module docstring
    and any ``__future__`` imports, so an injected import lands legally.
    """
    line = 0  # default: very top
    body = tree.body
    i = 0
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        line = body[0].end_lineno or 0      # past the docstring
        i = 1
    for node in body[i:]:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            line = node.end_lineno or line  # past each future import
        else:
            break
    return line
