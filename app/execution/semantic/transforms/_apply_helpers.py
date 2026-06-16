"""Shared helpers reused byte-identically by sibling semantic transforms.

Several transforms independently extracted the *same* helper while shrinking
their ``apply`` functions in parallel; those copies were genuinely identical
(same executable body) and are consolidated here so a fix lands in one place.
Each transform imports the helper under its existing private alias, so call
sites stay behavior-identical. Deterministic, stdlib-only, offline.
"""

from __future__ import annotations

import ast


def node_offset(source: str, node: ast.AST) -> int | None:
    """Convert a node's ``(lineno, col_offset)`` into an absolute string offset.

    Returns ``None`` when the node carries no position or points past the end of
    ``source``. ``col_offset`` is a UTF-8 byte offset; the byte prefix is decoded
    so the splice lands correctly even with non-ASCII text earlier on the line.
    """
    lineno = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    if lineno is None or col is None:
        return None
    lines = source.splitlines(keepends=True)
    if lineno - 1 >= len(lines):
        return None
    offset = sum(len(lines[i]) for i in range(lineno - 1))
    # col_offset is a byte offset; decode the byte prefix to a char offset so the
    # splice lands correctly even with non-ASCII text earlier on the line.
    line = lines[lineno - 1]
    prefix = line.encode("utf-8")[:col].decode("utf-8", errors="ignore")
    return offset + len(prefix)
