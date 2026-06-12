"""blame_age_days: real behavior — ages are HEAD-anchored and deterministic."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.tools.git_history import blame_age_days


def _repo(tmp_path: Path) -> None:
    def _git(*args: str, date: str = "") -> None:
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "old.py").write_text("OLD = 1\n")
    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "old",
         date="2024-01-01T12:00:00 +0000")
    (tmp_path / "app" / "new.py").write_text("NEW = 1\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "new",
         date="2026-01-01T12:00:00 +0000")


def test_age_is_anchored_to_head_not_wall_clock(tmp_path):
    _repo(tmp_path)
    # The old line was committed ~2 years before HEAD: the age must reflect
    # that delta exactly, regardless of when the test runs.
    age = blame_age_days(tmp_path, "app/old.py", 1)
    assert age is not None and 725 <= age <= 735  # 2024-01-01 -> 2026-01-01

    # A line born in the HEAD commit is 0 days old by construction.
    assert blame_age_days(tmp_path, "app/new.py", 1) == 0


def test_non_git_directory_yields_none(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.py").write_text("X = 1\n")
    assert blame_age_days(tmp_path, "app/x.py", 1) is None


def test_unknown_file_and_bad_line_yield_none(tmp_path):
    _repo(tmp_path)
    assert blame_age_days(tmp_path, "app/ghost.py", 1) is None   # not in git
    assert blame_age_days(tmp_path, "app/old.py", 999) is None   # no such line
