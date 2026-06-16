"""Remove a redundant ``else`` after a terminal — flatten the else-body.

A small, surgical refactor: an ``if`` whose body ALREADY exits (its last
statement is a ``return``, ``raise``, ``break`` or ``continue``) makes its
``else:`` block redundant — control can never fall past the ``if`` into the
``else``. The else-body can drop one indent level and stand as plain siblings::

    if c:                          if c:
        return x                       return x
    else:              ->          BODY
        BODY

Apex rewrites only this exact, unambiguous shape and nothing else:

  - the ``if`` body's LAST statement is a terminal (``return``/``raise``/
    ``break``/``continue``);
  - the ``orelse`` is a real ``else:`` block, NOT an ``elif`` chain — an
    ``elif`` shares the ``if``'s column and has no literal ``else:`` header, so
    it is skipped (only a written-out ``else:`` block is flattened);
  - the ``else:`` header line is found by literal match (the line between the
    if-body end and the first orelse statement whose stripped text is exactly
    ``else:``); if it can't be located, that occurrence is skipped;
  - the dedent unit is ``orelse[0].col_offset - if.col_offset``; every line the
    else-body spans must start with at least that many spaces, or the occurrence
    is skipped to stay safe (never a partial or ambiguous dedent).

Edits are line-span rewrites located by the AST. Conservative by design — any
ambiguity is skipped, and the rewritten module must re-parse or the whole plan
blocks. Rewrites are applied bottom-up (highest lineno first) so earlier line
numbers stay valid; nested ``if``s are collected across every statement block
then applied in reverse line order. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import iter_statement_blocks
from app.execution._transform_base import plan_single_module_rewrite
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_remove_redundant_else"]

_TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


class _Rewrite:
    """One located rewrite: drop the ``else:`` header at line ``else_line``
    (1-based) and dedent the else-body lines [body_lo, body_hi] (1-based,
    inclusive) by ``unit`` leading spaces."""

    __slots__ = ("else_line", "body_lo", "body_hi", "unit")

    def __init__(self, else_line: int, body_lo: int, body_hi: int,
                 unit: int) -> None:
        self.else_line = else_line
        self.body_lo = body_lo
        self.body_hi = body_hi
        self.unit = unit


def _body_end(body: list[ast.stmt]) -> int:
    """The last source line (1-based) spanned by a statement body."""
    return max(s.end_lineno for s in body)


def _find_else_line(lines: list[str], lo: int, hi: int) -> int | None:
    """The 1-based line in the open span (lo, hi) whose stripped text is exactly
    ``else:`` — the real ``else:`` header. None if not found, which means the
    ``orelse`` is an ``elif`` (or otherwise unlocatable) and is skipped.
    ``lo``/``hi`` are 1-based; the header lies strictly between the if-body's
    last line and the first orelse statement's line. Two candidate headers is
    ambiguous — skip."""
    found: int | None = None
    for n in range(lo + 1, hi):
        if lines[n - 1].strip() == "else:":
            if found is not None:
                return None
            found = n
    return found


def _try_if(stmt: ast.If, lines: list[str]) -> _Rewrite | None:
    """If ``stmt`` is an ``if`` with a terminal-ending body and a real ``else:``
    block whose dedent is unambiguous, return its rewrite, else None."""
    if not stmt.orelse:
        return None
    if not isinstance(stmt.body[-1], _TERMINALS):
        return None

    if_body_end = _body_end(stmt.body)
    first_else = stmt.orelse[0]
    else_line = _find_else_line(lines, if_body_end, first_else.lineno)
    if else_line is None:
        return None  # elif chain or unlocatable header — skip

    unit = first_else.col_offset - stmt.col_offset
    if unit <= 0:
        return None

    body_lo = first_else.lineno
    body_hi = _body_end(stmt.orelse)
    # Every else-body line must carry at least ``unit`` leading spaces, or the
    # dedent would be ambiguous (e.g. a continuation indented less than the
    # block). Skip to stay safe.
    pad = " " * unit
    for n in range(body_lo, body_hi + 1):
        if not lines[n - 1].startswith(pad):
            return None
    return _Rewrite(else_line, body_lo, body_hi, unit)


def _elif_nodes(tree: ast.Module) -> set[int]:
    """The ``id()`` of every ``ast.If`` that is an ``elif`` — the sole,
    same-column ``orelse`` of a parent ``if``.

    Removing an elif's ``else`` is unsafe: an EARLIER branch of the chain may
    NOT exit, so dedenting the else-body would make it run on that branch's path
    too. (`if A: <no exit>` / `elif B: raise` / `else: Y` — dropping the else
    runs ``Y`` after ``A`` as well.) The if-body-terminal check only inspects the
    elif's OWN body, so it can't see the earlier branch — we skip elifs entirely.
    A nested ``if`` inside a real ``else:`` block is indented deeper, so the
    same-column test distinguishes it from a true elif."""
    elifs: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and len(node.orelse) == 1
                and isinstance(node.orelse[0], ast.If)
                and node.orelse[0].col_offset == node.col_offset):
            elifs.add(id(node.orelse[0]))
    return elifs


def _collect_rewrites(tree: ast.Module, lines: list[str]) -> list[_Rewrite]:
    """Every redundant-else rewrite in ``tree``, across all statement blocks."""
    elifs = _elif_nodes(tree)
    rewrites: list[_Rewrite] = []
    for block in iter_statement_blocks(tree):
        for stmt in block:
            if isinstance(stmt, ast.If) and id(stmt) not in elifs:
                rw = _try_if(stmt, lines)
                if rw is not None:
                    rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up (highest line first) so earlier line numbers
    stay valid. For each: dedent the body lines, then drop the ``else:`` line."""
    lines = source.splitlines(keepends=True)
    for rw in sorted(rewrites, key=lambda r: r.else_line, reverse=True):
        for n in range(rw.body_lo, rw.body_hi + 1):
            lines[n - 1] = lines[n - 1][rw.unit:]
        del lines[rw.else_line - 1]
    return "".join(lines)


def plan_remove_redundant_else(project_root: str | Path,
                               module_rel: str) -> RenamePlan:
    """Build the single-module remove-redundant-else plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan drops every redundant
    ``else:`` (one whose ``if`` body ends in a terminal) and dedents the
    else-body so it stands as siblings after the ``if``. An empty plan means
    nothing matched (a no-op, not a failure)."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="remove-redundant-else",
        collect=lambda tree, source: _collect_rewrites(
            tree, source.splitlines(keepends=True)),
        apply=_apply,
        reparse_phrase="removal")
