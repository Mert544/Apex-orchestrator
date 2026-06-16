"""Merge a nested ``if`` — collapse ``if A: if B:`` into ``if A and B:``.

A direct reduction of nesting depth, which is exactly what drives cyclomatic /
structural complexity: an ``if`` whose ENTIRE body is a single nested ``if`` (no
else on either) is the same control flow as one ``if`` with the conjoined
condition. Flattening it removes a level of indentation and a branch from the
shape the grade penalises::

    if A:                          if (A) and (B):
        if B:              ->          BODY
            BODY

Apex rewrites only this exact, unambiguous shape and nothing else:

  - the OUTER ``if`` body is EXACTLY one statement, and that statement is an
    ``ast.If`` (the INNER ``if``);
  - the OUTER has NO ``orelse`` (no ``else`` / ``elif``), AND the INNER has NO
    ``orelse`` — any branch on either side changes semantics, so it is skipped;
  - both ``test`` expressions are single-line (``lineno == end_lineno``) so the
    original source of each can be spliced verbatim; a multi-line test is
    skipped to keep the merge trivially correct;
  - the merged header is ``if (A) and (B):`` at the OUTER's indentation, where
    ``A`` / ``B`` are each ``test``'s ORIGINAL source (via
    ``ast.get_source_segment``) wrapped in parens and joined with `` and ``;
  - the inner body is dedented by exactly ONE level — the inner ``if``'s own
    indentation step, ``inner.body[0].col_offset - inner.col_offset`` spaces —
    so the body that sat under the (now-removed) inner ``if`` sits directly
    under the merged header instead; every non-blank inner-body line must
    already carry at least that indent, or the occurrence is skipped (never a
    partial or ambiguous dedent).

Edits are line-span replacements located by the AST: the span from the OUTER
``if`` header through the end of the inner block is swapped for the merged
header line plus the dedented inner body. Rewrites are collected across every
statement block and applied bottom-up (highest line first) so earlier line
numbers stay valid — a triple ``if A: if B: if C:`` thus collapses its OUTER
pair safely. Conservative by design — any ambiguity is a skipped occurrence,
and the rewritten module must re-parse or the whole plan blocks. Deterministic,
stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_line_rewrites,
    is_fixture_path,
    iter_statement_blocks,
)
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_merge_nested_if"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


class _Rewrite:
    """One located rewrite: replace lines [lo, hi] (1-based, inclusive) — the
    OUTER ``if`` header through the inner block — with the merged ``header``
    line followed by the inner-body lines dedented by ``unit`` spaces.

    ``body_lo`` / ``body_hi`` (1-based, inclusive) bound the inner-body lines to
    dedent; ``header`` already carries the OUTER indentation and trailing
    newline."""

    __slots__ = ("lo", "hi", "header", "body_lo", "body_hi", "unit")

    def __init__(self, lo: int, hi: int, header: str, body_lo: int,
                 body_hi: int, unit: int) -> None:
        self.lo = lo
        self.hi = hi
        self.header = header
        self.body_lo = body_lo
        self.body_hi = body_hi
        self.unit = unit


def _body_end(body: list[ast.stmt]) -> int:
    """The last source line (1-based) spanned by a statement body."""
    return max(s.end_lineno for s in body)


def _try_if(outer: ast.If, source: str, lines: list[str]) -> _Rewrite | None:
    """If ``outer`` is an ``if`` whose whole body is a single nested ``if`` with
    no else on either side and an unambiguous merge, return its rewrite, else
    None (the occurrence is skipped)."""
    if outer.orelse:
        return None  # else / elif on the outer — semantics differ, skip
    if len(outer.body) != 1:
        return None  # outer body is more than the single nested if — skip
    inner = outer.body[0]
    if not isinstance(inner, ast.If):
        return None
    if inner.orelse:
        return None  # else / elif on the inner — skip

    # Both tests must be single-line so their original source splices cleanly.
    if outer.test.lineno != outer.test.end_lineno:
        return None
    if inner.test.lineno != inner.test.end_lineno:
        return None

    a_src = ast.get_source_segment(source, outer.test)
    b_src = ast.get_source_segment(source, inner.test)
    if a_src is None or b_src is None:
        return None

    # Dedent the inner body by exactly the inner ``if``'s own indentation step,
    # so it lands one level under the merged header (where the outer body sat).
    unit = inner.body[0].col_offset - inner.col_offset
    if unit <= 0:
        return None

    body_lo = inner.body[0].lineno
    body_hi = _body_end(inner.body)
    # Every non-blank inner-body line must carry at least ``unit`` leading
    # spaces, or the dedent would be ambiguous (a continuation indented less
    # than the block). Skip to stay safe.
    pad = " " * unit
    for n in range(body_lo, body_hi + 1):
        line = lines[n - 1]
        if line.strip() and not line.startswith(pad):
            return None

    newline = "\n" if lines[outer.lineno - 1].endswith("\n") else ""
    header = " " * outer.col_offset + f"if ({a_src}) and ({b_src}):" + newline
    return _Rewrite(outer.lineno, body_hi, header, body_lo, body_hi, unit)


def _collect_rewrites(tree: ast.Module, source: str,
                      lines: list[str]) -> list[_Rewrite]:
    """Every NON-OVERLAPPING merge-nested-if rewrite in ``tree``.

    A triple ``if A: if B: if C:`` yields a match for both the A/B and the B/C
    pairs, but their line spans overlap (the A/B span contains the B/C one), so
    applying both would corrupt the source. We keep the OUTERMOST of any
    overlapping group — sort candidates by ``lo`` ascending and drop any whose
    span starts within an already-kept span. This collapses the outer pair and
    leaves the still-nested remainder for a later pass (the compiler re-scans),
    which keeps every applied rewrite independent and the result re-parsable."""
    candidates: list[_Rewrite] = []
    for block in iter_statement_blocks(tree):
        for stmt in block:
            if isinstance(stmt, ast.If):
                rw = _try_if(stmt, source, lines)
                if rw is not None:
                    candidates.append(rw)

    kept: list[_Rewrite] = []
    covered_through = 0  # highest ``hi`` of an accepted rewrite (1-based line)
    for rw in sorted(candidates, key=lambda r: r.lo):
        if rw.lo <= covered_through:
            continue  # nested inside an already-kept span — skip this pass
        kept.append(rw)
        covered_through = rw.hi
    return kept


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up (highest line first) so earlier line numbers
    stay valid. Each becomes the merged header line plus the dedented inner
    body, replacing the OUTER header through the inner block."""
    lines = source.splitlines(keepends=True)

    def _new_block(rw: _Rewrite) -> list[str]:
        body = [lines[n - 1][rw.unit:] for n in range(rw.body_lo, rw.body_hi + 1)]
        return [rw.header, *body]

    return apply_line_rewrites(
        source,
        [(rw.lo, rw.hi, _new_block(rw)) for rw in rewrites],
    )


def plan_merge_nested_if(project_root: str | Path,
                         module_rel: str) -> RenamePlan:
    """Build the single-module merge-nested-if plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan collapses every exact
    ``if A:\\n    if B:`` shape (no else on either, single-line tests, an
    unambiguous dedent) into ``if (A) and (B):`` with the inner body dedented
    one level. An empty plan means nothing matched — a no-op, not a failure."""
    plan = RenamePlan(old=module_rel, new="merge-nested-if")
    if _is_fixture_path(module_rel):
        return plan

    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, source, lines)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="merge")
