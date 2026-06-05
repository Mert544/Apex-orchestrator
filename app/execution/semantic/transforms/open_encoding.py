"""Add an explicit encoding to text-mode ``open()`` calls.

``open(path)`` uses the platform's locale default encoding (UTF-8 on
Linux/macOS, often cp1252 on Windows), so the same code reads and writes text
differently across machines — a classic portability bug (pylint W1514). Adding
``encoding="utf-8"`` makes it deterministic.

Binary-mode opens (a ``b`` in the mode) take no encoding and are left untouched,
as are calls that already pass ``encoding=`` or whose mode is dynamic (we can't
prove it is text). Only single-line calls are rewritten — a multi-line call is
skipped to keep the edit line-exact and safe.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def _is_text_open_without_encoding(node: ast.Call) -> bool:
    """True if ``node`` is a builtin text-mode ``open()`` lacking ``encoding=``."""
    if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
        return False
    if not node.args:
        return False  # open() needs at least a path; a bare open() is not ours
    # A `**kwargs` (keyword with arg=None) could smuggle in encoding — stay safe.
    if any(kw.arg is None for kw in node.keywords):
        return False
    if any(kw.arg == "encoding" for kw in node.keywords):
        return False
    # Resolve the mode: positional arg[1] or keyword mode=.
    mode_node: ast.expr | None = node.args[1] if len(node.args) >= 2 else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    if mode_node is not None:
        if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
            return False  # dynamic mode — can't prove it is text
        if "b" in mode_node.value:
            return False  # binary mode takes no encoding
    return True


def _open_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _is_text_open_without_encoding(n)
    ]


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    calls = _open_calls(tree)
    if not calls:
        return None

    lines = source.splitlines(keepends=True)
    changed = 0
    # Rightmost first so inserting into one call never shifts an earlier call on
    # the same line.
    for node in sorted(calls, key=lambda c: (c.lineno, c.col_offset), reverse=True):
        if node.lineno != node.end_lineno:
            continue  # multi-line call — skip to keep the edit line-exact
        li = node.lineno - 1
        if li >= len(lines):
            continue
        line = lines[li]
        close = (node.end_col_offset or 0) - 1  # index of the closing ')'
        if close <= node.col_offset or close > len(line):
            continue
        # Insert a comma only if the args don't already end with one.
        j = close - 1
        while j > node.col_offset and line[j].isspace():
            j -= 1
        insert = ' encoding="utf-8"' if line[j] == "," else ', encoding="utf-8"'
        lines[li] = line[:close] + insert + line[close:]
        changed += 1

    if changed == 0:
        return None
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(lines),
            "expected_old_content": source,
        }],
        transform_type="add_open_encoding",
        rationale=[
            f"Added explicit encoding=\"utf-8\" to {changed} text-mode open() "
            f"call(s) in {rel_path} (portability — avoids locale-dependent decoding)."
        ],
    )
