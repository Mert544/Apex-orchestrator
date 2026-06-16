"""Combine nested ``with`` statements — collapse ``with A:\\n with B:``.

A small, surgical refactor: a ``with`` whose body is EXACTLY one nested ``with``
is just a single comma-form ``with``. Apex rewrites the EXACT shape below and
nothing else::

    with A:
        with B:
            BODY            ->   with A, B:
                                     BODY

    with open(a) as f:
        with open(b) as g:           with open(a) as f, open(b) as g:
            BODY            ->            BODY

A maximal chain of singly-nested ``with`` headers is merged in one pass: three
deep collapses fully to ``with A, B, C:``.

Conservative by design — any ambiguity is left untouched, never guessed:

  - only a ``with`` whose body is length 1 and whose single statement is itself
    a plain ``with`` matches; an outer body with anything else beside the inner
    ``with`` is left alone;
  - ``async with`` (``ast.AsyncWith``) is never touched, at either level;
  - each ``with`` header must be SINGLE-LINE (the ``with`` line is the line right
    before its body) so the header rewrite is trivial; a header spanning multiple
    lines, or one carrying a trailing comment on its ``with`` line, is skipped;
  - each ``withitem``'s source text (context expression plus an optional ``as``
    target) is recovered via ``ast.get_source_segment``; if any can't be
    recovered the chain is skipped;
  - the inner body is dedented by one indent level only when every body line
    carries the expected leading spaces; otherwise the chain is skipped.

Edits are line-span replacements located by the AST: the stacked ``with`` header
lines are swapped for one ``with A, B:`` line at the OUTERMOST ``with``'s own
indentation, and the innermost body is dedented to sit one level under it.
Processed bottom-up so earlier line numbers stay valid. The rewritten module
must re-parse, or the whole plan blocks. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)

__all__ = ["plan_combine_nested_with"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its repetition is often deliberate
    boilerplate). A local copy — importing this from health_score created a
    health_score <-> dedup import cycle, and the grade now reads dedup."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


class _Rewrite:
    """One located rewrite: replace header lines [hdr_lo, hdr_hi] (1-based,
    inclusive) with a single merged ``with`` line, then dedent body lines
    [body_lo, body_hi] by ``dedent`` spaces each."""

    __slots__ = ("hdr_lo", "hdr_hi", "header", "body_lo", "body_hi", "dedent")

    def __init__(self, hdr_lo: int, hdr_hi: int, header: str,
                 body_lo: int, body_hi: int, dedent: int) -> None:
        self.hdr_lo = hdr_lo
        self.hdr_hi = hdr_hi
        self.header = header
        self.body_lo = body_lo
        self.body_hi = body_hi
        self.dedent = dedent


def _single_line_header(node: ast.With, source_lines: list[str]) -> bool:
    """The ``with`` header sits on a single line right before its body, and that
    line carries no trailing comment that the rewrite would drop."""
    if not node.body:
        return False
    first = node.body[0]
    # The header occupies exactly the line before the body's first statement.
    if node.lineno != first.lineno - 1:
        return False
    line = source_lines[node.lineno - 1]
    return "#" not in line


def _item_text(item: ast.withitem, source: str) -> str | None:
    """Source text of one ``withitem``: ``ctx`` or ``ctx as name``."""
    ctx = ast.get_source_segment(source, item.context_expr)
    if ctx is None:
        return None
    if item.optional_vars is None:
        return ctx
    name = ast.get_source_segment(source, item.optional_vars)
    if name is None:
        return None
    return f"{ctx} as {name}"


def _items_text(items: list[ast.withitem], source: str) -> str | None:
    """Comma-joined source text of a ``with``'s items, or None if any segment
    can't be recovered."""
    parts: list[str] = []
    for item in items:
        text = _item_text(item, source)
        if text is None:
            return None
        parts.append(text)
    return ", ".join(parts)


