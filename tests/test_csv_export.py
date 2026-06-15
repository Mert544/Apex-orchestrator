"""Tests for the CSV findings exporter (app.reporting.csv_export).

Each test parses the exporter's output back with ``csv.reader`` and asserts on
the structured rows — proving the document is well-formed CSV, not just a
plausible string. Covers the header contract, row count/values, the tricky
quote/comma/newline round-trip, the empty (header-only) path, and byte-for-byte
determinism.
"""

from __future__ import annotations

import csv
import io

from app.engine.diff_review import ReviewFinding
from app.reporting.csv_export import HEADER, to_csv


def _parse(text: str) -> list[list[str]]:
    """Round-trip the exporter's output back through csv.reader."""
    return list(csv.reader(io.StringIO(text)))


def _finding(**kw) -> ReviewFinding:
    base = dict(
        file="app/x.py", line=10, category="security", severity="high",
        message="eval() — code injection risk", auto_fixable=True, fix_kind="eval",
    )
    base.update(kw)
    return ReviewFinding(**base)


def test_header_row_is_stable():
    rows = _parse(to_csv([]))
    assert rows[0] == list(HEADER)
    assert rows[0] == [
        "path", "line", "column", "severity",
        "category", "check", "message", "rule_id",
    ]


def test_empty_findings_is_header_only():
    out = to_csv([])
    rows = _parse(out)
    assert len(rows) == 1          # header, no data rows
    assert rows[0] == list(HEADER)
    # Pinned line terminator: exactly one trailing newline, no \r.
    assert out.endswith("\n")
    assert "\r" not in out


def test_row_count_and_values():
    findings = [
        _finding(file="a.py", line=3, severity="high", category="security",
                 message="eval() — code injection risk", fix_kind="eval"),
        _finding(file="b.py", line=7, severity="low", category="style",
                 message="use a literal `[]` instead of `list()`",
                 fix_kind="collection-literal"),
    ]
    rows = _parse(to_csv(findings))
    assert len(rows) == 3                      # header + 2 findings
    assert [r[0] for r in rows[1:]] == ["a.py", "b.py"]
    assert [r[1] for r in rows[1:]] == ["3", "7"]
    assert rows[1][3] == "high"
    assert rows[1][4] == "security"
    assert rows[1][5] == "eval"                # check == fix_kind
    assert rows[1][6] == "eval() — code injection risk"
    assert rows[1][7] == "apex/eval"           # rule_id mirrors SARIF
    assert rows[2][7] == "apex/collection-literal"


def test_rule_id_falls_back_to_category_when_no_fix_kind():
    # A flag-only finding (fix_kind="") falls back to the category for its id.
    rows = _parse(to_csv([_finding(fix_kind="", category="bug")]))
    assert rows[1][5] == ""                     # check is blank
    assert rows[1][7] == "apex/bug"             # rule_id uses category


def test_message_with_comma_quote_and_newline_round_trips():
    nasty = 'broke on "x", then\nspilled onto a second line, comma'
    rows = _parse(to_csv([_finding(message=nasty)]))
    assert len(rows) == 2                        # the embedded newline did NOT add a row
    assert rows[1][6] == nasty                   # exact round-trip
    # Sanity: the raw document quotes the field (so the newline is contained).
    raw = to_csv([_finding(message=nasty)])
    assert '"' in raw


def test_path_falls_back_for_path_free_issue():
    # A duck-typed finding without a `file`/`path` attribute → empty path cell,
    # not an error.
    class Issue:
        line = 4
        category = "bug"
        severity = "medium"
        message = "comparison with itself is always constant — likely a typo"
        fix_kind = ""

    rows = _parse(to_csv([Issue()]))
    assert rows[1][0] == ""                       # no path
    assert rows[1][1] == "4"
    assert rows[1][4] == "bug"


def test_column_slot_is_present_and_empty():
    rows = _parse(to_csv([_finding()]))
    assert rows[0][2] == "column"
    assert rows[1][2] == ""                       # line-level findings have no column


def test_deterministic_same_input_same_output():
    findings = [
        _finding(file="a.py", line=1, message='with "quotes", and\nnewline'),
        _finding(file="b.py", line=2, fix_kind="", category="style"),
    ]
    first = to_csv(findings)
    second = to_csv(findings)
    assert first == second                        # byte-for-byte identical
