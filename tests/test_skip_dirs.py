"""Tests for the canonical tree-walk exclusion set."""

from __future__ import annotations

from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS, is_skipped, iter_source_files


def test_claude_worktrees_are_skipped():
    # The omission that bit Apex three times: agent worktrees under .claude/.
    assert ".claude" in SKIPPED_DIRS
    assert is_skipped(".claude/worktrees/agent-1/app/engine/foo.py")
    assert is_skipped(Path("x/.claude/y/test_foo.py"))


def test_real_source_is_kept():
    assert not is_skipped("app/engine/foo.py")
    assert not is_skipped("tests/test_foo.py")
    assert not is_skipped(Path("scripts/verify.py"))


def test_caches_venvs_and_build_output_skipped():
    for d in (".git", "__pycache__", ".apex", ".epistemic",
              ".venv", "venv", "node_modules", "dist", "build"):
        assert is_skipped(f"{d}/x.py"), d
        assert d in SKIPPED_DIRS


def test_skip_is_a_whole_component_match_not_substring():
    # A file whose NAME merely contains a skipped token is not a directory match.
    assert not is_skipped("app/buildings.py")    # 'build' is a substring, not a part
    assert not is_skipped("app/distance.py")     # 'dist' is a substring, not a part
    assert not is_skipped("app/venv_helper.py")  # 'venv' is a substring, not a part


def test_iter_source_files_excludes_worktrees(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
    wt = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    wt.mkdir(parents=True)
    (wt / "copy.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "c.py").write_text("x = 1\n", encoding="utf-8")

    found = [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)]
    assert found == ["app/real.py"]  # sorted, worktree + cache excluded


def test_iter_source_files_is_sorted_and_deterministic(tmp_path):
    (tmp_path / "app").mkdir()
    for name in ("c.py", "a.py", "b.py"):
        (tmp_path / "app" / name).write_text("x = 1\n", encoding="utf-8")
    a = [p.name for p in iter_source_files(tmp_path)]
    b = [p.name for p in iter_source_files(tmp_path)]
    assert a == b == ["a.py", "b.py", "c.py"]
