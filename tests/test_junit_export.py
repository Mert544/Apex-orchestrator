"""Tests for the JUnit XML exporter (app.reporting.junit_export).

Every test parses the emitted XML with ``xml.etree.ElementTree`` to prove it is
well-formed, then asserts structure/counts. Covers special-character escaping,
the empty-findings (passing) suite, dict-shaped findings, missing fields, and
byte-for-byte determinism.
"""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from app.reporting.junit_export import to_junit_xml


@dataclass
class _Finding:
    """A minimal stand-in for a ReviewFinding (same field names)."""

    file: str
    line: int
    category: str
    severity: str
    message: str
    fix_kind: str = ""
    auto_fixable: bool = False


def _parse(xml: str) -> ET.Element:
    """Parse the XML and return the root <testsuites> element."""
    root = ET.fromstring(xml)
    assert root.tag == "testsuites"
    return root


def _suite(root: ET.Element) -> ET.Element:
    suites = root.findall("testsuite")
    assert len(suites) == 1
    return suites[0]


def test_empty_findings_is_valid_passing_suite():
    xml = to_junit_xml([])
    root = _parse(xml)
    suite = _suite(root)
    assert suite.get("tests") == "0"
    assert suite.get("failures") == "0"
    assert suite.findall("testcase") == []
    # The suite name defaults to "apex".
    assert root.get("name") == "apex"
    assert suite.get("name") == "apex"


def test_single_finding_structure_and_counts():
    findings = [
        _Finding("app/foo.py", 12, "security", "high", "eval() — code injection risk", "eval"),
    ]
    xml = to_junit_xml(findings)
    root = _parse(xml)
    suite = _suite(root)
    assert suite.get("tests") == "1"
    assert suite.get("failures") == "1"
    cases = suite.findall("testcase")
    assert len(cases) == 1
    case = cases[0]
    assert case.get("classname") == "app/foo.py"
    # Name carries the rule (fix_kind) and the line.
    assert "eval" in case.get("name")
    assert "12" in case.get("name")
    failures = case.findall("failure")
    assert len(failures) == 1
    failure = failures[0]
    assert failure.get("message") == "eval() — code injection risk"
    assert failure.get("type") == "high"
    # The detail body echoes the structured location.
    assert "app/foo.py:12" in failure.text
    assert "eval() — code injection risk" in failure.text


def test_counts_match_finding_total():
    findings = [
        _Finding("a.py", 1, "bug", "medium", "m1"),
        _Finding("a.py", 2, "style", "low", "m2"),
        _Finding("b.py", 3, "security", "high", "m3"),
    ]
    xml = to_junit_xml(findings)
    suite = _suite(_parse(xml))
    assert suite.get("tests") == "3"
    assert suite.get("failures") == "3"
    assert len(suite.findall("testcase")) == 3


def test_special_characters_are_escaped_and_still_parse():
    nasty = 'bad <tag> & "quote" > here'
    findings = [
        _Finding('w<&>"eird.py', 7, "bug & <stuff>", 'sev"<&>', nasty, 'fk<&>"'),
    ]
    xml = to_junit_xml(findings)
    # The raw special characters must NOT appear unescaped in attributes.
    assert "<tag>" not in xml
    assert "&amp;" in xml  # & got escaped somewhere
    # Parsing must succeed (proves the escaping produced well-formed XML).
    root = _parse(xml)
    suite = _suite(root)
    case = suite.findall("testcase")[0]
    # Round-trips back to the original values via the parser.
    assert case.get("classname") == 'w<&>"eird.py'
    failure = case.findall("failure")[0]
    assert failure.get("message") == nasty
    assert failure.get("type") == 'sev"<&>'
    assert nasty in failure.text


def test_dict_shaped_findings_supported():
    findings = [
        {"file": "d.py", "line": 5, "category": "docs", "severity": "low",
         "message": "missing docstring", "fix_kind": "docstring"},
    ]
    xml = to_junit_xml(findings)
    suite = _suite(_parse(xml))
    case = suite.findall("testcase")[0]
    assert case.get("classname") == "d.py"
    assert "docstring" in case.get("name")
    assert case.findall("failure")[0].get("message") == "missing docstring"


def test_missing_file_falls_back_to_placeholder():
    # A line-level Issue-shaped finding with no `file` attribute.
    finding = {"line": 3, "category": "bug", "severity": "medium", "message": "oops"}
    xml = to_junit_xml([finding])
    suite = _suite(_parse(xml))
    case = suite.findall("testcase")[0]
    assert case.get("classname")  # non-empty placeholder
    assert case.findall("failure")[0].get("message") == "oops"


def test_missing_message_yields_nonempty_fallback():
    finding = {"file": "x.py", "line": 1, "category": "bug", "severity": "low"}
    xml = to_junit_xml([finding])
    suite = _suite(_parse(xml))
    failure = suite.findall("testcase")[0].findall("failure")[0]
    assert failure.get("message")  # never empty
    assert failure.get("type") == "low"


def test_deterministic_byte_identical():
    findings = [
        _Finding("b.py", 3, "security", "high", "m3"),
        _Finding("a.py", 10, "style", "low", "m-ten"),
        _Finding("a.py", 2, "bug", "medium", "m-two"),
    ]
    first = to_junit_xml(findings)
    second = to_junit_xml(findings)
    assert first == second


def test_ordering_is_stable_by_file_then_line():
    findings = [
        _Finding("b.py", 3, "security", "high", "m3"),
        _Finding("a.py", 10, "style", "low", "m-ten"),
        _Finding("a.py", 2, "bug", "medium", "m-two"),
    ]
    suite = _suite(_parse(to_junit_xml(findings)))
    classnames = [c.get("classname") for c in suite.findall("testcase")]
    assert classnames == ["a.py", "a.py", "b.py"]
    # Within a.py: line 2 before line 10 (numeric, not lexicographic).
    a_lines = [c.get("name") for c in suite.findall("testcase")
               if c.get("classname") == "a.py"]
    assert a_lines[0].endswith(":2")
    assert a_lines[1].endswith(":10")


def test_custom_suite_name_used_everywhere():
    xml = to_junit_xml([], suite_name="my-scan")
    root = _parse(xml)
    assert root.get("name") == "my-scan"
    assert _suite(root).get("name") == "my-scan"


def test_real_review_finding_shape():
    # Exercise against the actual ReviewFinding dataclass to confirm duck-typing.
    from app.engine.diff_review import ReviewFinding

    f = ReviewFinding(
        file="app/svc.py", line=42, category="security", severity="high",
        message="os.system() — prefer subprocess.run()", auto_fixable=True,
        fix_kind="os.system",
    )
    xml = to_junit_xml([f])
    suite = _suite(_parse(xml))
    assert suite.get("tests") == "1"
    case = suite.findall("testcase")[0]
    assert case.get("classname") == "app/svc.py"
    assert case.findall("failure")[0].get("type") == "high"


def test_xml_declaration_present():
    xml = to_junit_xml([])
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
