from pathlib import Path

from examples.helper_agents.security_agent import SecurityAgent


def _write(root: Path, rel: str, content: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(content, encoding="utf-8")


def test_security_agent_detects_eval_and_os_system(tmp_path: Path):
    _write(
        tmp_path,
        "app/main.py",
        "import os\n\ndef risky():\n    os.system('ls')\n    config = eval('{}')\n",
    )
    agent = SecurityAgent(tmp_path)
    report = agent.scan()

    findings = report.findings
    risk_types = {f.risk_type for f in findings}

    assert "os.system() shell injection" in risk_types
    assert "eval() usage" in risk_types
    assert report.scanned_files >= 1
    assert report.risk_score > 0


def test_security_agent_detects_hardcoded_secret(tmp_path: Path):
    _write(
        tmp_path,
        "config.py",
        "API_KEY = 'sk-live-abc123'\nDATABASE_URL = 'postgresql://user:pass@localhost/db'\n",
    )
    agent = SecurityAgent(tmp_path)
    report = agent.scan()

    risk_types = {f.risk_type for f in report.findings}
    assert "hardcoded_secret" in risk_types or "hardcoded_connection" in risk_types


def test_security_agent_detects_bare_except(tmp_path: Path):
    _write(
        tmp_path,
        "app/utils.py",
        "def helper():\n    try:\n        pass\n    except:\n        pass\n",
    )
    agent = SecurityAgent(tmp_path)
    report = agent.scan()

    assert any(f.risk_type == "bare_except" for f in report.findings)


def test_security_agent_skips_non_python_files(tmp_path: Path):
    _write(tmp_path, "README.md", "# Project\n")
    agent = SecurityAgent(tmp_path)
    report = agent.scan()

    assert report.scanned_files == 0


def test_security_agent_empty_project(tmp_path: Path):
    agent = SecurityAgent(tmp_path)
    report = agent.scan()
    assert report.findings == []
    assert report.risk_score == 0.0
