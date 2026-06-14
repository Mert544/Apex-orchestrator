from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.engine.git_auto_commit import GitAutoCommit, GitCommitResult


def _init_repo(root: Path) -> None:
    """Create a real, deterministic git repo with one committed file."""
    def _git(*args: str) -> None:
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2024-01-01T12:00:00 +0000"
        subprocess.run(["git", *args], cwd=root, capture_output=True, env=env)

    (root / "main.py").write_text("x = 1\n")
    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "initial")


class TestGitAutoCommit:
    def test_not_git_repo(self, tmp_path: Path):
        gac = GitAutoCommit(str(tmp_path))
        result = gac.commit(["file.py"], finding="eval() usage")
        assert result.success is False
        assert "Not a git repository" in result.error

    def test_build_message_security(self):
        gac = GitAutoCommit()
        msg = gac._build_message("eval() usage", "fix", ["auth.py"])
        assert msg.startswith("security:")
        assert "eval" in msg
        assert "auth.py" in msg

    def test_build_message_docs(self):
        gac = GitAutoCommit()
        msg = gac._build_message("missing_docstring", "fix", ["utils.py"])
        assert msg.startswith("docs:")
        assert "docstring" in msg

    def test_build_message_test(self):
        gac = GitAutoCommit()
        msg = gac._build_message("missing_test", "generate", ["test_main.py"])
        assert msg.startswith("test:")
        assert "test" in msg

    def test_build_message_default_prefix(self):
        # A finding that maps to none of the special prefixes falls back to "fix".
        gac = GitAutoCommit()
        msg = gac._build_message("style cleanup", "fix", ["mod.py"])
        assert msg.startswith("fix:")
        assert "mod.py" in msg

    def test_build_message_truncates_file_list(self):
        # More than three files collapses the tail into a "+N more" suffix.
        gac = GitAutoCommit()
        files = ["a.py", "b.py", "c.py", "d.py", "e.py"]
        msg = gac._build_message("cleanup", "fix", files)
        assert "a.py, b.py, c.py" in msg
        assert "+2 more" in msg
        assert "d.py" not in msg


class TestGitAutoCommitRealRepo:
    def test_commit_succeeds_and_returns_hash(self, tmp_path: Path):
        _init_repo(tmp_path)
        # Modify a tracked file so there is something to stage and commit.
        (tmp_path / "main.py").write_text("x = ast.literal_eval(y)\n")
        gac = GitAutoCommit(str(tmp_path))
        result = gac.commit(["main.py"], finding="eval() usage", action="fix")

        assert result.success is True
        assert result.commit_hash  # an 8-char short hash
        assert len(result.commit_hash) == 8
        assert result.changed_files == ["main.py"]
        assert result.message.startswith("security:")
        # The commit really landed: HEAD subject matches the built message.
        head_subject = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=tmp_path, capture_output=True, text=True,
        ).stdout.strip()
        assert head_subject == result.message

    def test_commit_with_no_staged_changes_fails(self, tmp_path: Path):
        _init_repo(tmp_path)
        # Nothing was modified, so staging produces an empty diff.
        gac = GitAutoCommit(str(tmp_path))
        result = gac.commit(["main.py"], finding="eval() usage")
        assert result.success is False
        assert "No staged changes" in result.error

    def test_commit_failure_returns_stderr(self, tmp_path: Path, monkeypatch):
        _init_repo(tmp_path)
        (tmp_path / "main.py").write_text("x = 2\n")
        # Force git to reject the commit by making no identity available: clear
        # the per-repo config and any inherited global/system identity. With a
        # staged diff but no committer, `git commit` exits non-zero and the
        # error path surfaces git's stderr verbatim.
        subprocess.run(["git", "config", "--unset", "user.email"],
                       cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "--unset", "user.name"],
                       cwd=tmp_path, capture_output=True)
        monkeypatch.setenv("GIT_AUTHOR_NAME", "")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no_global"))
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "no_system"))
        monkeypatch.setenv("EMAIL", "")
        gac = GitAutoCommit(str(tmp_path))
        result = gac.commit(["main.py"], finding="cleanup")
        assert result.success is False
        # We never produced a commit hash on the failure path.
        assert result.commit_hash == ""
        assert result.error  # git's complaint about identity / commit failure

    def test_can_commit_true_in_clean_repo(self, tmp_path: Path):
        _init_repo(tmp_path)
        gac = GitAutoCommit(str(tmp_path))
        assert gac.can_commit() is True

    def test_to_dict_round_trips_fields(self):
        result = GitCommitResult(
            success=True, commit_hash="abc12345", message="fix: x",
            changed_files=["a.py"], error="",
        )
        d = result.to_dict()
        assert d == {
            "success": True,
            "commit_hash": "abc12345",
            "message": "fix: x",
            "changed_files": ["a.py"],
            "error": "",
        }

    def test_result_default_changed_files_is_empty_list(self):
        # __post_init__ normalizes a missing changed_files to [].
        result = GitCommitResult(success=False, error="boom")
        assert result.changed_files == []
