"""remove-pointless-pass — delete a ``pass`` that is dead weight because the
block it lives in ALREADY contains other real statements.

A ``pass`` statement is a true no-op: it exists only so a block that would
otherwise be empty is syntactically valid (an empty function body, ``except:
pass``, ``case _: pass``, an empty ``class``). The moment a block holds at least
one OTHER statement, the ``pass`` carries no meaning at all — it can be deleted
without changing behaviour for any input.

So, conservatively, for every statement block (a function body, an ``if``/
``else`` body, a loop body, an ``except`` body, a ``match`` ``case`` body, …)
Apex removes each child ``ast.Pass`` ONLY when the block contains at least one
other statement, so the deletion always leaves a non-empty block:

  - a block whose SOLE statement is ``pass`` is an intentional empty body and is
    LEFT UNTOUCHED (removing it would make the block syntactically invalid);
  - a block that is a docstring followed by ``pass`` HAS two statements, so the
    ``pass`` is removable — the docstring remains as the (now sole) body;
  - every other ``pass`` that shares its block with real code is removed.

All such pointless ``pass`` statements across the module are removed in one
plan. Removal is by line span (a ``pass`` is always a single line), located by
the AST and applied bottom-up so earlier line numbers stay valid; the rewritten
module must re-parse or the whole plan blocks. Fixtures/tests/examples are never
a subject. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_line_rewrites,
    is_fixture_path,
    iter_statement_blocks,
    plan_single_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_remove_pointless_pass"]

_is_fixture_path = is_fixture_path


def _collect_removals(tree: ast.Module) -> list[tuple[int, int]]:
    """Every ``(lo, hi)`` 1-based inclusive line span of a pointless ``pass``.

    A ``pass`` is pointless — and so removed — only when its block holds at least
    one OTHER statement, so the deletion leaves the block non-empty. A block whose
    only statement is ``pass`` is an intentional empty body and is skipped."""
    removals: list[tuple[int, int]] = []
    for block in iter_statement_blocks(tree):
        if len(block) < 2:
            continue  # a sole-statement block: if it's `pass`, it's intentional
        for stmt in block:
            if isinstance(stmt, ast.Pass):
                removals.append((stmt.lineno, stmt.end_lineno))
    return removals


def plan_remove_pointless_pass(project_root: str | Path,
                               module_rel: str) -> RenamePlan:
    """Build the single-module plan, or its blockers. An empty plan (no
    ``new_contents``, no blockers) means nothing matched — a no-op, not a
    failure."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="remove-pointless-pass",
        collect=lambda tree, source: _collect_removals(tree),
        apply=lambda source, removals: apply_line_rewrites(
            source, [(lo, hi, []) for lo, hi in removals]),
        reparse_phrase="removing pointless pass")
