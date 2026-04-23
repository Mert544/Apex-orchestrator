from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MergeResult:
    success: bool = False
    commit_hash: str = ""
    branch: str = ""
    errors: list[str] = field(default_factory=list)


class AutoMerger:
    """Automatically commit and merge successful patches.

    Stages changes, creates a commit, and optionally pushes to remote.
    Safe by default: commits locally but does not push unless configured.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()

    def _run_git(self, *args: str) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def commit_patches(
        self,
        changed_files: list[str],
        message: str = "Apex Orchestrator: apply semantic patches",
        branch: str | None = None,
    ) -> MergeResult:
        result = MergeResult()

        if branch:
            rc, _, err = self._run_git("checkout", "-b", branch)
            if rc != 0 and "already exists" not in err.lower():
                result.errors.append(f"Failed to create branch: {err.strip()}")
                return result
            rc, _, err = self._run_git("checkout", branch)
            if rc != 0:
                result.errors.append(f"Failed to checkout branch: {err.strip()}")
                return result
            result.branch = branch

        for f in changed_files:
            rc, _, err = self._run_git("add", f)
            if rc != 0:
                result.errors.append(f"Failed to stage {f}: {err.strip()}")

        rc, out, err = self._run_git("commit", "-m", message)
        if rc != 0:
            if "nothing to commit" in err.lower() or "nothing to commit" in out.lower():
                result.errors.append("No changes to commit.")
            else:
                result.errors.append(f"Commit failed: {err.strip()}")
            return result

        result.success = True
        hash_rc, hash_out, _ = self._run_git("rev-parse", "HEAD")
        if hash_rc == 0:
            result.commit_hash = hash_out.strip()

        return result

    def push(self, remote: str = "origin", branch: str = "") -> tuple[bool, str]:
        if not branch:
            _, out, _ = self._run_git("branch", "--show-current")
            branch = out.strip()
        rc, _, err = self._run_git("push", remote, branch)
        return rc == 0, err.strip()
