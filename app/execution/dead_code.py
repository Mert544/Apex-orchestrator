"""Dead-code removal — Apex's first deleting transform.

Turns the unreachable-code DETECTOR into an ACTION: code that provably never
runs is removed. The notion of "unreachable" matches the detector exactly
(``app/engine/detectors._unreachable_code_lines``):

  For every executable statement list — a function body, both branches of an
  ``if``, loop bodies/else, ``with`` bodies, the ``try``/``except``/``else``/
  ``finally`` bodies, and the module body — an unconditional terminal
  (``return``/``raise``/``break``/``continue``) that is a *direct* child and not
  the last statement makes every statement AFTER it in that block unreachable.

Conservative by design: only a direct-child terminal that isn't last triggers a
removal. A ``return`` nested inside a child block (e.g. guarded by an ``if``)
does not make following siblings dead, so only direct children are inspected.

Edits are precise text spans located by the AST — the source is rebuilt by
slicing dead line-spans out of the original lines (no ``ast.unparse`` round-trip),
so comments and formatting on live code survive untouched. Comments living on the
dead lines go with them; they're dead too.

The plan is consumed by the same test-verified / rollback machinery as a rename
(``RenamePlan``): this module builds the plan, the caller verifies it against the
suite and rolls back on failure, so removal can't change behaviour.

Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _py_files

# The detector's exact rule set — kept in lockstep so "dead" means the same here.
_BLOCK_FIELDS = ("body", "orelse", "finalbody")
_TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)

# A dead span: (lineno, end_lineno) — 1-based, inclusive of both endpoints.
_Span = tuple[int, int]


def _dead_spans(tree: ast.AST) -> list[_Span]:
    """Line spans of trailing unreachable statements, one entry per dead block.

    For each block (the same ``_BLOCK_FIELDS`` the detector walks), if a
    direct-child terminal is not the last statement, the span runs from the first
    statement after it through the block's last statement's ``end_lineno``.
    """
    spans: list[_Span] = []

    def scan(block: list) -> None:
        for i, stmt in enumerate(block[:-1]):
            if isinstance(stmt, _TERMINALS):
                first_dead = block[i + 1]
                last = block[-1]
                lo = first_dead.lineno
                hi = getattr(last, "end_lineno", last.lineno) or last.lineno
                spans.append((lo, hi))
                break  # one finding per block — the rest is already covered

    for node in ast.walk(tree):
        # ExceptHandler owns a ``body`` but isn't a node type _BLOCK_FIELDS names
        # directly; the generic getattr below picks up every block-bearing node.
        for field in _BLOCK_FIELDS:
            block = getattr(node, field, None)
            if isinstance(block, list) and block and all(
                isinstance(s, ast.stmt) for s in block
            ):
                scan(block)
    return spans


def _delete_spans(source: str, spans: list[_Span]) -> str:
    """Rebuild ``source`` with each inclusive line span removed.

    Spans are deleted bottom-up so earlier line numbers stay valid as we go.
    """
    lines = source.splitlines(keepends=True)
    # Dedupe and process from the largest starting line first.
    for lo, hi in sorted(set(spans), reverse=True):
        del lines[lo - 1:hi]
    return "".join(lines)


def plan_remove_dead_code(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build a plan that deletes provably unreachable code from ``module_rel``.

    The plan re-uses ``RenamePlan`` as the transport the verify/rollback caller
    expects: ``old`` names the module, ``new`` is the literal
    ``"remove-dead-code"`` tag, ``edits_by_file`` counts the dead blocks removed.
    """
    plan = RenamePlan(old=module_rel, new="remove-dead-code")
    root = Path(project_root)
    path = root / module_rel

    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        plan.blockers.append(f"{module_rel}: cannot read module ({exc})")
        return plan

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        plan.blockers.append(f"{module_rel}: cannot parse module ({exc})")
        return plan

    spans = _dead_spans(tree)
    if not spans:
        return plan  # nothing dead — empty (no-op) plan

    new = _delete_spans(source, spans)
    if new == source:
        return plan

    # Never emit code that won't re-parse — a broken slice is a blocker, not output.
    try:
        ast.parse(new)
    except SyntaxError as exc:
        plan.blockers.append(
            f"{module_rel}: removal produced unparseable source ({exc})")
        plan.new_contents.clear()
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new
    plan.edits_by_file[module_rel] = len(spans)
    return plan


__all__ = ["plan_remove_dead_code", "RenamePlan", "_py_files"]
