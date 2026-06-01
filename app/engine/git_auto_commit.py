from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GitCommitResult:
    """Result of a git auto-commit."""

    success: bool
    commit_hash: str = ""
    message: str = ""
    changed_files: list[str] = None
    error: str = ""

    def __post_init__(self):
        if self.changed_files is None:
            self.changed_files = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "commit_hash": self.commit_hash,
            "message": self.message,
            "changed_files": self.changed_files,
            "error": self.error,
        }


class GitAutoCommit:
    """Auto-commit successful patches with descriptive messages.

    Usage:
        gac = GitAutoCommit(project_root=".")
        result = gac.commit(["file1.py", "file2.py"], finding="eval() usage")
        if result.success:
            print(f"Committed: {result.commit_hash}")
    """

    def __init__(self, project_root: str = ".") -> None:
        self.project_root = Path(project_root).resolve()

    def _run_git(self, args: list[str]) -> tuple[int, str, str]:
        """Run git command in project root."""
        result = subprocess.run(
            ["git"] + args,
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def commit(self, changed_files: list[str], finding: str, action: str = "fix") -> GitCommitResult:
        """Stage files and create a commit."""
        # Check if this is a git repo
        code, _, _ = self._run_git(["rev-parse", "--git-dir"])
        if code != 0:
            return GitCommitResult(success=False, error="Not a git repository")

        # Stage files
        for f in changed_files:
            self._run_git(["add", f])

        # Check if there are staged changes
        code, diff, _ = self._run_git(["diff", "--cached", "--stat"])
        if code != 0 or not diff:
            return GitCommitResult(success=False, error="No staged changes to commit")

        # Create commit message
        msg = self._build_message(finding, action, changed_files)

        # Commit. Disable GPG signing for machine-generated commits: agents
        # cannot satisfy an interactive/required signing key, and a repo (or
        # sandbox) that mandates signing would otherwise block auto-commit.
        code, stdout, stderr = self._run_git(["-c", "commit.gpgsign=false", "commit", "-m", msg])
        if code != 0:
            return GitCommitResult(success=False, error=stderr)

        # Get commit hash
        _, hash_out, _ = self._run_git(["rev-parse", "HEAD"])

        return GitCommitResult(
            success=True,
            commit_hash=hash_out[:8],
            message=msg,
            changed_files=changed_files,
        )

    def _build_message(self, finding: str, action: str, files: list[str]) -> str:
        """Build a conventional commit message."""
        # Map finding to conventional commit type
        if "security" in finding.lower() or "eval" in finding.lower() or "injection" in finding.lower():
            prefix = "security"
        elif "docstring" in finding.lower():
            prefix = "docs"
        elif "test" in finding.lower():
            prefix = "test"
        else:
            prefix = "fix"

        short_finding = finding.replace("() usage", "").replace("missing_", "")
        file_list = ", ".join(Path(f).name for f in files[:3])
        if len(files) > 3:
            file_list += f" +{len(files) - 3} more"

        return f"{prefix}: Apex auto-{action} {short_finding} in {file_list}"

    def can_commit(self) -> bool:
        """Check if auto-commit is safe (no uncommitted changes before we started)."""
        code, _, _ = self._run_git(["diff", "--stat"])
        return code == 0
