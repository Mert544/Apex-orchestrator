"""Self-Healing Agent Skill — Automatically fixes common code issues.

Integrates with Apex Debug findings to apply safe transformations,
then verifies fixes with tests.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HealingResult:
    """Result of a self-healing operation."""

    success: bool
    files_modified: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    test_passed: bool = False
    message: str = ""


class SelfHealingAgent:
    """Agent that automatically fixes code issues detected by Apex Debug.

    Usage:
        healer = SelfHealingAgent(project_root="/path/to/code")
        result = healer.heal()
        if result.success:
            print(f"Fixed {len(result.files_modified)} files")
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def heal(self, dry_run: bool = True) -> HealingResult:
        """Run Apex Debug autofix on the project.

        Args:
            dry_run: If True, only preview changes without applying

        Returns:
            HealingResult with details
        """
        # Step 1: Run Apex Debug with autofix
        cmd = [
            "python", "-m", "apex_debug.cli.app",
            "analyze", str(self.project_root),
            "--min-severity", "info",
        ]
        if dry_run:
            cmd.append("--fix-dry-run")
        else:
            cmd.append("--fix")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=120,
            )
        except Exception as e:
            return HealingResult(
                success=False,
                message=f"Apex Debug failed: {e}",
            )

        # Step 2: Parse which files would be/have been modified
        modified: list[str] = []
        for line in result.stdout.splitlines():
            if "Would fix" in line or "Fixed" in line:
                # Extract filename from lines like "  Fixed 3 issue(s) in main.py"
                parts = line.split(" in ")
                if len(parts) >= 2:
                    fname = parts[-1].strip()
                    modified.append(fname)

        # Step 3: If not dry_run, run tests to verify fixes
        test_passed = False
        if not dry_run and modified:
            test_passed = self._run_tests()

        return HealingResult(
            success=True,
            files_modified=modified,
            test_passed=test_passed,
            message=result.stdout if result.stdout else "No changes needed",
        )

    def _run_tests(self) -> bool:
        """Run project tests to verify fixes didn't break anything.

        Returns:
            True if tests pass, False otherwise
        """
        test_commands = [
            ["pytest", "-x", "-q"],
            ["python", "-m", "pytest", "-x", "-q"],
            ["python", "setup.py", "test"],
        ]

        for cmd in test_commands:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(self.project_root),
                    timeout=180,
                )
                if result.returncode == 0:
                    return True
            except Exception:
                continue

        return False

    def rollback(self, backup_dir: str | Path) -> bool:
        """Rollback changes using git restore or backup files.

        Args:
            backup_dir: Directory containing backups

        Returns:
            True if rollback succeeded
        """
        try:
            subprocess.run(
                ["git", "restore", "."],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=30,
            )
            return True
        except Exception:
            return False
