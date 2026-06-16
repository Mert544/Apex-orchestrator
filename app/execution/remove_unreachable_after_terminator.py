"""remove-unreachable-after-terminator — delete statements that can never run
because they follow an UNCONDITIONAL terminator at the same block level.

In any statement block (a function body, an ``if``/``else`` body, a loop body,
an ``except`` body, …) once a statement is an unconditional ``return``,
``raise``, ``break`` or ``continue``, every statement AFTER it in the SAME block
is unreachable — control has already left the block — so it is removed. The
terminator and everything before it are left exactly as they were.

Behaviour-preserving by construction: the deleted statements never execute, for
any input. The pass is deliberately conservative — an occurrence is SKIPPED whole
(nothing removed in that block) when any of the trailing, to-be-removed
statements is:

  - a ``def`` / ``async def`` / ``class`` — even if dead it may be referenced by
    name elsewhere via the module namespace, so leave it;
  - an ``import`` / ``import from`` — same name-binding caution;
  - a ``global`` / ``nonlocal`` declaration — scope semantics;
  - anything containing a ``yield`` / ``yield from`` — generator semantics.

Only the FIRST terminator in each block matters (everything after it is
unreachable, including any nested terminators). Removal is by line span, located
by the AST and applied bottom-up so earlier line numbers stay valid; the
rewritten module must re-parse or the whole plan blocks. Fixtures/tests/examples
are never a subject. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
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

__all__ = ["plan_remove_unreachable_after_terminator"]

_is_fixture_path = is_fixture_path

# Statements that, on their own, unconditionally divert control out of the block.
_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)

# Trailing statements we will NOT delete — name-binding / scope / generator
# hazards make removal unsafe-or-ambiguous, so the whole occurrence is skipped.
_HAZARD_STMT = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
    ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
)


def _has_yield(stmt: ast.stmt) -> bool:
    """True if ``stmt`` contains a ``yield`` / ``yield from`` anywhere."""
    return any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(stmt))


def _collect_removals(tree: ast.Module) -> list[tuple[int, int]]:
    """Every ``(lo, hi)`` 1-based inclusive line span of unreachable trailing
    statements — one per block that has code after its first terminator."""
    removals: list[tuple[int, int]] = []
    for block in iter_statement_blocks(tree):
        for i, stmt in enumerate(block):
            if isinstance(stmt, _TERMINATORS):
                tail = block[i + 1:]
                if not tail:
                    break  # terminator is last — nothing unreachable
                if any(isinstance(s, _HAZARD_STMT) or _has_yield(s) for s in tail):
                    break  # conservative: a hazard in the tail blocks the block
                lo = tail[0].lineno
                hi = max(s.end_lineno for s in tail)
                removals.append((lo, hi))
                break  # only the first terminator in the block matters
    return removals


def plan_remove_unreachable_after_terminator(project_root: str | Path,
                                             module_rel: str) -> RenamePlan:
    """Build the single-module plan, or its blockers. An empty plan (no
    ``new_contents``, no blockers) means nothing matched — a no-op, not a
    failure."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="remove-unreachable-after-terminator",
        collect=lambda tree, source: _collect_removals(tree),
        apply=lambda source, removals: apply_line_rewrites(
            source, [(lo, hi, []) for lo, hi in removals]),
        reparse_phrase="removing unreachable code")
