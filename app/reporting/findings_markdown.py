"""Markdown rendering for Apex findings — a PR comment / Step Summary report.

A reviewer's two homes are the pull-request conversation and the GitHub Actions
run summary (``$GITHUB_STEP_SUMMARY``). Both render GitHub-Flavored Markdown.
This module turns Apex's deterministic findings into a clean Markdown report you
can drop into either: a header with a counts-by-severity line, then a table
(Severity | File:Line | Category | Message) sorted high→low severity, then path,
then line. An empty finding list renders a single "no findings" line instead of
an empty table.

Pure, deterministic, stdlib-only. Same findings in → byte-identical Markdown
out: no clock, no randomness, no network. The ``|`` and newline characters in a
message are escaped so a hostile message can never break the table's columns.

A "finding" is duck-typed: any object exposing ``file`` / ``line`` /
``category`` / ``severity`` / ``message`` attributes (e.g.
:class:`app.engine.diff_review.ReviewFinding`) works, as does a plain ``dict``
with those keys. Missing fields fall back to safe defaults, so a line-level
:class:`app.engine.detectors.Issue` (no ``file``) renders fine too.
"""

from __future__ import annotations

from typing import Any, Iterable

# Severities in descending order — drives both the counts line and the row sort.
_SEVERITY_ORDER = ("high", "medium", "low")
# Sort rank; anything unexpected sorts after the known tiers (stable, last).
_SEVERITY_RANK = {sev: i for i, sev in enumerate(_SEVERITY_ORDER)}
_UNKNOWN_RANK = len(_SEVERITY_ORDER)

# An emoji per tier keeps the counts line scannable; falls back to a neutral dot.
_SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
_UNKNOWN_ICON = "⚪"

# Where a finding has no file of its own (e.g. a line-level Issue).
_NO_FILE = "<unknown>"

# A Step Summary collapses behind <details> once the table grows past this many
# rows, so a noisy run doesn't bury the rest of the summary.
_DETAILS_THRESHOLD = 10


def _field(finding: Any, name: str, default: str = "") -> str:
    """Read ``name`` off a finding (attribute or dict key) as a string.

    Duck-typed so a :class:`ReviewFinding`, a detector :class:`Issue`, or a plain
    ``dict`` all work. A missing/``None`` value yields ``default``.
    """
    if isinstance(finding, dict):
        value = finding.get(name, default)
    else:
        value = getattr(finding, name, default)
    if value is None:
        return default
    return str(value)


def _line_of(finding: Any) -> int:
    """The finding's line number as an int (0 when absent/unreadable)."""
    raw = _field(finding, "line")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _location(finding: Any) -> str:
    """``file:line`` for a finding, falling back to the file (or a placeholder)."""
    path = _field(finding, "file", _NO_FILE) or _NO_FILE
    line = _line_of(finding)
    return f"{path}:{line}" if line else path


def _escape_cell(text: str) -> str:
    """Make ``text`` safe to drop into a single Markdown table cell.

    A literal ``|`` would start a new column and a newline would end the row, so
    both are neutralized: ``|`` becomes the HTML entity ``&#124;`` and any
    CR/LF run collapses to a single ``<br>``. The result renders as one cell on
    one logical row no matter what the message contains.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Newlines become <br> so the message stays on one logical table row.
    text = "<br>".join(text.split("\n"))
    return text.replace("|", "&#124;")


def _sort_key(finding: Any) -> tuple[int, str, int]:
    """Deterministic ordering: severity high→low, then path, then line."""
    severity = _field(finding, "severity").lower()
    rank = _SEVERITY_RANK.get(severity, _UNKNOWN_RANK)
    path = _field(finding, "file", _NO_FILE) or _NO_FILE
    return (rank, path, _line_of(finding))


def _counts_by_severity(findings: list[Any]) -> dict[str, int]:
    """Count findings per known severity tier (zeros included, deterministic)."""
    counts = {sev: 0 for sev in _SEVERITY_ORDER}
    for f in findings:
        severity = _field(f, "severity").lower()
        if severity in counts:
            counts[severity] += 1
    return counts


def _counts_line(findings: list[Any]) -> str:
    """A one-line severity tally, e.g. ``🔴 2 high · 🟠 1 medium · 🟡 0 low``."""
    counts = _counts_by_severity(findings)
    return " · ".join(
        f"{_SEVERITY_ICON.get(sev, _UNKNOWN_ICON)} {counts[sev]} {sev}"
        for sev in _SEVERITY_ORDER
    )


def _table(findings: list[Any]) -> list[str]:
    """The Markdown table rows (header + separator + one row per finding).

    ``findings`` is assumed already sorted by :func:`_sort_key`.
    """
    rows = [
        "| Severity | File:Line | Category | Message |",
        "| --- | --- | --- | --- |",
    ]
    for f in findings:
        severity = _field(f, "severity") or "unknown"
        icon = _SEVERITY_ICON.get(severity.lower(), _UNKNOWN_ICON)
        category = _field(f, "category") or "finding"
        message = _field(f, "message") or "(no message)"
        rows.append(
            f"| {icon} {_escape_cell(severity)} "
            f"| {_escape_cell(_location(f))} "
            f"| {_escape_cell(category)} "
            f"| {_escape_cell(message)} |"
        )
    return rows


def findings_to_markdown(findings: Iterable[Any], *, title: str = "Apex Findings") -> str:
    """Render findings as a Markdown report for a PR comment / Step Summary.

    The report is a ``## title`` header, a counts-by-severity line, then a table
    (Severity | File:Line | Category | Message) sorted high→low severity, then
    path, then line. An empty ``findings`` renders a single "✅ No findings" line
    in place of the table.

    Deterministic and self-contained: ``|`` and newlines in a message are escaped
    so the table stays well-formed for any input.
    """
    items = list(findings)
    lines = [f"## {title}", ""]
    if not items:
        lines.append("✅ No findings")
        return "\n".join(lines) + "\n"

    items.sort(key=_sort_key)
    total = len(items)
    noun = "finding" if total == 1 else "findings"
    lines.append(f"**{total} {noun}** — {_counts_line(items)}")
    lines.append("")
    lines.extend(_table(items))
    return "\n".join(lines) + "\n"


def findings_to_step_summary(findings: Iterable[Any], *, title: str = "Apex Findings") -> str:
    """Render findings for ``$GITHUB_STEP_SUMMARY``.

    Identical to :func:`findings_to_markdown` for small result sets. Once the
    table would exceed :data:`_DETAILS_THRESHOLD` rows, the table is wrapped in a
    collapsible ``<details>`` block (the header and counts line stay visible) so
    a noisy run doesn't bury the rest of the job summary. Empty findings render
    the same "✅ No findings" line.
    """
    items = list(findings)
    if not items:
        return findings_to_markdown(items, title=title)

    items.sort(key=_sort_key)
    total = len(items)
    noun = "finding" if total == 1 else "findings"
    lines = [
        f"## {title}",
        "",
        f"**{total} {noun}** — {_counts_line(items)}",
        "",
    ]
    table = _table(items)
    if total > _DETAILS_THRESHOLD:
        lines.append(f"<details><summary>Show {total} findings</summary>")
        lines.append("")
        lines.extend(table)
        lines.append("")
        lines.append("</details>")
    else:
        lines.extend(table)
    return "\n".join(lines) + "\n"
