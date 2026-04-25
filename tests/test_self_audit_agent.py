from __future__ import annotations

from pathlib import Path

from app.agents.skills.self_audit_agent import SelfAuditAgent


def test_self_audit_finds_no_risks_in_clean_code(tmp_path: Path):
    agent = SelfAuditAgent()
    # Create a clean Python file
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("def hello():\n    '''Say hello.'''\n    return 'hello'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_clean.py").write_text("from app.clean import hello\n")
    result = agent.run(project_root=str(tmp_path))
    assert result["agent"] == "self_audit"
    assert result["findings"] == []
    assert result["missing_docstrings_count"] == 0


def test_self_audit_finds_eval(tmp_path: Path):
    agent = SelfAuditAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "risky.py").write_text("def run(code):\n    return eval(code)\n")
    result = agent.run(project_root=str(tmp_path))
    assert len(result["findings"]) == 1
    assert result["findings"][0]["risk"] == "eval()"


def test_self_audit_finds_missing_docstrings(tmp_path: Path):
    agent = SelfAuditAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "nodoc.py").write_text("class Foo:\n    def bar(self):\n        pass\n")
    result = agent.run(project_root=str(tmp_path))
    assert result["missing_docstrings_count"] >= 2
    assert any("Foo" in s["name"] for s in result["missing_docstrings_sample"])


def test_self_audit_finds_long_functions(tmp_path: Path):
    agent = SelfAuditAgent()
    (tmp_path / "app").mkdir()
    lines = ["def long_func():"]
    lines.extend([f"    x = {i}" for i in range(60)])
    lines.append("    return x")
    (tmp_path / "app" / "long.py").write_text("\n".join(lines))
    result = agent.run(project_root=str(tmp_path))
    assert result["long_functions_count"] >= 1
    assert result["long_functions_sample"][0]["name"] == "long_func"


def test_self_audit_finds_todos(tmp_path: Path):
    agent = SelfAuditAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "todo.py").write_text("def func():\n    # TODO: fix this\n    pass\n")
    result = agent.run(project_root=str(tmp_path))
    assert result["todos_count"] >= 1
    assert any("TODO" in t["text"] for t in result["todos_sample"])


def test_self_audit_coverage_gap(tmp_path: Path):
    agent = SelfAuditAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "module_a.py").write_text("def a(): pass\n")
    (tmp_path / "app" / "module_b.py").write_text("def b(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("from app.module_a import a\n")
    result = agent.run(project_root=str(tmp_path))
    cov = result["coverage_gap"]
    assert "module_a" in cov["tested_modules"]
    assert "module_b" in cov["untested_modules"]
