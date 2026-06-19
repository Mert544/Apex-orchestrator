"""`apex scan`'s security agent must be a SUPERSET of the rich detect() engine.

Two external-project red-teams found that `scan` used a WEAKER legacy pattern set
than `grade`/`maintain` (which read `app.engine.detectors.detect`), so a buyer who
ran `scan` first saw a misleadingly CLEAN picture — TLS-off, f-string SQL, and
other findings `grade` reports were silently missing. These tests pin the fix:
the per-file security scan now ALSO runs `detect()` and merges its
``category=="security"`` issues, de-duplicated, into the agent's findings.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.skills import SecurityAgent
from app.agents.skills.security_agent import _canonical_risk, _DETECT_RISK_TYPE
from app.engine import detectors


# A file the legacy CRITICAL_PATTERNS missed: TLS verification disabled and an
# f-string SQL query were NOT in the old pattern set; pickle deserialization was.
_FIXTURE = (
    "import requests\n"
    "import pickle\n"
    "\n"
    "def fetch(url):\n"
    "    return requests.get(url, verify=False)\n"
    "\n"
    "def query(cursor, name):\n"
    "    cursor.execute(f'SELECT * FROM users WHERE name = {name}')\n"
    "\n"
    "def load(stream):\n"
    "    return pickle.load(stream)\n"
)


def _scan(tmp_path: Path, source: str, rel: str = "m.py") -> list[dict]:
    (tmp_path / rel).write_text(source, encoding="utf-8")
    result = SecurityAgent().run(project_root=str(tmp_path))
    return result["findings"]


def _detect_risk_type(issue: detectors.Issue) -> str:
    """The risk_type slug the agent assigns a detect Issue (mirrors the merge)."""
    rt = _DETECT_RISK_TYPE.get(issue.fix_kind)
    if rt is None and issue.fix_kind:
        rt = issue.fix_kind.replace("-", "_").replace(".", "_")
    if rt is None:
        for needle, slug in (
            ("exec()", "exec_usage"),
            ("pickle.load", "pickle_deserialization"),
            ("marshal.load", "unsafe_deserialization"),
            ("shell=True", "subprocess_shell_injection"),
            ("hardcoded secret", "hardcoded_secret"),
        ):
            if needle in issue.message:
                rt = slug
                break
    return rt or "security_issue"


def _security_detect_canon(source: str) -> set[tuple[int, str]]:
    """(line, canonical-risk) of every security Issue the rich engine reports."""
    return {
        (i.line, _canonical_risk(_detect_risk_type(i)))
        for i in detectors.detect(source)
        if i.category == "security"
    }


def test_scan_reports_tls_sql_and_pickle_previously_missed(tmp_path: Path):
    findings = _scan(tmp_path, _FIXTURE)
    risk_types = {f["risk_type"] for f in findings}
    # TLS-off and f-string SQL were invisible to the legacy scan; pickle was not.
    assert "tls_verification_disabled" in risk_types
    assert "sql_injection" in risk_types
    assert "pickle_deserialization" in risk_types


def test_scan_is_a_superset_of_detect_security(tmp_path: Path):
    """Every security issue detect() flags is covered by the scan's findings.

    The superset is at (line, canonical-risk) granularity: for every security
    Issue detect() reports, the merged scan carries a finding on that line for
    that risk (either the legacy finding for an issue both engines see, or the
    newly-merged detect finding for one the legacy patterns missed). This is the
    honest superset proof — and the reason a buyer running `scan` no longer sees
    a cleaner picture than `grade`/`maintain`.
    """
    findings = _scan(tmp_path, _FIXTURE)
    scan_keys = {(f["line"], _canonical_risk(f["risk_type"])) for f in findings}
    detect_keys = _security_detect_canon(_FIXTURE)
    assert detect_keys, "fixture must produce detect security findings"
    missing = detect_keys - scan_keys
    assert not missing, f"scan missed detect security findings: {missing}"


def test_detect_only_messages_are_carried_verbatim(tmp_path: Path):
    """For a risk ONLY the rich engine flags (TLS-off), the detect message is
    carried verbatim into the merged finding's details — provably traceable."""
    findings = _scan(tmp_path, _FIXTURE)
    details = {f["details"] for f in findings}
    tls_messages = {
        i.message for i in detectors.detect(_FIXTURE)
        if i.category == "security" and i.fix_kind == "tls-verify"
    }
    assert tls_messages
    assert tls_messages <= details


def test_clean_file_yields_no_findings(tmp_path: Path):
    clean = (
        "import json\n"
        "\n"
        "def load(path):\n"
        '    with open(path, encoding="utf-8") as f:\n'
        "        return json.load(f)\n"
    )
    assert _scan(tmp_path, clean) == []


def test_no_duplicate_when_both_engines_flag_same_line(tmp_path: Path):
    """eval() is flagged by BOTH the legacy patterns and detect() — once each in
    isolation. The merged scan must report it exactly ONCE for that line."""
    findings = _scan(tmp_path, "def run(code):\n    return eval(code)\n")
    eval_on_line_2 = [
        f for f in findings
        if f["line"] == 2 and _is_eval_risk(f["risk_type"])
    ]
    assert len(eval_on_line_2) == 1


def _is_eval_risk(risk_type: str) -> bool:
    return "eval" in risk_type.lower()


def test_deterministic_across_two_runs(tmp_path: Path):
    (tmp_path / "m.py").write_text(_FIXTURE, encoding="utf-8")
    first = SecurityAgent().run(project_root=str(tmp_path))["findings"]
    second = SecurityAgent().run(project_root=str(tmp_path))["findings"]
    assert first == second


def test_findings_sorted_by_line_then_details(tmp_path: Path):
    findings = _scan(tmp_path, _FIXTURE)
    keys = [(f["line"], f["details"]) for f in findings]
    assert keys == sorted(keys)


def test_detect_failure_falls_back_to_legacy(tmp_path: Path, monkeypatch):
    """A detect() crash on one file must NOT crash the scan — it falls back to the
    legacy pattern findings for that file."""
    def boom(_source: str):
        raise RuntimeError("synthetic detect failure")

    monkeypatch.setattr(detectors, "detect", boom)
    # eval() is in the legacy CRITICAL_PATTERNS, so the fallback still flags it.
    findings = _scan(tmp_path, "def run(code):\n    return eval(code)\n")
    assert any("eval" in f["risk_type"].lower() for f in findings)


def test_merged_findings_preserve_agent_schema(tmp_path: Path):
    """Every merged finding (legacy or detect-sourced) keeps the agent's dict
    schema so downstream consumers don't break."""
    findings = _scan(tmp_path, _FIXTURE)
    assert findings
    required = {"file", "line", "risk_type", "severity", "details", "suggestion"}
    for f in findings:
        assert required <= set(f.keys())
        assert f["severity"] in ("critical", "high", "medium", "low")


def test_detect_only_finding_carries_engine_severity(tmp_path: Path):
    """A finding that ONLY the rich engine produces (TLS-off) is merged with a
    valid agent-vocabulary severity."""
    findings = _scan(tmp_path, _FIXTURE)
    tls = [f for f in findings if f["risk_type"] == "tls_verification_disabled"]
    assert tls
    assert tls[0]["severity"] == "high"


def test_empty_source_is_safe(tmp_path: Path):
    assert _scan(tmp_path, "") == []
