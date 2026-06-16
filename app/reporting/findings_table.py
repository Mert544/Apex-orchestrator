"""Fixed-width ASCII table for findings — terminal output that survives a pipe.

`apex review` already exports findings as SARIF (for code-scanning dashboards)
and HTML; this renders the same findings as a plain-ASCII table for a terminal
or a CI log. No color codes, no Unicode box-drawing — just ``-``/``|``/``+`` so
the output is byte-stable through a pipe, a grep, or a file redirect.

Each finding is read structurally (a :class:`~app.engine.diff_review.ReviewFinding`
or any object/dict exposing ``file``, ``line``, ``severity``, ``category``,
``message``). Rows sort deterministically — severity high->low, then path, then
line — and the message column truncates with an ellipsis so the whole table fits
within ``max_width``. Pure function of the input: same findings in, same table
out, with no clock or randomness.
"""

from __future__ import annotations

from typing import Any

_HEADERS = ("Severity", "File:Line", "Category", "Message")

# Severity rank for the primary sort key (high findings first). An unknown
# severity sorts after the known tiers but before nothing — deterministic.
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Padding around each cell inside its column ("| <cell> |"): one space per side.
_CELL_PAD = 1
# Width charged per column separator ("|") plus its two surrounding pad spaces.
_SEP_WIDTH = 1 + 2 * _CELL_PAD


def _field(finding: Any, name: str, default: Any = "") -> Any:
    """Read ``name`` from a finding, whether it is an object or a dict."""
    if isinstance(finding, dict):
        return finding.get(name, default)
    return getattr(finding, name, default)


def _sort_key(finding: Any) -> tuple[int, str, int]:
    """Deterministic order: severity high->low, then file path, then line."""
    severity = str(_field(finding, "severity", "")).lower()
    file = str(_field(finding, "file", ""))
    try:
        line = int(_field(finding, "line", 0) or 0)
    except (TypeError, ValueError):
        line = 0
    return (_SEVERITY_RANK.get(severity, len(_SEVERITY_RANK)), file, line)


def _truncate(text: str, width: int) -> str:
    """Clamp ``text`` to ``width`` chars, marking a cut with a trailing ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return "." * width
    return text[: width - 3] + "..."


def _row(cells: tuple[str, ...], widths: tuple[int, ...]) -> str:
    """One pipe-delimited row, each cell left-padded to its column width."""
    pad = " " * _CELL_PAD
    body = "|".join(f"{pad}{c.ljust(w)}{pad}" for c, w in zip(cells, widths))
    return f"|{body}|"


def findings_to_table(findings: Any, *, max_width: int = 120) -> str:
    """Render ``findings`` as a fixed-width ASCII table for terminal output.

    Columns are Severity, File:Line, Category, Message. Findings sort
    deterministically (severity high->low, path, line). The Message column is
    truncated with an ellipsis so the total table width never exceeds
    ``max_width``. An empty input yields ``"No findings."``.
    """
    rows = list(findings or [])
    if not rows:
        return "No findings."

    rows.sort(key=_sort_key)

    # Build the first three columns verbatim; they are short and fixed by the
    # data. The Message column absorbs whatever width remains.
    cells: list[tuple[str, str, str, str]] = []
    for f in rows:
        severity = str(_field(f, "severity", ""))
        file = str(_field(f, "file", ""))
        line = _field(f, "line", "")
        loc = f"{file}:{line}" if file or str(line) else ""
        category = str(_field(f, "category", ""))
        message = str(_field(f, "message", "")).replace("\n", " ")
        cells.append((severity, loc, category, message))

    # Natural width each column wants (header included so the header never clips).
    natural = [len(_HEADERS[i]) for i in range(4)]
    for c in cells:
        for i in range(4):
            natural[i] = max(natural[i], len(c[i]))

    # Fixed-column overhead: outer borders ("|...|") + per-column padding/seps.
    # Total width = 1 (left border) + sum(width + _SEP_WIDTH for each column).
    fixed = natural[0] + natural[1] + natural[2]
    overhead = 1 + 4 * _SEP_WIDTH  # left "|" + 4 columns each contributing a "|"
    msg_budget = max_width - (fixed + overhead)
    # Never collapse the message column below room for a 1-char ellipsis-able
    # cell; clamp to its natural width (no point padding past the data).
    msg_width = max(1, min(natural[3], msg_budget))

    widths = (natural[0], natural[1], natural[2], msg_width)

    rule = "+" + "+".join("-" * (w + 2 * _CELL_PAD) for w in widths) + "+"

    lines = [rule, _row(_HEADERS, widths), rule]
    for severity, loc, category, message in cells:
        lines.append(_row((severity, loc, category, _truncate(message, msg_width)), widths))
    lines.append(rule)
    return "\n".join(lines)
