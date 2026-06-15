"""CSV export for Apex findings — the format spreadsheets, BI tools, and audit
trails ingest natively.

Where :mod:`app.engine.sarif_export` targets code-scanning dashboards, this
targets the enterprise buyer who wants the findings in Excel/Sheets, a data
warehouse, or an immutable audit log. One row per finding, a stable header, and
``csv``-module quoting so a message containing a comma, a quote, or a newline
survives a round-trip through any spreadsheet importer.

Pure function of the findings (a duck-typed :class:`ReviewFinding`/``Issue``):
same findings in, byte-identical CSV out. No clock, no random, no network — it
reads only the attributes already on each finding.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable

# Column order is the contract: consumers (a saved spreadsheet template, an audit
# pipeline's schema) depend on it, so it never reorders. ``column`` is always
# emitted even though Apex findings are line-level (no column yet) — keeping the
# slot stable means a future column-precise finding doesn't shift the schema.
HEADER = (
    "path",
    "line",
    "column",
    "severity",
    "category",
    "check",
    "message",
    "rule_id",
)


def _rule_id(check: str, category: str) -> str:
    """Stable rule id, mirroring the SARIF exporter: ``apex/<check-or-category>``.

    Uses the detector routing key (``fix_kind``) when present, else the category,
    so the same finding gets the same id in CSV and SARIF. Empty only when a
    finding exposes neither — then the slot is left blank rather than guessed.
    """
    key = (check or category or "").strip().replace(" ", "-")
    return f"apex/{key}" if key else ""


def _row(finding: Any) -> list[str]:
    """One CSV row for a finding, reading only attributes it actually exposes.

    Tolerant by design: a :class:`ReviewFinding` carries ``file``; a raw
    detector :class:`Issue` does not (it is line-level, path-free), so ``path``
    falls back to an empty cell. ``check`` is the detector's ``fix_kind`` routing
    key (blank when the issue is flag-only / not auto-fixable). Everything is
    coerced to ``str`` so the ``csv`` module can quote it uniformly.
    """
    path = getattr(finding, "file", "") or getattr(finding, "path", "") or ""
    line = getattr(finding, "line", "")
    category = getattr(finding, "category", "") or ""
    severity = getattr(finding, "severity", "") or ""
    check = getattr(finding, "fix_kind", "") or ""
    message = getattr(finding, "message", "") or ""
    return [
        str(path),
        "" if line in ("", None) else str(line),
        "",  # column: Apex findings are line-level (stable empty slot)
        str(severity),
        str(category),
        str(check),
        str(message),
        _rule_id(check, category),
    ]


def to_csv(findings: Iterable[Any]) -> str:
    """Render an iterable of findings as a CSV document (header + one row each).

    The ``csv`` module handles all quoting/escaping, so a ``message`` containing
    commas, double quotes, or embedded newlines round-trips through
    ``csv.reader`` unchanged. The line terminator is pinned to ``"\\n"`` (not the
    platform default ``"\\r\\n"``) so the bytes are identical on every OS — a
    determinism requirement for audit trails and golden-file tests.

    Findings are written in the order given; callers that need a canonical order
    (e.g. the review's severity/file/line sort) sort before passing them in. An
    empty iterable yields a header-only document.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    for finding in findings:
        writer.writerow(_row(finding))
    return buffer.getvalue()
