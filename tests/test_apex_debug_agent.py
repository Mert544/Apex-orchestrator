from app.agents.skills.apex_debug_agent import AgentAnalysisResult, ApexDebugAgent
from app.agents.skills.finding import Finding, Severity


def _proj(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bad.py").write_text(
        "import os\ndef r(c):\n    return eval(c)\ndef s(n):\n    os.system(n)\n"
    )
    return tmp_path


def test_severity_ordering_and_from_name():
    assert Severity.CRITICAL > Severity.HIGH > Severity.LOW
    assert Severity.from_name("critical") == Severity.CRITICAL
    assert Severity.from_name("bogus") == Severity.LOW


def test_run_finds_security_issues(tmp_path):
    _proj(tmp_path)
    result = ApexDebugAgent(tmp_path).run()
    assert len(result.findings) >= 2
    assert result.critical_count >= 2
    assert result.security_count == len(result.findings)
    assert all(isinstance(f, Finding) for f in result.findings)
    assert result.files_analyzed >= 1


def test_run_missing_target_returns_error(tmp_path):
    result = ApexDebugAgent(tmp_path).run(target="does_not_exist.py")
    assert result.errors
    assert result.findings == []


def test_min_severity_filters(tmp_path):
    _proj(tmp_path)
    # Nothing is above CRITICAL... requiring > CRITICAL drops all.
    agent = ApexDebugAgent(tmp_path, min_severity="critical")
    result = agent.run()
    assert all(f.severity >= Severity.CRITICAL for f in result.findings)


def test_categories_filter_non_security_empties(tmp_path):
    _proj(tmp_path)
    result = ApexDebugAgent(tmp_path).run(categories=["style"])
    assert result.findings == []


def test_summary_and_epistemic_claims(tmp_path):
    _proj(tmp_path)
    agent = ApexDebugAgent(tmp_path)
    assert "No analysis run yet" in agent.summary()
    agent.run()
    assert "Apex Debug Analysis Summary" in agent.summary()
    claims = agent.to_epistemic_claims()
    assert claims and claims[0]["type"] == "finding"
    assert "severity" in claims[0]


def test_analyze_alias_returns_findings(tmp_path):
    _proj(tmp_path)
    findings = ApexDebugAgent(tmp_path).analyze()
    assert isinstance(findings, list)


def test_result_helpers():
    r = AgentAnalysisResult(findings=[
        Finding("a", severity=Severity.HIGH, category="security"),
        Finding("b", severity=Severity.MEDIUM, category="style"),
    ])
    assert r.high_count == 1
    assert r.medium_count == 1
    assert len(r.by_category("security")) == 1
    assert len(r.by_severity(Severity.HIGH)) == 1
