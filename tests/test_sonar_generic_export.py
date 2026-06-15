"""SonarQube Generic Issue Import export: Apex findings in SonarQube's shape.

Covers the documented contract of :mod:`app.reporting.sonar_generic_export`:
valid ``{"issues": [...]}`` JSON, the required SonarQube keys on every issue,
the deterministic category->type / severity->severity mapping over every real
Apex category, the ``startLine >= 1`` clamp, the empty/exhausted-iterable case,
and byte-for-byte determinism. Findings are fed in all three accepted shapes
(``Issue``, ``ReviewFinding``, and plain dict) to lock the defensive reader.
"""

from __future__ import annotations

import json

from app.engine.detectors import Issue
from app.engine.diff_review import ReviewFinding
from app.reporting.sonar_generic_export import (
    ENGINE_ID,
    to_sonar_generic,
    to_sonar_generic_json,
    to_sonar_issue,
)

# SonarQube's fixed enumerations — an import is rejected if a value is off-list.
_VALID_SEVERITIES = {"INFO", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"}
_VALID_TYPES = {"BUG", "VULNERABILITY", "CODE_SMELL"}


def _issue(finding):
    """The single built issue for a one-finding input (convenience)."""
    return to_sonar_generic([finding])["issues"][0]


# --- shape / required keys ---------------------------------------------------

def test_top_level_is_issues_array_of_json():
    out = to_sonar_generic_json([
        ReviewFinding("app/m.py", 3, "security", "high", "eval()", True, "eval"),
    ])
    parsed = json.loads(out)
    assert set(parsed) == {"issues"}
    assert isinstance(parsed["issues"], list)
    assert len(parsed["issues"]) == 1


def test_every_issue_has_required_sonar_keys():
    findings = [
        ReviewFinding("a.py", 1, "security", "high", "eval()", True, "eval"),
        ReviewFinding("b.py", 2, "bug", "medium", "dead code", False, ""),
        ReviewFinding("c.py", 3, "style", "low", "== None", True, "none-comparison"),
    ]
    for issue in to_sonar_generic(findings)["issues"]:
        assert issue["engineId"] == ENGINE_ID == "apex"
        assert isinstance(issue["ruleId"], str) and issue["ruleId"].startswith("apex/")
        assert issue["severity"] in _VALID_SEVERITIES
        assert issue["type"] in _VALID_TYPES
        loc = issue["primaryLocation"]
        assert set(loc) == {"message", "filePath", "textRange"}
        assert isinstance(loc["message"], str)
        assert isinstance(loc["filePath"], str)
        assert set(loc["textRange"]) == {"startLine"}
        assert isinstance(loc["textRange"]["startLine"], int)


def test_rule_id_uses_fix_kind_then_category():
    routed = _issue(ReviewFinding("m.py", 1, "security", "high", "eval()", True, "eval"))
    assert routed["ruleId"] == "apex/eval"
    # No fix_kind -> fall back to the category.
    unrouted = _issue(ReviewFinding("m.py", 1, "bug", "medium", "dead code", False, ""))
    assert unrouted["ruleId"] == "apex/bug"
    # A fix_kind with spaces is slugified (mirrors sarif_export).
    spaced = _issue(ReviewFinding("m.py", 1, "security", "medium", "bare except", True, "bare except"))
    assert spaced["ruleId"] == "apex/bare-except"


# --- category -> type mapping ------------------------------------------------

def test_category_to_type_mapping_exhaustive():
    expected = {
        "security": "VULNERABILITY",
        "bug": "BUG",
        "style": "CODE_SMELL",
        "docs": "CODE_SMELL",
        "convention": "CODE_SMELL",
        "refactor": "CODE_SMELL",
    }
    for category, sonar_type in expected.items():
        issue = _issue(ReviewFinding("m.py", 1, category, "medium", "msg", False, ""))
        assert issue["type"] == sonar_type, category


def test_unknown_category_defaults_to_code_smell():
    # A future/unrecognised category must never escalate the gate.
    issue = _issue(ReviewFinding("m.py", 1, "telemetry", "high", "msg", False, ""))
    assert issue["type"] == "CODE_SMELL"
    # Missing category entirely (sparse dict) also defaults to CODE_SMELL.
    assert to_sonar_issue({"line": 1, "message": "x"})["type"] == "CODE_SMELL"


# --- severity mapping --------------------------------------------------------

def test_severity_mapping_per_level():
    # Non-security: high/medium/low -> CRITICAL/MAJOR/MINOR.
    assert _issue(ReviewFinding("m.py", 1, "bug", "high", "x", False, ""))["severity"] == "CRITICAL"
    assert _issue(ReviewFinding("m.py", 1, "bug", "medium", "x", False, ""))["severity"] == "MAJOR"
    assert _issue(ReviewFinding("m.py", 1, "style", "low", "x", False, ""))["severity"] == "MINOR"


def test_high_security_is_blocker_but_medium_security_is_not():
    blocker = _issue(ReviewFinding("m.py", 1, "security", "high", "eval()", True, "eval"))
    assert blocker["severity"] == "BLOCKER"
    assert blocker["type"] == "VULNERABILITY"
    # A medium security finding (e.g. yaml.load) stays MAJOR — only high lifts.
    major = _issue(ReviewFinding("m.py", 1, "security", "medium", "yaml.load", True, "yaml"))
    assert major["severity"] == "MAJOR"


def test_unknown_severity_defaults_to_info():
    assert _issue(ReviewFinding("m.py", 1, "bug", "critical", "x", False, ""))["severity"] == "INFO"
    # Missing severity (sparse dict) also defaults to INFO, never a gate level.
    assert to_sonar_issue({"category": "bug", "line": 1})["severity"] == "INFO"


# --- startLine clamping ------------------------------------------------------

def test_start_line_clamped_to_at_least_one():
    for raw in (0, -5):
        issue = _issue(ReviewFinding("m.py", raw, "bug", "low", "x", False, ""))
        assert issue["primaryLocation"]["textRange"]["startLine"] == 1
    # A valid line is preserved.
    ok = _issue(ReviewFinding("m.py", 42, "bug", "low", "x", False, ""))
    assert ok["primaryLocation"]["textRange"]["startLine"] == 42


def test_missing_or_non_integer_line_becomes_one():
    assert to_sonar_issue({"category": "bug", "message": "x"})[
        "primaryLocation"]["textRange"]["startLine"] == 1
    assert to_sonar_issue({"category": "bug", "line": None, "message": "x"})[
        "primaryLocation"]["textRange"]["startLine"] == 1
    assert to_sonar_issue({"category": "bug", "line": "oops", "message": "x"})[
        "primaryLocation"]["textRange"]["startLine"] == 1


# --- finding-shape coverage --------------------------------------------------

def test_accepts_issue_review_finding_and_dict_shapes():
    # Issue has no file field -> filePath empty; line/category/severity read.
    issue_shape = to_sonar_issue(Issue(7, "security", "high", "eval()", "eval"))
    assert issue_shape["primaryLocation"]["filePath"] == ""
    assert issue_shape["severity"] == "BLOCKER"
    assert issue_shape["primaryLocation"]["textRange"]["startLine"] == 7

    # ReviewFinding carries file -> filePath populated.
    rf_shape = to_sonar_issue(ReviewFinding("pkg/x.py", 4, "bug", "high", "bug!", False, ""))
    assert rf_shape["primaryLocation"]["filePath"] == "pkg/x.py"

    # Plain dict, read via filePath/startLine aliases.
    dict_shape = to_sonar_issue(
        {"category": "style", "severity": "low", "message": "nit",
         "filePath": "d.py", "startLine": 9})
    assert dict_shape["primaryLocation"]["filePath"] == "d.py"
    assert dict_shape["primaryLocation"]["textRange"]["startLine"] == 9
    assert dict_shape["type"] == "CODE_SMELL"


# --- empty input -------------------------------------------------------------

def test_empty_findings_yields_empty_issues():
    assert to_sonar_generic([]) == {"issues": []}
    assert json.loads(to_sonar_generic_json([])) == {"issues": []}


def test_exhausted_iterator_yields_empty_issues():
    assert to_sonar_generic(iter(())) == {"issues": []}


# --- determinism -------------------------------------------------------------

def test_output_is_deterministic_and_order_independent():
    a = ReviewFinding("z.py", 9, "style", "low", "z nit", True, "none-comparison")
    b = ReviewFinding("a.py", 1, "security", "high", "eval()", True, "eval")
    c = ReviewFinding("a.py", 1, "bug", "medium", "dead", False, "")
    first = to_sonar_generic_json([a, b, c])
    # Same findings in a different order must serialize byte-for-byte identically.
    second = to_sonar_generic_json([c, a, b])
    assert first == second
    # Re-running the same call is also identical (no clock/random/network).
    assert to_sonar_generic_json([a, b, c]) == first


def test_issues_sorted_by_path_then_line():
    findings = [
        ReviewFinding("b.py", 1, "bug", "low", "later file", False, ""),
        ReviewFinding("a.py", 5, "bug", "low", "lower file later line", False, ""),
        ReviewFinding("a.py", 2, "bug", "low", "lower file earlier line", False, ""),
    ]
    issues = to_sonar_generic(findings)["issues"]
    located = [(i["primaryLocation"]["filePath"],
               i["primaryLocation"]["textRange"]["startLine"]) for i in issues]
    assert located == [("a.py", 2), ("a.py", 5), ("b.py", 1)]


def test_json_has_trailing_newline_and_is_indented():
    out = to_sonar_generic_json([ReviewFinding("m.py", 1, "bug", "low", "x", False, "")])
    assert out.endswith("}\n")
    # Default indent renders multi-line, readable JSON.
    assert "\n  " in out
    # Compact mode (indent=None) is single-physical-line + newline.
    compact = to_sonar_generic_json(
        [ReviewFinding("m.py", 1, "bug", "low", "x", False, "")], indent=None)
    assert compact.count("\n") == 1
