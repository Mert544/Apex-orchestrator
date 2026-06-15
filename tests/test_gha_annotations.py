"""GitHub Actions annotations export: severity mapping + escaping + determinism."""

from __future__ import annotations

from app.engine.diff_review import ReviewFinding
from app.reporting.gha_annotations import (
    to_gha_annotations,
    to_gha_annotations_lines,
)


def _finding(severity: str, **over) -> ReviewFinding:
    kw = dict(file="app/m.py", line=4, category="security",
              severity=severity, message="msg", auto_fixable=False, fix_kind="eval")
    kw.update(over)
    return ReviewFinding(**kw)


def test_severity_maps_to_command_and_fields():
    line = to_gha_annotations_lines([_finding("high")])[0]
    # command prefix + the file/line/title properties, then ::message
    assert line.startswith("::error ")
    assert "file=app/m.py" in line
    assert "line=4" in line
    assert "title=apex/eval" in line
    assert line.endswith("::msg")


def test_each_severity_picks_its_command():
    lines = to_gha_annotations_lines([
        _finding("high"), _finding("medium"), _finding("low"),
    ])
    assert [ln.split(" ", 1)[0] for ln in lines] == ["::error", "::warning", "::notice"]


def test_unknown_severity_falls_back_to_notice():
    line = to_gha_annotations_lines([_finding("catastrophic")])[0]
    assert line.startswith("::notice ")


def test_title_falls_back_to_category_then_finding():
    # no fix_kind -> category; no category either -> "finding"
    cat = to_gha_annotations_lines([_finding("low", fix_kind="", category="docs")])[0]
    assert "title=apex/docs" in cat
    fallback = to_gha_annotations_lines([_finding("low", fix_kind="", category="")])[0]
    assert "title=apex/finding" in fallback


def test_line_is_clamped_to_at_least_one():
    assert "line=1" in to_gha_annotations_lines([_finding("high", line=0)])[0]


def test_message_escaping_percent_and_newlines():
    # % must be escaped FIRST so the % of %0D/%0A is not double-escaped.
    f = _finding("high", message="100% off\r\nnext line")
    line = to_gha_annotations_lines([f])[0]
    body = line.split("::", 2)[2]
    assert body == "100%25 off%0D%0Anext line"
    assert "%2525" not in line  # no double-escaping anywhere


def test_message_keeps_colon_and_comma_literal():
    # In the MESSAGE (not a property value), ':' and ',' are NOT escaped.
    f = _finding("high", message="see: a, b")
    body = to_gha_annotations_lines([f])[0].split("::", 2)[2]
    assert body == "see: a, b"


def test_property_value_escapes_colon_comma_percent_newlines():
    # A path/title carrying every reserved character is escaped per property rules.
    f = _finding("high", file="a:b,c%d\r\ne.py", fix_kind="k:1,2")
    line = to_gha_annotations_lines([f])[0]
    assert "file=a%3Ab%2Cc%25d%0D%0Ae.py" in line
    assert "title=apex/k%3A1%2C2" in line


def test_suggestion_appended_to_message():
    f = _finding("high", suggestion=("eval(c)", "ast.literal_eval(c)"))
    body = to_gha_annotations_lines([f])[0].split("::", 2)[2]
    assert "Suggested fix: replace `eval(c)` with `ast.literal_eval(c)`." in body


def test_auto_fixable_note_when_no_suggestion():
    f = _finding("high", auto_fixable=True)
    body = to_gha_annotations_lines([f])[0].split("::", 2)[2]
    assert body.endswith("Auto-fixable by `apex maintain`.")


def test_empty_findings_yield_empty_string():
    assert to_gha_annotations([]) == ""
    assert to_gha_annotations_lines([]) == []


def test_joined_output_is_newline_separated_no_trailing_newline():
    out = to_gha_annotations([_finding("high"), _finding("low")])
    assert "\n" in out
    assert not out.endswith("\n")
    assert out.count("\n") == 1  # two findings -> exactly one separator


def test_deterministic_same_input_same_output():
    findings = [_finding("high", message="a%b"), _finding("medium", line=9)]
    assert to_gha_annotations(findings) == to_gha_annotations(findings)
    # order is preserved exactly as given
    swapped = list(reversed(findings))
    assert to_gha_annotations(swapped) != to_gha_annotations(findings)
