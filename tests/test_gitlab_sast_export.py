"""GitLab SAST report export: Apex findings as the JSON object GitLab's
"Security & Compliance" pipeline artifact ingests (a drop-in
`gl-sast-report.json`).

Covers: a valid JSON object carrying a `vulnerabilities` array with the spec'd
keys, the Apex->GitLab severity mapping for every Apex severity, a stable+distinct
`id` (GitLab tracks vulnerabilities by it across runs), the empty case (an empty
`vulnerabilities` array), determinism (no per-run timestamp; byte-stable output),
repo-relative paths, dict findings, and a `<&>`-laden message round-tripping
through JSON unscathed.
"""

from __future__ import annotations

import json

from app.engine.detectors import Issue
from app.engine.diff_review import ReviewFinding
from app.reporting.gitlab_sast_export import (
    GITLAB_SAST_SEVERITIES,
    GITLAB_SAST_VERSION,
    to_gitlab_sast_json,
    to_gitlab_sast_json_from_findings,
)

_REQUIRED_VULN_KEYS = {"id", "category", "name", "description", "severity",
                       "location", "identifiers"}


def _rf(file="app/m.py", line=4, category="security", severity="high",
        message="eval() on input", auto_fixable=True, fix_kind="eval"):
    return ReviewFinding(file, line, category, severity, message, auto_fixable, fix_kind)


def _vulns(out):
    return json.loads(out)["vulnerabilities"]


def test_emits_valid_json_object_with_vulnerabilities_array():
    out = to_gitlab_sast_json([_rf()])
    report = json.loads(out)
    assert isinstance(report, dict)
    assert report["version"] == GITLAB_SAST_VERSION
    assert report["scan"]["scanner"]["id"] == "apex"
    assert report["scan"]["type"] == "sast"
    assert report["scan"]["status"] == "success"
    vulns = report["vulnerabilities"]
    assert isinstance(vulns, list)
    assert len(vulns) == 1


def test_vulnerability_carries_required_keys_and_location():
    vuln = _vulns(to_gitlab_sast_json([_rf()]))[0]
    assert _REQUIRED_VULN_KEYS.issubset(vuln)
    assert vuln["category"] == "sast"
    assert vuln["description"] == "eval() on input"
    assert vuln["location"]["file"] == "app/m.py"
    assert vuln["location"]["start_line"] == 4
    ident = vuln["identifiers"][0]
    assert ident["type"] == "apex_rule"
    assert ident["value"] == "apex/eval"
    assert ident["name"] == "apex/eval"


def test_severity_mapping_for_every_apex_level():
    cases = {"high": "High", "medium": "Medium", "low": "Low"}
    for apex_sev, gitlab_sev in cases.items():
        vuln = _vulns(to_gitlab_sast_json([_rf(severity=apex_sev)]))[0]
        assert vuln["severity"] == gitlab_sev
        assert vuln["severity"] in GITLAB_SAST_SEVERITIES


def test_unknown_severity_falls_back_to_low():
    vuln = _vulns(to_gitlab_sast_json([_rf(severity="bogus")]))[0]
    assert vuln["severity"] == "Low"


def test_id_is_stable_across_runs_and_distinct_per_finding():
    a, b = _rf(line=4), _rf(line=9)
    first = _vulns(to_gitlab_sast_json([a, b]))
    second = _vulns(to_gitlab_sast_json([a, b]))
    ids_first = {v["id"] for v in first}
    ids_second = {v["id"] for v in second}
    # Stable: same findings -> same ids.
    assert ids_first == ids_second
    # Distinct: two findings differing only by line get different ids.
    assert len(ids_first) == 2
    # A sha256 hex digest.
    for v in first:
        assert len(v["id"]) == 64
        int(v["id"], 16)  # raises if not hex


def test_empty_findings_yield_empty_vulnerabilities():
    report = json.loads(to_gitlab_sast_json([]))
    assert report["vulnerabilities"] == []
    # Still a valid, complete report envelope.
    assert report["scan"]["type"] == "sast"
    assert report["version"] == GITLAB_SAST_VERSION


def test_output_is_deterministic_byte_for_byte():
    findings = [_rf(line=9, message="b"), _rf(line=2, message="a"),
                _rf(file="app/z.py", line=1)]
    assert to_gitlab_sast_json(findings) == to_gitlab_sast_json(findings)
    # Reordering the input does not change the output (sorted serialization).
    assert to_gitlab_sast_json(findings) == to_gitlab_sast_json(list(reversed(findings)))


def test_no_clock_field_varies_per_run():
    # The report must carry no start/end time that would shift between runs.
    report = json.loads(to_gitlab_sast_json([_rf()]))
    scan = report["scan"]
    for field in ("start_time", "end_time"):
        if field in scan:
            assert scan[field] in ("", None)


def test_sorted_by_file_then_line():
    findings = [_rf(file="b.py", line=2), _rf(file="a.py", line=5),
                _rf(file="a.py", line=1)]
    vulns = _vulns(to_gitlab_sast_json(findings))
    locs = [(v["location"]["file"], v["location"]["start_line"]) for v in vulns]
    assert locs == [("a.py", 1), ("a.py", 5), ("b.py", 2)]


def test_accepts_issue_objects_and_dicts():
    # A raw detector Issue (no `file` attr) uses its `category` as the rule and
    # defaults the path; a dict finding is read by key.
    issue = Issue(line=3, category="security", severity="medium",
                  message="yaml.load()", fix_kind="yaml")
    vuln = _vulns(to_gitlab_sast_json([issue]))[0]
    assert vuln["severity"] == "Medium"
    assert vuln["identifiers"][0]["value"] == "apex/yaml"
    assert vuln["location"]["start_line"] == 3

    d = {"file": "d.py", "line": 7, "severity": "low",
         "message": "style nit", "category": "style"}
    dvuln = _vulns(to_gitlab_sast_json([d]))[0]
    assert dvuln["location"]["file"] == "d.py"
    assert dvuln["severity"] == "Low"
    assert dvuln["identifiers"][0]["value"] == "apex/style"


def test_rule_prefers_fix_kind_then_category():
    # fix_kind present -> rule from fix_kind; spaces collapse to dashes.
    v = _vulns(to_gitlab_sast_json([_rf(fix_kind="bare except", category="security")]))[0]
    assert v["identifiers"][0]["value"] == "apex/bare-except"
    # No fix_kind -> fall back to category.
    v2 = _vulns(to_gitlab_sast_json([_rf(fix_kind="", category="bug")]))[0]
    assert v2["identifiers"][0]["value"] == "apex/bug"


def test_project_root_is_stripped():
    vuln = _vulns(to_gitlab_sast_json(
        [_rf(file="/repo/app/m.py")], project_root="/repo"))[0]
    assert vuln["location"]["file"] == "app/m.py"


def test_special_characters_round_trip_through_json():
    msg = 'eval(x) with <tag> & "quotes"'
    vuln = _vulns(to_gitlab_sast_json([_rf(message=msg)]))[0]
    assert vuln["description"] == msg


def test_alias_is_same_function():
    assert to_gitlab_sast_json_from_findings is to_gitlab_sast_json
