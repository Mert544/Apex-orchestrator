"""CodeClimate / GitLab "Code Quality" export: Apex findings as the JSON array
GitLab's merge-request widget ingests (a drop-in `gl-code-quality-report.json`).

Covers: a valid JSON array with the spec'd keys, the Apex->CodeClimate severity
mapping for every Apex severity, a stable+distinct fingerprint (CI dedup depends
on determinism), the empty case, repo-relative paths, dict findings, and a
`<&>`-laden message round-tripping through JSON unscathed.
"""

from __future__ import annotations

import json

from app.engine.detectors import Issue
from app.engine.diff_review import ReviewFinding
from app.reporting.codeclimate_export import (
    CODECLIMATE_SEVERITIES,
    to_codeclimate_json,
    to_codeclimate_json_from_findings,
)

_REQUIRED_KEYS = {"description", "check_name", "fingerprint", "severity", "location"}


def _rf(file="app/m.py", line=4, category="security", severity="high",
        message="eval() on input", auto_fixable=True, fix_kind="eval"):
    return ReviewFinding(file, line, category, severity, message, auto_fixable, fix_kind)


def test_emits_valid_json_array_with_required_keys():
    out = to_codeclimate_json([_rf()])
    issues = json.loads(out)
    assert isinstance(issues, list)
    assert len(issues) == 1
    issue = issues[0]
    assert _REQUIRED_KEYS.issubset(issue)
    # The CodeClimate location shape: a path and a 1-based begin line.
    assert issue["location"]["path"] == "app/m.py"
    assert issue["location"]["lines"]["begin"] == 4
    assert issue["description"] == "eval() on input"
    # check_name mirrors sarif's rule id (fix_kind, then category).
    assert issue["check_name"] == "apex/eval"


def test_severity_mapping_for_each_apex_severity():
    findings = [
        _rf(line=1, severity="high"),
        _rf(line=2, severity="medium"),
        _rf(line=3, severity="low"),
    ]
    issues = json.loads(to_codeclimate_json(findings))
    by_line = {i["location"]["lines"]["begin"]: i["severity"] for i in issues}
    assert by_line[1] == "critical"   # high  -> critical
    assert by_line[2] == "major"      # medium -> major
    assert by_line[3] == "minor"      # low   -> minor
    # Every emitted severity is inside the CodeClimate vocabulary.
    assert set(by_line.values()).issubset(set(CODECLIMATE_SEVERITIES))


def test_unknown_severity_falls_back_to_minor():
    issues = json.loads(to_codeclimate_json([_rf(severity="bogus")]))
    assert issues[0]["severity"] == "minor"
    assert issues[0]["severity"] in CODECLIMATE_SEVERITIES


def test_check_name_falls_back_to_category_then_constant():
    # No fix_kind -> category; the category's spaces are slugified.
    no_fixkind = _rf(category="bare except", fix_kind="")
    issues = json.loads(to_codeclimate_json([no_fixkind]))
    assert issues[0]["check_name"] == "apex/bare-except"
    # Neither fix_kind nor category -> a stable constant.
    bare = _rf(category="", fix_kind="")
    issues = json.loads(to_codeclimate_json([bare]))
    assert issues[0]["check_name"] == "apex/finding"


def test_fingerprint_is_stable_across_two_calls():
    finding = _rf()
    first = json.loads(to_codeclimate_json([finding]))
    second = json.loads(to_codeclimate_json([finding]))
    assert first[0]["fingerprint"] == second[0]["fingerprint"]
    # The whole artifact is byte-identical run to run (CI dedup relies on it).
    assert to_codeclimate_json([finding]) == to_codeclimate_json([finding])
    # A SHA-256 hex digest: 64 lowercase hex chars.
    fp = first[0]["fingerprint"]
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_differs_for_different_findings():
    a = json.loads(to_codeclimate_json([_rf(line=1)]))[0]["fingerprint"]
    b = json.loads(to_codeclimate_json([_rf(line=2)]))[0]["fingerprint"]
    c = json.loads(to_codeclimate_json([_rf(message="other issue")]))[0]["fingerprint"]
    d = json.loads(to_codeclimate_json([_rf(file="app/other.py")]))[0]["fingerprint"]
    e = json.loads(to_codeclimate_json([_rf(fix_kind="os.system")]))[0]["fingerprint"]
    assert len({a, b, c, d, e}) == 5  # line, message, path, check_name all matter


def test_empty_findings_yields_empty_array():
    out = to_codeclimate_json([])
    assert json.loads(out) == []


def test_message_with_angle_and_amp_round_trips():
    msg = "fix `a < b && c > d` <&> escaping"
    issues = json.loads(to_codeclimate_json([_rf(message=msg)]))
    # JSON handles escaping; the value comes back out exactly as it went in.
    assert issues[0]["description"] == msg
    # And it never leaked HTML-style entities into the raw serialization.
    raw = to_codeclimate_json([_rf(message=msg)])
    assert "&amp;" not in raw and "&lt;" not in raw


def test_project_root_makes_paths_relative():
    finding = _rf(file="/home/user/proj/app/m.py")
    issues = json.loads(to_codeclimate_json([finding], project_root="/home/user/proj"))
    assert issues[0]["location"]["path"] == "app/m.py"
    # A path outside the root is left untouched.
    other = _rf(file="/elsewhere/x.py")
    issues = json.loads(to_codeclimate_json([other], project_root="/home/user/proj"))
    assert issues[0]["location"]["path"] == "/elsewhere/x.py"


def test_accepts_dict_findings_with_path_synonym():
    # Raw detector/dict findings use `path` rather than `file`.
    finding = {
        "path": "app/d.py",
        "line": 7,
        "category": "bug",
        "severity": "medium",
        "message": "mutable default argument",
        "fix_kind": "mutable-default",
    }
    issues = json.loads(to_codeclimate_json([finding]))
    assert issues[0]["location"]["path"] == "app/d.py"
    assert issues[0]["location"]["lines"]["begin"] == 7
    assert issues[0]["severity"] == "major"
    assert issues[0]["check_name"] == "apex/mutable-default"


def test_accepts_issue_objects_without_a_path_field():
    # An `Issue` carries no path (line-level only); it exports with an empty path
    # and still produces a valid issue object.
    issue_obj = Issue(line=3, category="style", severity="low",
                      message="use a literal `[]`", fix_kind="collection-literal")
    issues = json.loads(to_codeclimate_json([issue_obj]))
    assert issues[0]["location"]["path"] == ""
    assert issues[0]["location"]["lines"]["begin"] == 3
    assert issues[0]["severity"] == "minor"


def test_output_is_deterministically_sorted():
    findings = [
        _rf(file="b.py", line=2, message="z"),
        _rf(file="a.py", line=5, message="m"),
        _rf(file="a.py", line=1, message="q"),
    ]
    issues = json.loads(to_codeclimate_json(findings))
    paths_lines = [(i["location"]["path"], i["location"]["lines"]["begin"]) for i in issues]
    assert paths_lines == [("a.py", 1), ("a.py", 5), ("b.py", 2)]


def test_convenience_alias_is_the_same_function():
    assert to_codeclimate_json_from_findings is to_codeclimate_json
    findings = [_rf()]
    assert to_codeclimate_json_from_findings(findings) == to_codeclimate_json(findings)


def test_multiple_findings_all_present():
    findings = [_rf(line=1, fix_kind="eval"), _rf(line=2, fix_kind="os.system")]
    issues = json.loads(to_codeclimate_json(findings))
    assert len(issues) == 2
    for issue in issues:
        assert _REQUIRED_KEYS.issubset(issue)
