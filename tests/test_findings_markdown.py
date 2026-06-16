"""Tests for app.reporting.findings_markdown — deterministic Markdown report."""

from __future__ import annotations

from app.reporting.findings_markdown import (
    findings_to_markdown,
    findings_to_step_summary,
)


def _f(file="a.py", line=1, category="security", severity="high", message="boom"):
    """A finding as a plain dict (duck-typed input the renderer accepts)."""
    return {"file": file, "line": line, "category": category,
            "severity": severity, "message": message}


def _data_rows(markdown: str) -> list[str]:
    """Table body rows (drop header + separator + non-table lines)."""
    rows = [ln for ln in markdown.splitlines() if ln.startswith("|")]
    # rows[0] is the header, rows[1] the --- separator.
    return rows[2:]


def test_table_rows_and_counts_present():
    findings = [
        _f(file="a.py", line=10, severity="high", category="security", message="m1"),
        _f(file="b.py", line=2, severity="medium", category="bug", message="m2"),
        _f(file="c.py", line=3, severity="low", category="style", message="m3"),
    ]
    out = findings_to_markdown(findings)
    assert out.startswith("## Apex Findings")
    # Counts line reflects each tier.
    assert "3 findings" in out
    assert "1 high" in out and "1 medium" in out and "1 low" in out
    # One data row per finding, header present.
    assert "| Severity | File:Line | Category | Message |" in out
    assert len(_data_rows(out)) == 3
    # Locations rendered as file:line.
    assert "a.py:10" in out and "b.py:2" in out and "c.py:3" in out


def test_custom_title():
    out = findings_to_markdown([_f()], title="My Report")
    assert out.startswith("## My Report")


def test_pipe_and_newline_escaped_keeps_columns():
    nasty = "has a | pipe\nand a newline"
    out = findings_to_markdown([_f(message=nasty)])
    row = _data_rows(out)[0]
    # Exactly 5 pipes delimit 4 columns (leading + 3 separators + trailing).
    assert row.count("|") == 5
    # Raw pipe and newline are neutralized.
    assert "&#124;" in row
    assert "<br>" in row
    # The row is a single line — no embedded newline that would split it.
    assert "\n" not in row


def test_pipe_in_other_fields_escaped():
    out = findings_to_markdown([_f(file="we|rd.py", category="ca|t", severity="high")])
    row = _data_rows(out)[0]
    assert row.count("|") == 5
    assert "we&#124;rd.py" in row
    assert "ca&#124;t" in row


def test_empty_findings_no_findings_line():
    out = findings_to_markdown([])
    assert "No findings" in out
    # No table emitted.
    assert "| Severity |" not in out


def test_empty_step_summary_no_findings_line():
    out = findings_to_step_summary([])
    assert "No findings" in out
    assert "<details>" not in out


def test_severity_ordering_high_to_low():
    findings = [
        _f(file="z.py", line=1, severity="low", message="lo"),
        _f(file="a.py", line=1, severity="high", message="hi"),
        _f(file="m.py", line=1, severity="medium", message="me"),
    ]
    out = findings_to_markdown(findings)
    rows = _data_rows(out)
    # High before medium before low regardless of input order.
    assert "hi" in rows[0]
    assert "me" in rows[1]
    assert "lo" in rows[2]


def test_tiebreak_path_then_line():
    findings = [
        _f(file="b.py", line=5, severity="high", message="b5"),
        _f(file="a.py", line=9, severity="high", message="a9"),
        _f(file="a.py", line=2, severity="high", message="a2"),
    ]
    out = findings_to_markdown(findings)
    rows = _data_rows(out)
    # Same severity → sort by path, then line: a.py:2, a.py:9, b.py:5.
    assert "a2" in rows[0]
    assert "a9" in rows[1]
    assert "b5" in rows[2]


def test_determinism_same_input_same_output():
    findings = [_f(file="b.py", line=2, severity="medium", message="x"),
                _f(file="a.py", line=1, severity="high", message="y")]
    first = findings_to_markdown(findings)
    second = findings_to_markdown(list(findings))
    assert first == second
    # Step summary is deterministic too.
    assert findings_to_step_summary(findings) == findings_to_step_summary(findings)


def test_step_summary_small_set_inline():
    findings = [_f(line=i, message=f"m{i}") for i in range(1, 4)]
    out = findings_to_step_summary(findings)
    assert "<details>" not in out
    assert len(_data_rows(out)) == 3


def test_step_summary_large_set_collapsible():
    findings = [_f(file=f"f{i}.py", line=i, message=f"m{i}") for i in range(20)]
    out = findings_to_step_summary(findings)
    assert "<details>" in out and "</details>" in out
    assert "Show 20 findings" in out
    # Every finding still present inside the collapsible block.
    assert len([ln for ln in out.splitlines() if ln.startswith("|")]) == 22  # 20 + header + sep


def test_missing_file_falls_back():
    # A line-level Issue-style finding with no file still renders.
    out = findings_to_markdown([{"line": 4, "severity": "high",
                                 "category": "bug", "message": "oops"}])
    assert "<unknown>:4" in out


def test_finding_object_duck_typed():
    class Obj:
        file = "o.py"
        line = 7
        category = "bug"
        severity = "high"
        message = "obj message"

    out = findings_to_markdown([Obj()])
    assert "o.py:7" in out and "obj message" in out


def test_singular_finding_noun():
    out = findings_to_markdown([_f()])
    assert "1 finding" in out
    assert "1 findings" not in out


def test_trailing_newline():
    assert findings_to_markdown([_f()]).endswith("\n")
    assert findings_to_markdown([]).endswith("\n")
    assert findings_to_step_summary([_f()]).endswith("\n")
