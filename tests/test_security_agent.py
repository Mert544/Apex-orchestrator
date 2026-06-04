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


def test_subprocess_call_with_list_is_not_flagged(tmp_path):
    # Real-world false positive: subprocess.call([...]) with list args is safe;
    # only shell=True is the injection risk. (Found running Apex on click.)
    from app.agents.skills import SecurityAgent
    (tmp_path / "m.py").write_text(
        "import subprocess\ndef edit(p):\n    subprocess.call(['vim', p])\n"
    )
    r = SecurityAgent().run(project_root=str(tmp_path))
    assert r["findings_count"] == 0


def test_subprocess_call_with_shell_true_is_flagged(tmp_path):
    from app.agents.skills import SecurityAgent
    (tmp_path / "m.py").write_text(
        "import subprocess\ndef run(c):\n    subprocess.call(c, shell=True)\n"
    )
    r = SecurityAgent().run(project_root=str(tmp_path))
    assert r["findings_count"] >= 1


def test_compile_nested_in_eval_is_not_double_counted(tmp_path):
    # eval(compile(...)) / exec(compile(...)) is ONE dynamic-execution risk, not
    # two. The nested compile must not produce a separate finding. (Found running
    # Apex on Flask, whose config/startup loaders use this idiom.)
    from app.agents.skills import SecurityAgent
    (tmp_path / "m.py").write_text(
        "def load(src, ns):\n    exec(compile(src, '<config>', 'exec'), ns)\n"
    )
    r = SecurityAgent().run(project_root=str(tmp_path))
    risks = [f["risk_type"] for f in r["findings"]]
    assert any("exec" in rt for rt in risks)
    assert not any("compile" in rt for rt in risks)
    assert r["findings_count"] == 1


def test_standalone_compile_is_still_flagged(tmp_path):
    # A compile() not wrapped by eval/exec is still its own finding (no regression).
    from app.agents.skills import SecurityAgent
    (tmp_path / "m.py").write_text("def build(src):\n    return compile(src, '<s>', 'exec')\n")
    r = SecurityAgent().run(project_root=str(tmp_path))
    assert any("compile" in f["risk_type"] for f in r["findings"])


def test_secret_inside_docstring_is_not_flagged(tmp_path):
    # A SECRET_KEY shown in a docstring example is documentation, not a real
    # hardcoded secret. (Found running Apex on Flask's config.py docstring.)
    from app.agents.skills import SecurityAgent
    (tmp_path / "m.py").write_text(
        'def configure():\n'
        '    """Set config like::\n'
        "\n"
        "        SECRET_KEY = 'development key'\n"
        '    """\n'
        "    return True\n"
    )
    r = SecurityAgent().run(project_root=str(tmp_path))
    assert not any(f["risk_type"] == "hardcoded_secret" for f in r["findings"])


def test_real_secret_assignment_is_still_flagged(tmp_path):
    # A genuine one-line assignment (lineno == end_lineno) is NOT in a docstring
    # and must still be flagged (no regression from the docstring filter).
    from app.agents.skills import SecurityAgent
    (tmp_path / "m.py").write_text("api_key = 'sk-live-abc123def456'\n")
    r = SecurityAgent().run(project_root=str(tmp_path))
    assert any(f["risk_type"] == "hardcoded_secret" for f in r["findings"])
