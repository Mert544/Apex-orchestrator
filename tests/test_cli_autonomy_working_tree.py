"""Branch coverage for app.cli_autonomy._working_tree_clean.

The helper gates auto-edit behind "is this a git repo with nothing uncommitted?"
The clean-status arm (the `git status --porcelain` call returning empty) was the
last uncovered branch in the module. These tests drive every arm deterministically
without touching the real repo:

  - a fresh repo with a committed, unmodified tree  -> True (the clean arm);
  - the same repo with an uncommitted change        -> False;
  - a plain directory that is not a git repo        -> False (rev-parse != "true");
  - a subprocess failure                             -> False (except arm).

Real git runs against an isolated tmp_path repo (no network, no wall-clock);
the non-repo and error arms are monkeypatched so they never depend on the host.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.cli_autonomy import _working_tree_clean


def _git(args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def _fresh_repo(tmp_path: Path) -> Path:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@example.com"], tmp_path)
    _git(["config", "user.name", "Tester"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "a.txt").write_text("hello\n")
    _git(["add", "a.txt"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    return tmp_path


def test_clean_committed_repo_is_clean(tmp_path):
    repo = _fresh_repo(tmp_path)
    assert _working_tree_clean(repo) is True


def test_uncommitted_change_is_not_clean(tmp_path):
    repo = _fresh_repo(tmp_path)
    (repo / "a.txt").write_text("changed\n")  # dirty the tree
    assert _working_tree_clean(repo) is False


def test_untracked_file_is_not_clean(tmp_path):
    repo = _fresh_repo(tmp_path)
    (repo / "new.txt").write_text("untracked\n")
    assert _working_tree_clean(repo) is False


def test_non_repo_directory_is_not_clean(tmp_path):
    # No `git init` -> rev-parse --is-inside-work-tree is non-zero / not "true".
    assert _working_tree_clean(tmp_path) is False


def test_subprocess_exception_is_not_clean(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", boom)
    assert _working_tree_clean(tmp_path) is False


def test_rev_parse_says_not_inside_worktree(tmp_path, monkeypatch):
    # rev-parse succeeds but reports we are NOT inside a work tree -> short-circuit.
    class _Res:
        returncode = 0
        stdout = "false\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Res())
    assert _working_tree_clean(tmp_path) is False
