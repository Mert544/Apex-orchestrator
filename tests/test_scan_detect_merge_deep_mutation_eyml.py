"""Deep-mutation hardening for the SecurityAgent scan-unification merge.

Targets the Batch-2 scan/detect() unification in
``app/agents/skills/security_agent.py``:

  * ``_merge_detect`` — the per-file superset/de-dup/fallback merge,
  * ``_detect_finding`` — mapping a rich ``detect()`` Issue into the agent's
    finding schema (fix_kind -> risk_type, message-derived risk_type, severity),
  * ``_canonical_risk`` — the coarse dedup token (first-substring-wins).

Every assertion pins an EXACT value (a count, a risk_type slug, a canonical
token, a severity) so a flipped comparison / reordered table / changed constant
fails a test rather than silently passing. This is the deep-mutation companion
to ``test_scan_uses_detect_engine_eyml.py`` — that file proves the contract;
this one pins the moving parts mutation-by-mutation.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.skills import SecurityAgent
from app.agents.skills.security_agent import (
    _canonical_risk,
    _detect_finding,
    _DETECT_RISK_TYPE,
    _DETECT_SEVERITY,
)
from app.engine import detectors


def _scan(tmp_path: Path, source: str, rel: str = "m.py") -> list[dict]:
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return SecurityAgent().run(project_root=str(tmp_path))["findings"]


def _issue(line=1, category="security", severity="high", message="msg", fix_kind="tls-verify"):
    return detectors.Issue(line=line, category=category, severity=severity,
                           message=message, fix_kind=fix_kind)


# --- _canonical_risk: first-substring-wins, exact tokens ---------------------

def test_canonical_risk_sql_token_exact():
    assert _canonical_risk("sql_injection") == "sql"


def test_canonical_risk_tls_token_exact():
    assert _canonical_risk("tls_verification_disabled") == "tls"


def test_canonical_risk_pickle_token_exact():
    assert _canonical_risk("pickle_deserialization") == "pickle"


def test_canonical_risk_is_case_insensitive():
    # The lookup lowercases first; an upper-cased risk_type still canonicalises.
    assert _canonical_risk("SQL_INJECTION") == "sql"


def test_canonical_risk_first_match_wins_eval_before_exec():
    # "eval" precedes "exec" in the table; an "eval"-bearing slug must resolve to
    # the eval token, proving order (not later substrings) decides.
    assert _canonical_risk("eval_usage") == "eval"


def test_canonical_risk_secret_family_collapses_to_secret():
    assert _canonical_risk("hardcoded_secret") == "secret"
    assert _canonical_risk("hardcoded_password") == "secret"
    assert _canonical_risk("hardcoded_connection") == "secret"


def test_canonical_risk_unknown_falls_back_to_raw_lowercased():
    assert _canonical_risk("Totally_Unknown") == "totally_unknown"


# --- _detect_finding: fix_kind -> risk_type mapping --------------------------

def test_detect_finding_maps_tls_fix_kind_to_slug():
    f = _detect_finding("a.py", _issue(line=5, fix_kind="tls-verify",
                                       message="TLS verification disabled (verify=False)"))
    assert f["risk_type"] == "tls_verification_disabled"
    assert f["line"] == 5
    assert f["file"] == "a.py"
    assert f["severity"] == "high"


def test_detect_finding_maps_sql_fix_kind_to_slug():
    f = _detect_finding("a.py", _issue(fix_kind="sql", message="SQL built from an f-string"))
    assert f["risk_type"] == "sql_injection"


def test_detect_finding_carries_message_verbatim_into_details_and_suggestion():
    f = _detect_finding("a.py", _issue(message="exact engine text", fix_kind="pickle"))
    assert f["details"] == "exact engine text"
    assert f["suggestion"] == "exact engine text"


def test_detect_finding_unknown_fix_kind_derives_slug_by_replacing_separators():
    # A fix_kind absent from _DETECT_RISK_TYPE: dots and dashes become underscores.
    f = _detect_finding("a.py", _issue(fix_kind="zip-slip.x", message="m"))
    assert f["risk_type"] == "zip_slip_x"


def test_detect_finding_empty_fix_kind_exec_message_derives_exec_usage():
    f = _detect_finding("a.py", _issue(fix_kind="", message="exec() — code injection risk"))
    assert f["risk_type"] == "exec_usage"


def test_detect_finding_empty_fix_kind_pickle_load_message():
    f = _detect_finding("a.py", _issue(fix_kind="",
                                       message="pickle.load() of untrusted input executes ..."))
    assert f["risk_type"] == "pickle_deserialization"


def test_detect_finding_empty_fix_kind_marshal_message():
    f = _detect_finding("a.py", _issue(fix_kind="", message="marshal.load()/loads() is unsafe ..."))
    assert f["risk_type"] == "unsafe_deserialization"


def test_detect_finding_empty_fix_kind_shell_true_message():
    f = _detect_finding("a.py", _issue(fix_kind="", message="subprocess with shell=True — risk"))
    assert f["risk_type"] == "subprocess_shell_injection"


def test_detect_finding_empty_fix_kind_hardcoded_secret_message():
    f = _detect_finding("a.py", _issue(fix_kind="",
                                       message="possible hardcoded secret — load it from env"))
    assert f["risk_type"] == "hardcoded_secret"


def test_detect_finding_empty_fix_kind_unknown_message_falls_back_security_issue():
    f = _detect_finding("a.py", _issue(fix_kind="", message="some novel risk text"))
    assert f["risk_type"] == "security_issue"


def test_detect_finding_severity_mapping_preserves_medium_and_low():
    assert _detect_finding("a.py", _issue(severity="medium", fix_kind="yaml"))["severity"] == "medium"
    assert _detect_finding("a.py", _issue(severity="low", fix_kind="weak-hash"))["severity"] == "low"


def test_detect_finding_unknown_severity_defaults_to_low():
    # _DETECT_SEVERITY only knows high|medium|low; anything else -> "low".
    f = _detect_finding("a.py", _issue(severity="critical", fix_kind="sql"))
    assert f["severity"] == "low"


def test_detect_severity_table_is_identity_on_known_keys():
    assert _DETECT_SEVERITY == {"high": "high", "medium": "medium", "low": "low"}


def test_detect_risk_type_table_has_the_tls_and_sql_anchors():
    # Pin the two slugs the red-team specifically required (superset evidence).
    assert _DETECT_RISK_TYPE["tls-verify"] == "tls_verification_disabled"
    assert _DETECT_RISK_TYPE["sql"] == "sql_injection"


# --- _merge_detect: superset behaviour ---------------------------------------

# TLS-off + f-string SQL were invisible to the legacy patterns; pickle.load was
# missed by the legacy patterns too (legacy only knows pickle.loads). All three
# must surface via the detect() merge.
_SUPERSET_FIXTURE = (
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


def test_merge_surfaces_tls_sql_and_pickle(tmp_path: Path):
    risk_types = {f["risk_type"] for f in _scan(tmp_path, _SUPERSET_FIXTURE)}
    assert "tls_verification_disabled" in risk_types
    assert "sql_injection" in risk_types
    assert "pickle_deserialization" in risk_types


def test_merge_tls_finding_lands_on_its_source_line(tmp_path: Path):
    findings = _scan(tmp_path, _SUPERSET_FIXTURE)
    tls = [f for f in findings if f["risk_type"] == "tls_verification_disabled"]
    assert len(tls) == 1
    assert tls[0]["line"] == 5
    assert tls[0]["severity"] == "high"


# --- _merge_detect: de-dup (same risk, same line, both engines) --------------

def test_eval_flagged_by_both_engines_reported_exactly_once(tmp_path: Path):
    # eval() is in legacy CRITICAL_PATTERNS AND detect()'s rules — once total.
    findings = _scan(tmp_path, "def run(code):\n    return eval(code)\n")
    eval_hits = [f for f in findings if f["line"] == 2 and "eval" in f["risk_type"].lower()]
    assert len(eval_hits) == 1


def test_dedup_keeps_legacy_finding_not_detect_one(tmp_path: Path):
    # The de-dup keeps the legacy finding (risk_type 'eval() usage' from
    # CRITICAL_PATTERNS, severity critical) and drops the detect() duplicate
    # (which would be 'eval_usage' at severity high). Pin the surviving record.
    findings = _scan(tmp_path, "def run(code):\n    return eval(code)\n")
    eval_hits = [f for f in findings if f["line"] == 2 and "eval" in f["risk_type"].lower()]
    assert len(eval_hits) == 1
    assert eval_hits[0]["severity"] == "critical"
    assert eval_hits[0]["risk_type"] == "eval() usage"


def test_os_system_not_double_counted(tmp_path: Path):
    findings = _scan(tmp_path, "import os\ndef r(c):\n    os.system(c)\n")
    os_hits = [f for f in findings
               if f["line"] == 3 and _canonical_risk(f["risk_type"]) == "os.system"]
    assert len(os_hits) == 1


# --- _merge_detect: clean file & empties ------------------------------------

def test_clean_file_yields_no_findings(tmp_path: Path):
    clean = (
        "import json\n"
        "\n"
        "def load(path):\n"
        '    with open(path, encoding="utf-8") as f:\n'
        "        return json.load(f)\n"
    )
    assert _scan(tmp_path, clean) == []


def test_empty_source_is_safe(tmp_path: Path):
    assert _scan(tmp_path, "") == []


# --- _merge_detect: detect() crash falls back to legacy ----------------------

def test_detect_crash_falls_back_to_legacy_findings(tmp_path: Path, monkeypatch):
    def boom(_source: str):
        raise RuntimeError("synthetic detect failure")

    monkeypatch.setattr(detectors, "detect", boom)
    # eval() is in legacy CRITICAL_PATTERNS, so the fallback still flags it once.
    findings = _scan(tmp_path, "def run(code):\n    return eval(code)\n")
    eval_hits = [f for f in findings if "eval" in f["risk_type"].lower()]
    assert len(eval_hits) == 1
    # The fallback returns the legacy list verbatim — no detect-sourced extras.
    assert eval_hits[0]["severity"] == "critical"


def test_detect_crash_on_clean_file_yields_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(detectors, "detect",
                        lambda _s: (_ for _ in ()).throw(RuntimeError("boom")))
    clean = "import json\n\ndef f(p):\n    return json.load(p)\n"
    assert _scan(tmp_path, clean) == []


# --- _merge_detect: determinism & ordering ----------------------------------

def test_merge_sorted_by_line_then_details(tmp_path: Path):
    findings = _scan(tmp_path, _SUPERSET_FIXTURE)
    keys = [(f["line"], f["details"]) for f in findings]
    assert keys == sorted(keys)


def test_merge_is_deterministic_across_runs(tmp_path: Path):
    (tmp_path / "m.py").write_text(_SUPERSET_FIXTURE, encoding="utf-8")
    first = SecurityAgent().run(project_root=str(tmp_path))["findings"]
    second = SecurityAgent().run(project_root=str(tmp_path))["findings"]
    assert first == second


# --- _merge_detect: non-security detect Issues are excluded ------------------

def test_non_security_detect_issue_not_merged(tmp_path: Path):
    # A bare f-string-without-placeholder is a STYLE finding in detect(); it must
    # NOT leak into the security scan's findings.
    src = "def f():\n    return f'no placeholder'\n"
    findings = _scan(tmp_path, src)
    assert findings == []
