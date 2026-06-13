"""Tests for git_rule_miner.mine_git_pairs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.engine.git_rule_miner import mine_git_pairs


def _git(cwd, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args],
                   cwd=str(cwd), check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def test_empty_history_returns_empty(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    result = mine_git_pairs(str(tmp_path), max_commits=10)
    # The initial commit has no parent — the diff against sha^ fails, so no pair.
    assert result == []


def test_single_expression_change_is_mined(tmp_path):
    _init_repo(tmp_path)
    # Use a return statement — expression is unwrapped from the statement context.
    (tmp_path / "a.py").write_text("def f(xs):\n    return len(xs) == 0\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "a.py").write_text("def f(xs):\n    return not xs\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "simplify")
    pairs = mine_git_pairs(str(tmp_path), max_commits=10)
    assert len(pairs) == 1
    before, after = pairs[0]
    assert "len" in before   # extracted: "len(xs) == 0"
    assert "not" in after    # extracted: "not xs"


def test_assignment_expression_change_is_mined(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = len(xs) == 0\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "a.py").write_text("x = not xs\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "simplify")
    pairs = mine_git_pairs(str(tmp_path), max_commits=10)
    assert len(pairs) == 1
    before, after = pairs[0]
    assert before == "len(xs) == 0"
    assert after == "not xs"


def test_multi_line_change_is_skipped(tmp_path):
    """A commit that adds/removes more than one line is not a single-expression fix."""
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("def f(x):\n    return x + 1\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "a.py").write_text("def f(x):\n    x = x * 2\n    return x\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "two-line change")
    pairs = mine_git_pairs(str(tmp_path), max_commits=10)
    assert pairs == []


def test_non_expression_statement_is_skipped(tmp_path):
    """An import statement or class def cannot be reduced to an expression — skip."""
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("import os\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "a.py").write_text("import sys\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "change import")
    pairs = mine_git_pairs(str(tmp_path), max_commits=10)
    assert pairs == []


def test_identical_lines_are_skipped(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("# comment\nlen(x)\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    # Whitespace-only change — stripped copies are equal.
    (tmp_path / "a.py").write_text("#comment\nlen(x)\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "strip comment")
    pairs = mine_git_pairs(str(tmp_path), max_commits=10)
    assert pairs == []


def test_non_git_dir_returns_empty(tmp_path):
    """No git repo → empty list, no exception."""
    result = mine_git_pairs(str(tmp_path), max_commits=5)
    assert result == []