def _try_with(node: ast.With, source: str,
              source_lines: list[str]) -> _Rewrite | None:
    """If ``node`` is the OUTER of a singly-nested plain-``with`` chain, return
    its rewrite, else None.

    A maximal chain is collected: ``node`` and each successively nested ``with``
    whose body is exactly one plain ``with`` are merged into one header, and the
    innermost body is dedented to one level under ``node``."""
    if isinstance(node, ast.AsyncWith):
        return None
    if len(node.body) != 1 or not isinstance(node.body[0], ast.With):
        return None
    if isinstance(node.body[0], ast.AsyncWith):
        return None

    # Walk the chain of singly-nested plain withs from the outer node down.
    chain: list[ast.With] = [node]
    current = node
    while (len(current.body) == 1 and isinstance(current.body[0], ast.With)
           and not isinstance(current.body[0], ast.AsyncWith)):
        current = current.body[0]
        chain.append(current)

    # Every header on the chain must be single-line and comment-free.
    for w in chain:
        if not _single_line_header(w, source_lines):
            return None

    # Recover and join every item across the chain, outer-to-inner.
    item_texts: list[str] = []
    for w in chain:
        text = _items_text(w.items, source)
        if text is None:
            return None
        item_texts.append(text)

    outer_indent = node.col_offset
    inner = chain[-1]
    inner_body = inner.body
    if not inner_body:
        return None

    # The innermost body dedents from its own column to one level under the
    # outer with — i.e. to the outer with's OWN body indentation (chain[1]).
    body_col = inner_body[0].col_offset
    target_col = node.body[0].col_offset  # one level under the outer with
    dedent = body_col - target_col
    if dedent < 0:
        return None

    body_lo = inner_body[0].lineno
    body_hi = inner_body[-1].end_lineno
    if body_hi is None:
        return None

    # Only dedent when every body line carries the expected leading spaces.
    if dedent:
        for ln in range(body_lo, body_hi + 1):
            line = source_lines[ln - 1]
            if line.strip() == "":
                continue  # blank lines are left as-is
            if not line.startswith(" " * body_col):
                return None

    header = " " * outer_indent + "with " + ", ".join(item_texts) + ":"
    return _Rewrite(node.lineno, inner.lineno, header,
                    body_lo, body_hi, dedent)


def _outer_withs(tree: ast.Module) -> list[ast.With]:
    """Every plain ``with`` that is NOT itself the single nested body of another
    matchable ``with`` — only the outermost of each chain is a rewrite anchor,
    so chains never double-collect."""
    nested: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.With) and not isinstance(node, ast.AsyncWith)
                and len(node.body) == 1
                and isinstance(node.body[0], ast.With)
                and not isinstance(node.body[0], ast.AsyncWith)):
            nested.add(id(node.body[0]))
    out: list[ast.With] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.With) and not isinstance(node, ast.AsyncWith)
                and id(node) not in nested):
            out.append(node)
    return out


def _collect_rewrites(tree: ast.Module, source: str,
                      source_lines: list[str]) -> list[_Rewrite]:
    """Every nested-with merge in ``tree``, anchored at chain outers only."""
    rewrites: list[_Rewrite] = []
    for node in _outer_withs(tree):
        rw = _try_with(node, source, source_lines)
        if rw is not None:
            rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up so earlier line numbers stay valid."""
    lines = source.splitlines(keepends=True)
    for rw in sorted(rewrites, key=lambda r: r.hdr_lo, reverse=True):
        # Dedent the body lines first (their indices are below the header span).
        if rw.dedent:
            for ln in range(rw.body_lo, rw.body_hi + 1):
                line = lines[ln - 1]
                if line.strip() == "":
                    continue
                lines[ln - 1] = line[rw.dedent:]
        # Replace the stacked header lines with the single merged header.
        last_hdr = lines[rw.hdr_hi - 1]
        newline = "\n" if last_hdr.endswith("\n") else ""
        lines[rw.hdr_lo - 1:rw.hdr_hi] = [rw.header + newline]
    return "".join(lines)


def plan_combine_nested_with(project_root: str | Path,
                             module_rel: str) -> RenamePlan:
    """Build the single-module combine-nested-with plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan collapses every
    ``with A:\\n    with B:`` (singly-nested plain ``with``) into one
    ``with A, B:`` header, merging a maximal chain in a single pass. An empty
    plan means nothing matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="combine-nested-with")
    if _is_fixture_path(module_rel):
        return plan

    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    source_lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, source, source_lines)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="merge")
