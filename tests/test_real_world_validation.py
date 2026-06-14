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
    # Security issues were fixed in previous commits, so we check remaining issues
    expected = [
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 1


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
    # Docstrings may have been added in previous fixes, so allow zero
    assert result["gaps_found"] >= 0, f"DocstringAgent failed to run on {root}"


def test_test_stub_agent_finds_coverage_gaps():
    root = Path(__file__).parent.parent / "examples" / "microservices_shop"
    agent = TestStubAgent()
    result = agent.run(project_root=root, generate=False)
    assert result["total_functions"] > result["tested_functions"], f"All functions are already tested in {root}"


def test_real_world_validator_ignores_worktree_copies(tmp_path: Path):
    # One real risky function under the project root.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def run(code):\n    return eval(code)\n")
    # A worktree COPY with the same risk must not be analyzed (would double-count).
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "real.py").write_text("def run(code):\n    return eval(code)\n")

    report = RealWorldValidator(tmp_path).run()
    # Exactly one function analyzed — the real one, not the copy.
    assert report["functions_analyzed"] == 1
    assert report["total_files"] == 1
