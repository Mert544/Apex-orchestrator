"""Render what Apex has LEARNED about fixing this project as a Markdown section.

``proof_history.py`` distils Apex's proof-of-fix artifacts into a track record —
per action type, how often a fix *landed* (``applied``) versus *rolled_back* or
got *blocked*, plus a bounded reliability ratio. That signal lives in JSON; a
reviewer reading a report can't see it. This module surfaces it: a single pure
function turns the durable proof history into a clean Markdown section so the
learned reliability is visible alongside the rest of an Apex report.

The section is a ``## heading``, a one-line headline ("Apex has learned X about
fixing this project"), then a per-action-type table (Action | Reliability |
Applied | Rolled back | Blocked | Total) sorted by reliability high→low, then by
action name, so the ordering is fully deterministic. An empty or absent history
renders a short "no fix history yet" section instead of an empty table.

Pure, deterministic, stdlib-only beyond the proof-history reader: same proof
files in → byte-identical Markdown out, no clock, no randomness. Reading a
missing/unreadable history is tolerated by ``load_proof_history`` itself, so this
function never raises. The ``|`` and newline characters in an action name are
escaped so a hostile name can never break the table's columns.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.proof_history import (
    load_proof_history,
    summarise_fix_track_record,
)

# Section heading and the empty-state line, kept as constants so the rendered
# shape is one obvious place to read.
_HEADING = "## What Apex Has Learned About Fixing This Project"
_EMPTY_LINE = "_No fix history yet — Apex has no proof-of-fix record for this project._"

# Table header + alignment separator. Columns mirror the per-action stats the
# track record exposes (applied / rolled_back / blocked / total / reliability).
_TABLE_HEADER = (
    "| Action | Reliability | Applied | Rolled back | Blocked | Total |"
)
_TABLE_SEP = "| --- | ---: | ---: | ---: | ---: | ---: |"


def _escape_cell(text: str) -> str:
    """Make ``text`` safe to drop into a single Markdown table cell.

    A literal ``|`` would start a new column and a newline would end the row, so
    both are neutralized: any CR/LF run collapses to ``<br>`` and ``|`` becomes
    the HTML entity ``&#124;``. The result is always one cell on one row.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "<br>".join(text.split("\n"))
    return text.replace("|", "&#124;")


def _action_sort_key(item: tuple[str, dict]) -> tuple[float, str]:
    """Order actions by reliability high→low, then action name ascending.

    Negating the reliability gives the descending primary sort while the name
    keeps ties (and equal-reliability rows) deterministic.
    """
    action, stats = item
    return (-float(stats.get("reliability", 0.0)), action)


def _percent(reliability: float) -> str:
    """Render a [0, 1] reliability as a whole-number percent, e.g. ``75%``."""
    return f"{round(reliability * 100):d}%"


def _action_row(action: str, stats: dict) -> str:
    """One table row for an action type's landed/rolled-back/blocked tally."""
    return (
        f"| {_escape_cell(action)} "
        f"| {_percent(float(stats.get('reliability', 0.0)))} "
        f"| {int(stats.get('applied', 0))} "
        f"| {int(stats.get('rolled_back', 0))} "
        f"| {int(stats.get('blocked', 0))} "
        f"| {int(stats.get('total', 0))} |"
    )


def _headline(summary: dict) -> str:
    """The one-line "Apex has learned X about fixing this project" headline.

    ``X`` quantifies the evidence: the share of all recorded fixes that landed
    across this project, over how many fixes and proofs that draws on.
    """
    totals = summary.get("totals") or {}
    fixes = int(summary.get("fixes", 0))
    proofs = int(summary.get("proofs", 0))
    landed = _percent(float(totals.get("reliability", 0.0)))
    fix_noun = "fix" if fixes == 1 else "fixes"
    proof_noun = "proof" if proofs == 1 else "proofs"
    return (
        f"**Apex has learned that {landed} of its fixes land cleanly on this "
        f"project** — from {fixes} {fix_noun} across {proof_noun} ({proofs})."
    )


def render_learning_markdown(root: str | Path) -> str:
    """Render Apex's learned fix-reliability for ``root`` as a Markdown section.

    Loads the proof-of-fix history under ``<root>/.apex/`` and renders a
    ``## heading``, a headline summarising overall fix reliability, then a
    per-action-type table (Action | Reliability | Applied | Rolled back |
    Blocked | Total) sorted by reliability high→low then action name. When the
    history is empty or absent, a short "no fix history yet" section is rendered
    in place of the table.

    Pure and deterministic: same proof files → byte-identical Markdown. Never
    raises — a missing or unreadable history yields the empty-state section.
    """
    history = load_proof_history(root)
    summary = summarise_fix_track_record(history)
    by_action = summary.get("by_action") or {}
    lines = [_HEADING, ""]
    if not by_action:
        lines.append(_EMPTY_LINE)
        return "\n".join(lines) + "\n"

    lines.append(_headline(summary))
    lines.append("")
    lines.append(_TABLE_HEADER)
    lines.append(_TABLE_SEP)
    for action, stats in sorted(by_action.items(), key=_action_sort_key):
        lines.append(_action_row(action, stats))
    return "\n".join(lines) + "\n"
