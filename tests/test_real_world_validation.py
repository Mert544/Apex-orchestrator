from __future__ import annotations

from pathlib import Path

from app.agents.skills import SecurityAgent, DocstringAgent, TestStubAgent
from app.validation.real_world_validator import RealWorldValidator


def test_flask_mini_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "flask_mini"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "os.system()",
        "pickle.loads",
        "missing_docstring",
        "bare_except",
    ]
    result = validator.assert_expected_issues(expected)

    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 5


def test_validator_surfaces_risks():
    root = Path(__file__).parent.parent / "examples" / "flask_mini"
    validator = RealWorldValidator(root)
    report = validator.run()
    assert report["functions_analyzed"] >= 5
    assert report["risk_count"] >= 5
    assert any("eval" in r.lower() for r in report["risks_found"])


def test_synthetic_shop_detects_hubs():
    root = Path(__file__).parent.parent / "examples" / "synthetic_shop"
    validator = RealWorldValidator(root)
    report = validator.run()
    assert report["total_files"] >= 5
    assert len(report["critical_untested"]) >= 1


def test_microservices_shop_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "microservices_shop"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "os.system()",
        "pickle.loads",
        "missing_docstring",
        "bare_except",
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 6


def test_legacy_bank_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "legacy_bank"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "exec()",
        "os.system()",
        "pickle.loads",
        "missing_docstring",
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 6


def test_ml_pipeline_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "ml_pipeline"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "exec()",
        "os.system()",
        "yaml.load",
        "missing_docstring",
        "bare_except",
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 6


def test_security_agent_finds_eval(tmp_path: Path):
    risky = tmp_path / "risky.py"
    risky.write_text("result = eval(user_input)\n")
    agent = SecurityAgent()
    result = agent.run(project_root=tmp_path)
    issues = [f.get("risk_type", "") for f in result.get("findings", [])]
    assert any("eval" in i.lower() for i in issues), f"SecurityAgent missed eval() — found: {issues}"


def test_security_agent_finds_os_system(tmp_path: Path):
    risky = tmp_path / "shell.py"
    risky.write_text("import os\nos.system('ls')\n")
    agent = SecurityAgent()
    result = agent.run(project_root=tmp_path)
    issues = [f.get("risk_type", "") for f in result.get("findings", [])]
    assert any("os.system" in i.lower() for i in issues), f"SecurityAgent missed os.system() — found: {issues}"


def test_docstring_agent_finds_missing_docstrings():
    root = Path(__file__).parent.parent / "examples" / "microservices_shop"
    agent = DocstringAgent()
    result = agent.run(project_root=root, patch=False)
    assert result["gaps_found"] > 0, f"DocstringAgent found no gaps in {root}"


def test_test_stub_agent_finds_coverage_gaps():
    root = Path(__file__).parent.parent / "examples" / "microservices_shop"
    agent = TestStubAgent()
    result = agent.run(project_root=root, generate=False)
    assert result["total_functions"] > result["tested_functions"], f"All functions are already tested in {root}"
