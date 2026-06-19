"""Shared helpers reused byte-identically by sibling semantic transforms.

Several transforms independently extracted the *same* helper while shrinking
their ``apply`` functions in parallel; those copies were genuinely identical
(same executable body) and are consolidated here so a fix lands in one place.
Each transform imports the helper under its existing private alias, so call
sites stay behavior-identical. Deterministic, stdlib-only, offline.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


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


def parse_or_none(source: str) -> ast.Module | None:
    """Parse ``source`` to a module, returning ``None`` on a syntax error.

    Consolidates the ``try: tree = ast.parse(source) except SyntaxError: return
    None`` parse-guard that several ``apply`` functions opened with, byte-for-byte.
    """
    try:
        return ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None


def run_rewrite_transformer(
    tree: ast.Module,
    transformer: ast.NodeTransformer,
    source: str,
) -> str | None:
    """Drive a rewrite ``NodeTransformer`` and return new source, or ``None``.

    Consolidates the visit-driver tail shared byte-for-byte by the AST-rewriting
    transforms (``augmented_assign``, ``chained_comparison``, ``startswith_tuple``):
    visit the tree, bail if nothing changed, fix locations, unparse, re-parse to
    guarantee the result is syntactically valid, restore a trailing newline, and
    refuse a no-op. The caller constructs its own ``transformer`` and builds the
    patch result; only the identical middle stays here.
    """
    new_tree = transformer.visit(tree)
    if not transformer.changed:  # type: ignore[attr-defined]
        return None

    ast.fix_missing_locations(new_tree)
    try:
        new_source = ast.unparse(new_tree)
    except Exception:
        return None

    # Re-parse to guarantee the rewrite is syntactically valid before emitting.
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    if source.endswith("\n") and not new_source.endswith("\n"):
        new_source += "\n"

    if new_source == source:
        return None

    return new_source


def parse_and_collect_lines(
    source: str,
    collect: Callable[[ast.Module], list],
) -> tuple[list, list[str]] | None:
    """Parse, collect target nodes, and split into lines for splice-based transforms.

    Consolidates the prologue shared byte-for-byte by the line-splicing transforms
    (``collection_literal``, ``isinstance_merge``, ``negated_comparison``): parse
    the source (bail on syntax error), collect candidate nodes via ``collect``,
    bail when there are none, and split ``source`` into keepends lines. Returns
    ``(nodes, lines)`` or ``None``; the caller still drives its own splice loop.
    """
    tree = parse_or_none(source)
    if tree is None:
        return None
    nodes = collect(tree)
    if not nodes:
        return None
    return nodes, source.splitlines(keepends=True)
