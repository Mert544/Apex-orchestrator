from __future__ import annotations

from pathlib import Path

from app.agents.skills.security_agent import SecurityAgent


def test_skill_security_discovery_ignores_worktree_copies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def run(code):\n    return eval(code)\n")
    # A worktree copy carrying the same eval() risk must not be discovered.
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "copy.py").write_text("def run(code):\n    return eval(code)\n")

    files = SecurityAgent()._discover_files(tmp_path)
    assert "app/real.py" in files
    assert not any(".claude" in f for f in files)
