from __future__ import annotations

from pathlib import Path

from app.agents.skills.test_stub_agent import TestStubAgent


def test_stub_agent_finds_gaps(tmp_path: Path):
    agent = TestStubAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    result = agent.run(project_root=str(tmp_path))
    assert result["gaps_found"] >= 1
    assert any(g["symbol_name"] == "add" for g in result["gaps"])


def test_stub_agent_generates_stubs(tmp_path: Path):
    agent = TestStubAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    result = agent.run(project_root=str(tmp_path), generate=True)
    assert len(result["stubs_generated"]) >= 1
    test_file = tmp_path / "tests" / "test_calc.py"
    assert test_file.exists()
    assert "def test_add()" in test_file.read_text()


def test_stub_agent_skips_private(tmp_path: Path):
    agent = TestStubAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def _internal():\n    pass\n")
    result = agent.run(project_root=str(tmp_path))
    assert result["gaps_found"] == 0


def test_stub_agent_ignores_worktree_copies(tmp_path: Path):
    agent = TestStubAgent()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "copy.py").write_text("def copy(): pass\n")

    sources = agent._discover_source_files(tmp_path)
    assert "app/real.py" in sources
    assert not any(".claude" in s for s in sources)
