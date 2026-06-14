from __future__ import annotations

from pathlib import Path

from app.agents.skills.dependency_agent import DependencyAgent


def test_skill_dependency_discovery_ignores_worktree_copies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "copy.py").write_text("def copy(): pass\n")

    files = DependencyAgent()._discover_files(tmp_path)
    assert "app/real.py" in files
    assert not any(".claude" in f for f in files)
