from __future__ import annotations

import html as _html
import re

from app.engine.detectors import Issue
from app.reporting.findings_html import findings_to_html


def _finding(**kw):
    """A finding as a plain dict (the renderer accepts dicts or objects)."""
    base = {
        "file": "app/x.py",
        "line": 1,
        "category": "bug",
        "severity": "low",
        "message": "something",
    }
    base.update(kw)
    return base


def _assert_self_contained(doc: str) -> None:
    """A single, offline, self-contained HTML document — no network, no scripts."""
    assert doc.startswith("<!DOCTYPE html>")
    assert "</html>" in doc
    assert "<style>" in doc          # CSS is inlined
    assert "http://" not in doc      # no remote resources of any kind
    assert "https://" not in doc
    assert 'rel="stylesheet"' not in doc
    assert "<link" not in doc
    assert "<script" not in doc
    assert "src=" not in doc
    assert "@import" not in doc
    assert "url(" not in doc


def test_valid_document_skeleton():
    doc = findings_to_html([_finding()])
    _assert_self_contained(doc)
    assert "<title>Apex Findings</title>" in doc
    assert "<table>" in doc and "</table>" in doc


def test_custom_title_is_escaped():
    doc = findings_to_html([], title='Audit <of> "X" & Y')
    assert "<title>Audit &lt;of&gt; &quot;X&quot; &amp; Y</title>" in doc
    assert "Audit <of>" not in doc


def test_severity_counts_are_correct():
    findings = [
        _finding(severity="high"),
        _finding(severity="high"),
        _finding(severity="medium"),
        _finding(severity="low"),
        _finding(severity="low"),
        _finding(severity="low"),
    ]
    doc = findings_to_html(findings)
    # Total chip plus a chip per present severity, with exact counts.
    assert "<strong>6</strong> findings" in doc
    assert '<strong>2</strong> high' in doc
    assert '<strong>1</strong> medium' in doc
    assert '<strong>3</strong> low' in doc


def test_single_finding_uses_singular_label():
    doc = findings_to_html([_finding(severity="high")])
    assert "<strong>1</strong> finding<" in doc  # "finding" not "findings"


def test_unknown_severity_falls_into_other_bucket():
    doc = findings_to_html([_finding(severity="critical"), _finding(severity="high")])
    assert "<strong>1</strong> other" in doc
    assert "<strong>1</strong> high" in doc


def test_malicious_finding_is_escaped():
    nasty = '<script>alert(1)</script> & "quoted"'
    doc = findings_to_html([_finding(message=nasty, file='a"<b>.py', category="<x>")])
    # The raw, dangerous markup never appears unescaped anywhere in the page.
    assert "<script>alert(1)</script>" not in doc
    assert "<x>" not in doc
    # The escaped forms are present instead.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in doc
    assert "&amp;" in doc and "&quot;" in doc
    assert "&lt;x&gt;" in doc
    _assert_self_contained(doc)


def test_findings_sorted_by_severity_then_path_then_line():
    findings = [
        _finding(severity="low", file="b.py", line=3, message="low-b"),
        _finding(severity="high", file="b.py", line=1, message="high-b"),
        _finding(severity="high", file="a.py", line=9, message="high-a"),
        _finding(severity="medium", file="a.py", line=2, message="med-a"),
    ]
    doc = findings_to_html(findings)
    order = [
        doc.index("high-a"),  # high before medium/low; a.py before b.py
        doc.index("high-b"),
        doc.index("med-a"),
        doc.index("low-b"),
    ]
    assert order == sorted(order)


def test_empty_findings_is_a_valid_no_findings_page():
    doc = findings_to_html([])
    _assert_self_contained(doc)
    assert "No findings" in doc
    # No table is emitted for an empty set.
    assert "<table>" not in doc


def test_determinism_same_input_same_output():
    findings = [
        _finding(severity="high", file="z.py", line=4, message="z"),
        _finding(severity="low", file="a.py", line=1, message="a"),
        _finding(severity="medium", file="m.py", line=2, message="m"),
    ]
    first = findings_to_html(findings)
    second = findings_to_html(findings)
    assert first == second
    # Insensitive to emit order: the same findings shuffled render identically.
    shuffled = list(reversed(findings))
    assert findings_to_html(shuffled) == first


def test_generated_on_is_injectable_and_default_empty():
    bare = findings_to_html([_finding()])
    assert "generated on" not in bare
    stamped = findings_to_html([_finding()], generated_on="<run 1>")
    assert "generated on &lt;run 1&gt;" in stamped
    assert stamped == findings_to_html([_finding()], generated_on="<run 1>")


def test_no_volatile_token_by_default():
    doc = findings_to_html([_finding()])
    assert not re.search(r"\d{4}-\d{2}-\d{2}", doc)  # no ISO date
    assert not re.search(r"\d{2}:\d{2}:\d{2}", doc)  # no clock time


def test_accepts_detector_issue_objects():
    # The detector's Issue has no `file` field; it must still render (line-only)
    # without raising, proving the renderer is decoupled from any one shape.
    issues = [
        Issue(line=12, category="security", severity="high",
              message="eval() — code injection risk", fix_kind="eval"),
        Issue(line=3, category="style", severity="low",
              message="compare to None with `is`", fix_kind="none-comparison"),
    ]
    doc = findings_to_html(issues)
    _assert_self_contained(doc)
    assert _html.escape("eval() — code injection risk", quote=True) in doc
    assert "<strong>1</strong> high" in doc
    assert "<strong>1</strong> low" in doc
