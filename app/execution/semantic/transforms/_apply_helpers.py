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


def _node_span(source: str, node: ast.AST) -> tuple[int, int] | None:
    """Absolute ``(start, end)`` char offsets of ``node`` in ``source``.

    Uses the node's full position quad (``lineno``/``col_offset`` and
    ``end_lineno``/``end_col_offset``). Returns ``None`` when any coordinate is
    missing or points past the end of ``source``, or when the span is empty.
    Byte ``col_offset``s are decoded so the offsets land on character boundaries.
    """
    start = node_offset(source, node)
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if start is None or end_lineno is None or end_col is None:
        return None
    lines = source.splitlines(keepends=True)
    if end_lineno - 1 >= len(lines):
        return None
    end_off = sum(len(lines[i]) for i in range(end_lineno - 1))
    end_line = lines[end_lineno - 1]
    end_prefix = end_line.encode("utf-8")[:end_col].decode("utf-8", errors="ignore")
    end = end_off + len(end_prefix)
    if end <= start or end > len(source):
        return None
    return start, end


def _outermost_spans(
    source: str,
    replacements: list[tuple[ast.AST, ast.AST]],
) -> list[tuple[int, int, ast.AST]] | None:
    """Resolve each ``(original, new)`` pair to its OUTERMOST source span.

    Returns ``(start, end, new_node)`` triples, or ``None`` if any original node
    lacks a usable position quad (so the caller refuses rather than reformats).
    A replaced ancestor's span subsumes any replaced descendant's (e.g. a nested
    ``or`` whose parent ``or`` is also merged); the contained ones are dropped
    because the outer splice already covers their edit.
    """
    spans: list[tuple[int, int, ast.AST]] = []
    for original, new_node in replacements:
        span = _node_span(source, original)
        if span is None:
            return None
        spans.append((span[0], span[1], new_node))

    spans.sort(key=lambda s: (s[0], -s[1]))
    outer: list[tuple[int, int, ast.AST]] = []
    covered_end = -1
    for start, end, new_node in spans:
        if start >= covered_end:  # not contained in an already-kept outer span
            outer.append((start, end, new_node))
            covered_end = end
    return outer


def _splice_outermost(
    source: str,
    outer: list[tuple[int, int, ast.AST]],
) -> str | None:
    """Splice each outermost span's unparsed replacement into ``source``.

    Rightmost-first so each splice leaves earlier offsets unchanged. Returns the
    rewritten text, or ``None`` if any replacement node cannot be unparsed.
    """
    new_source = source
    for start, end, new_node in sorted(outer, key=lambda s: s[0], reverse=True):
        try:
            rendered = ast.unparse(new_node)
        except Exception:
            return None
        new_source = new_source[:start] + rendered + new_source[end:]
    return new_source


def run_rewrite_transformer(
    tree: ast.Module,
    transformer: ast.NodeTransformer,
    source: str,
) -> str | None:
    """Drive a rewrite ``NodeTransformer`` and return new source, or ``None``.

    Surgically splices each rewritten construct back into the ORIGINAL source
    text — only the bytes spanning a changed node are replaced, so every comment
    (including ``# type: ignore`` / ``# noqa`` / ``# pyright: ignore`` pragmas),
    quote style, and blank line OUTSIDE the changed construct survives untouched.
    A whole-file ``ast.unparse`` would discard all of those; this never does.

    The transformer records each rewrite by appending an
    ``(original_node, replacement_node)`` pair to its ``replacements`` list (the
    original node keeps the ``ast.parse`` positions that locate its span). We
    keep only outermost spans, splice rightmost-first, and re-parse the result to
    guarantee it is syntactically valid before emitting. If any target node lacks
    a usable single-construct span, we REFUSE (return ``None``) rather than fall
    back to reformatting the whole file.
    """
    transformer.visit(tree)
    if not transformer.changed:  # type: ignore[attr-defined]
        return None
    replacements = getattr(transformer, "replacements", None)
    if not replacements:
        return None

    outer = _outermost_spans(source, replacements)
    if outer is None:
        return None
    new_source = _splice_outermost(source, outer)
    if new_source is None:
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
