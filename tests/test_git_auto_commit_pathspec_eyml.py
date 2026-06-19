"""Auto-commit must commit ONLY the files Apex changed — never the whole index.

A red-team audit found a CRITICAL leak: GitAutoCommit.commit() ran a bare
``git commit`` with no pathspec, so it captured everything already staged in the
index. A user with pre-staged work (a secret, unrelated WIP) who runs
``apex maintain --mode autonomous --commit`` would have that content silently
swept into Apex's commit, mislabelled as the fix, and invisible in the
proof-of-fix artifact.

The fix commits with an explicit pathspec. These tests pin it: a pre-staged
unrelated file is NOT included in Apex's commit and stays staged (preserved) for
the user. Deterministic; uses a real throwaway git repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.engine.git_auto_commit import GitAutoCommit


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "apex_target.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("TOKEN = 'ok'\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_commit_excludes_prestaged_unrelated_file(repo: Path):
    # Apex is about to commit a change it made to apex_target.py...
    (repo / "apex_target.py").write_text("x = 2\n", encoding="utf-8")
    # ...but the user has separately staged a secret in another file.
    (repo / "secret.py").write_text("TOKEN = 'SECRET_LEAK_999'\n", encoding="utf-8")
    _git(repo, "add", "secret.py")

    result = GitAutoCommit(str(repo)).commit(["apex_target.py"], "modernize", "fix")
    assert result.success is True

    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    # Apex's commit contains ONLY its own file — never the staged secret.
    assert committed == ["apex_target.py"], committed
    assert "secret.py" not in committed
    # The secret is still staged (preserved for the user), and HEAD's secret.py
    # is the original — it was never committed by Apex.
    assert "secret.py" in _git(repo, "diff", "--cached", "--name-only")
    assert "SECRET_LEAK_999" not in _git(repo, "show", "HEAD:secret.py")


def test_clean_tree_commit_still_scopes_to_changed_files(repo: Path):
    (repo / "apex_target.py").write_text("x = 3\n", encoding="utf-8")
    result = GitAutoCommit(str(repo)).commit(["apex_target.py"], "modernize", "fix")
    assert result.success is True
    assert result.changed_files == ["apex_target.py"]
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["apex_target.py"]


def test_commit_refuses_when_changed_file_has_no_staged_change(repo: Path):
    # apex_target.py is unchanged; even if the user staged something else, Apex
    # has nothing of its OWN to commit and must not piggyback on the index.
    (repo / "secret.py").write_text("TOKEN = 'X'\n", encoding="utf-8")
    _git(repo, "add", "secret.py")
    result = GitAutoCommit(str(repo)).commit(["apex_target.py"], "modernize", "fix")
    assert result.success is False
    # No NEW commit was created — HEAD is still the initial commit, so Apex never
    # piggybacked the user's staged secret onto a commit of its own.
    assert _git(repo, "log", "--format=%s").splitlines() == ["init"]
