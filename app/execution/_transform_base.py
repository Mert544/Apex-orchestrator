"""Shared primitives for the single-module source transforms.

The deterministic, AST-located rewrites under ``app/execution/`` (bool-return,
merge-isinstance, fix-not-in-is, chain-comparison, set-literal, ternary-bool,
collapse-startswith, list/dict comprehension, redundant-else) each used to carry
their own private copy of the same four helpers. That repetition is exactly what
``apex grade`` flagged as duplication, so the identical primitives live here once
and every transform imports them.

This is a **library** (leading underscore in the filename) — it is never an
objective and exposes no ``plan_*`` entry point. Each primitive matches the EXACT
semantics the transforms relied on, so the extraction is behaviour-preserving:

- :func:`is_fixture_path` — the example/test/fixture exclusion every transform
  copied verbatim.
- :func:`apply_column_rewrites` — the bottom-up, right-to-left single-line column
  splice used by the column-span transforms (merge-isinstance et al.).
- :func:`apply_line_rewrites` — the bottom-up inclusive line-span replacement
  used by the line-span transforms (bool-return, comprehension, dict).
- :func:`iter_statement_blocks` — the statement-list walker used by the
  block-scanning transforms (bool-return, comprehension, redundant-else).

Deterministic and stdlib-only — no time, no randomness.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = [
    "is_fixture_path",
    "apply_column_rewrites",
    "apply_line_rewrites",
    "iter_statement_blocks",
]


def is_fixture_path(path: str) -> bool:
    """True for example/test/fixture code, which the transforms exclude as a
    subject (its repetition is often deliberate boilerplate).

    A path is a fixture when, lower-cased with ``\\`` normalised to ``/``, it
    starts with an ``examples/`` / ``example/`` / ``tests/`` / ``test/`` /
    ``fixtures/`` segment, contains ``/examples/``, ``/tests/`` or ``/fixtures/``
    anywhere, or its basename starts with ``test_``. This is the identical helper
    that was copied across the transform modules — a local copy because importing
    it from health_score created a health_score <-> dedup import cycle."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def apply_column_rewrites(
    source: str,
    rewrites: Iterable[tuple[int, int, int, str]],
) -> str:
    """Splice single-line column-span rewrites into ``source``.

    Each rewrite is ``(lineno, col_offset, end_col_offset, new_text)`` with a
    1-based ``lineno`` and 0-based column offsets (AST conventions): on that line,
    ``[col_offset, end_col_offset)`` is replaced by ``new_text``. Rewrites are
    applied bottom-up and right-to-left — sorted by ``(lineno, col_offset)``
    descending — so earlier offsets stay valid when several share a line or one
    is nested in another. This is the loop the column-span transforms duplicated."""
    lines = source.splitlines(keepends=True)
    for lineno, col, end_col, text in sorted(
            rewrites, key=lambda r: (r[0], r[1]), reverse=True):
        line = lines[lineno - 1]
        lines[lineno - 1] = line[:col] + text + line[end_col:]
    return "".join(lines)


def apply_line_rewrites(
    source: str,
    rewrites: Iterable[tuple[int, int, list[str]]],
) -> str:
    """Replace inclusive 1-based line spans in ``source``.

    Each rewrite is ``(lo_lineno, hi_lineno, new_lines)``: lines ``[lo, hi]``
    (1-based, inclusive) are replaced by the ``new_lines`` list. Rewrites are
    applied bottom-up — sorted by ``lo_lineno`` descending — so earlier line
    numbers stay valid. ``new_lines`` carries its own trailing newlines (or not),
    so the caller preserves the original last line's trailing-newline behaviour by
    matching it; this helper splices verbatim. This is the loop the line-span
    transforms (bool-return, comprehension, dict-comprehension) duplicated."""
    lines = source.splitlines(keepends=True)
    for lo, hi, new_lines in sorted(rewrites, key=lambda r: r[0], reverse=True):
        lines[lo - 1:hi] = new_lines
    return "".join(lines)


def iter_statement_blocks(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    """Yield every list-of-statements in ``tree`` (module body, function/class
    bodies, if/for/while/with/try blocks, and except-handler bodies).

    Order doesn't matter — the transforms sort their rewrites before applying.
    This is the walker the block-scanning transforms (bool-return, comprehension,
    dict-comprehension, redundant-else) duplicated."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and all(
                    isinstance(s, ast.stmt) for s in block):
                yield block
        handlers = getattr(node, "handlers", None)
        if isinstance(handlers, list):
            for handler in handlers:
                if isinstance(handler, ast.ExceptHandler) and handler.body:
                    yield handler.body


# Operand node types that NEVER need wrapping parens when their source is spliced
# verbatim into a binding-operator context (``==`` ``!=`` ``in`` ``is`` ``<`` …):
# each is atomic or self-bracketing, so surrounding precedence can't re-associate
# it. Anything else — a ternary (``a if c else d``), ``or``/``and``, ``lambda``, a
# walrus, a nested comparison — binds looser than the operator it is spliced
# beside, so it MUST be parenthesised or the rewrite silently changes meaning
# (``not (a == (b if c else d))`` -> ``a != b if c else d`` == ``(a != b) if c
# else d``). ``ast.get_source_segment`` strips an operand's own wrapping parens,
# so the splice site can't rely on them surviving.
_ATOMIC_OPERANDS = (ast.Name, ast.Constant, ast.Attribute, ast.Subscript, ast.Call)


def operand_needs_parens(node: ast.expr) -> bool:
    """True if ``node`` must be wrapped in parens to keep its meaning when its
    source is spliced into a binding-operator expression."""
    return not isinstance(node, _ATOMIC_OPERANDS)


def splice_operand(source: str, node: ast.expr) -> str | None:
    """The source text of ``node``, parenthesised iff precedence could otherwise
    change its meaning when spliced beside a binding operator. ``None`` if the
    source can't be recovered (the caller skips the occurrence)."""
    src = ast.get_source_segment(source, node)
    if src is None:
        return None
    return f"({src})" if operand_needs_parens(node) else src
