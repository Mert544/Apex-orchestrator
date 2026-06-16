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


def _is_builtin_open_with_args(node: ast.Call) -> bool:
    """True if ``node`` calls the builtin ``open`` with at least a path arg."""
    return isinstance(node.func, ast.Name) and node.func.id == "open" and bool(node.args)


def _encoding_is_provable_absent(node: ast.Call) -> bool:
    """True only if no ``encoding=`` and no ``**kwargs`` could supply one."""
    # A `**kwargs` (keyword with arg=None) could smuggle in encoding — stay safe.
    if any(kw.arg is None for kw in node.keywords):
        return False
    return not any(kw.arg == "encoding" for kw in node.keywords)


def _resolve_mode_node(node: ast.Call) -> ast.expr | None:
    """The mode argument: positional arg[1] or a ``mode=`` keyword (keyword wins)."""
    mode_node: ast.expr | None = node.args[1] if len(node.args) >= 2 else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    return mode_node


def _mode_is_provable_text(mode_node: ast.expr | None) -> bool:
    """True if an absent/constant non-binary mode proves the call is text-mode."""
    if mode_node is None:
        return True
    if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
        return False  # dynamic mode — can't prove it is text
    return "b" not in mode_node.value  # binary mode takes no encoding


def _is_text_open_without_encoding(node: ast.Call) -> bool:
    """True if ``node`` is a builtin text-mode ``open()`` lacking ``encoding=``."""
    if not _is_builtin_open_with_args(node):
        return False
    if not _encoding_is_provable_absent(node):
        return False
    return _mode_is_provable_text(_resolve_mode_node(node))


def _open_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _is_text_open_without_encoding(n)
    ]


def _close_index(node: ast.Call, line: str) -> int | None:
    """Index of the closing ``)`` in ``line``, or ``None`` if out of bounds."""
    close = (node.end_col_offset or 0) - 1  # index of the closing ')'
    if close <= node.col_offset or close > len(line):
        return None
    return close


def _encoding_insert(line: str, col_offset: int, close: int) -> str:
    """The text to splice before ``close`` (comma only if not already present)."""
    # Insert a comma only if the args don't already end with one.
    j = close - 1
    while j > col_offset and line[j].isspace():
        j -= 1
    return ' encoding="utf-8"' if line[j] == "," else ', encoding="utf-8"'


def _rewrite_open_line(node: ast.Call, line: str) -> str | None:
    """Return ``line`` with an ``encoding="utf-8"`` arg added, or ``None`` to skip."""
    if node.lineno != node.end_lineno:
        return None  # multi-line call — skip to keep the edit line-exact
    close = _close_index(node, line)
    if close is None:
        return None
    insert = _encoding_insert(line, node.col_offset, close)
    return line[:close] + insert + line[close:]


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
        li = node.lineno - 1
        if li >= len(lines):
            continue
        rewritten = _rewrite_open_line(node, lines[li])
        if rewritten is None:
            continue
        lines[li] = rewritten
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
