from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.fractal_patch_generator import FractalPatch
from app.engine.rollback_journal import RollbackJournal


@dataclass
class ActionResult:
    """Result of an action executed by Hands."""

    action_type: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    changed_files: list[str] = field(default_factory=list)
    feedback_score: float = 0.0  # +1.0 success, -0.5 failure, 0.0 unknown
    patch_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "changed_files": self.changed_files,
            "feedback_score": self.feedback_score,
            "patch_id": self.patch_id,
        }


class ActionExecutor:
    """Action layer (Hands) — executes decisions in sandbox.

    Never modifies the original project directly.
    Always works in a temporary copy unless explicitly approved.

    Features:
    - Rollback journal integration
    - Patch tracking for potential rollback
    - Safety verification

    Usage:
        executor = ActionExecutor(project_root=".")
        result = executor.execute_patch(patch, run_tests=True)
        if result.success:
            executor.promote_to_original()
    """

    def __init__(self, project_root: str = ".", enable_rollback: bool = True, dry_run: bool = False) -> None:
        self.project_root = Path(project_root).resolve()
        self.sandbox_dir: Path | None = None
        self._last_changed_files: list[str] = []
        self._rollback_journal = (
            RollbackJournal(project_root=str(self.project_root))
            if enable_rollback
            else None
        )
        self._run_id: str = ""
        self._dry_run = dry_run

    def set_run_id(self, run_id: str) -> None:
        """Set the current run ID for tracking."""
        self._run_id = run_id

    def create_sandbox(self) -> Path:
        """Create a temporary copy of the project for safe execution."""
        tmp = Path(tempfile.mkdtemp(prefix="apex_sandbox_"))
        # Copy project files (excluding .git, node_modules, etc.)
        ignore = shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".venv", "node_modules", ".apex"
        )
        shutil.copytree(self.project_root, tmp / "project", ignore=ignore)
        self.sandbox_dir = tmp / "project"
        return self.sandbox_dir

    def execute_patch(
        self, patch: FractalPatch, run_tests: bool = False, dry_run: bool = False
    ) -> ActionResult:
        """Apply a patch in sandbox and optionally run tests.

        If dry_run is True, validates the patch without writing.
        """
        if not self.sandbox_dir:
            self.create_sandbox()

        sandbox_path = self.sandbox_dir / patch.file
        if not sandbox_path.exists():
            return ActionResult(
                action_type="patch", success=False, stderr="File not found in sandbox"
            )

        old_content = sandbox_path.read_text(encoding="utf-8")
        if patch.old_code not in old_content:
            return ActionResult(
                action_type="patch", success=False, stderr="old_code not found in file"
            )

        if dry_run:
            new_content = old_content.replace(patch.old_code, patch.new_code, 1)
            return ActionResult(
                action_type="patch",
                success=True,
                stdout=f"[dry-run] Would replace {len(patch.old_code)} bytes with {len(patch.new_code)} bytes in {patch.file}",
                changed_files=[str(patch.file)],
                feedback_score=0.0,
                patch_id="dry-run",
            )

        # Record old content for potential rollback
        patch_id = ""
        if self._rollback_journal:
            patch_id = self._rollback_journal.record_patch(
                file_path=str(patch.file),
                old_content=old_content,
                new_content=old_content.replace(patch.old_code, patch.new_code, 1),
                run_id=self._run_id,
                issue=patch.finding,
                action_type=patch.action,
            )

        # Apply patch
        new_content = old_content.replace(patch.old_code, patch.new_code, 1)
        sandbox_path.write_text(new_content, encoding="utf-8")
        patch.applied = True
        self._last_changed_files.append(str(patch.file))

        # Optionally run tests
        if run_tests:
            result = self._run_tests()
            result.patch_id = patch_id
            return result

        return ActionResult(
            action_type="patch",
            success=True,
            changed_files=self._last_changed_files.copy(),
            feedback_score=0.0,  # Applied but not tested
            patch_id=patch_id,
        )

    def _run_tests(self) -> ActionResult:
        """Run pytest in sandbox."""
        if not self.sandbox_dir:
            return ActionResult(action_type="test", success=False, stderr="No sandbox")

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "-q", "--tb=short"],
                cwd=str(self.sandbox_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            # pytest exit code 5 = no tests collected (acceptable)
            success = result.returncode in (0, 5)
            return ActionResult(
                action_type="test",
                success=success,
                stdout=result.stdout,
                stderr=result.stderr,
                changed_files=self._last_changed_files.copy(),
                feedback_score=1.0 if success else -0.5,
            )
        except Exception as exc:
            return ActionResult(
                action_type="test",
                success=False,
                stderr=str(exc),
                changed_files=self._last_changed_files.copy(),
                feedback_score=-0.5,
            )

    def promote_to_original(self) -> bool:
        """Copy sandbox changes back to original project."""
        if not self.sandbox_dir:
            return False
        for changed in self._last_changed_files:
            src = self.sandbox_dir / changed
            dst = self.project_root / changed
            if src.exists():
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

                # Mark patch as promoted in journal
                if self._rollback_journal:
                    for record in reversed(self._rollback_journal.records):
                        if record.file_path == changed and not record.promoted:
                            self._rollback_journal.mark_promoted(record.patch_id)
                            break
        return True

    def rollback_last(self) -> bool:
        """Rollback the last patch."""
        if self._rollback_journal:
            return self._rollback_journal.rollback_last()
        return False

    def rollback_all(self) -> int:
        """Rollback all non-reverted patches."""
        if self._rollback_journal:
            return self._rollback_journal.rollback_all()
        return 0

    def rollback_file(self, file_path: str) -> bool:
        """Rollback a specific file to its original content."""
        if self._rollback_journal:
            for record in reversed(self._rollback_journal.records):
                if record.file_path == file_path and not record.reverted:
                    return self._rollback_journal.rollback(record.patch_id)
        return False

    def get_patch_history(self) -> list[dict[str, Any]]:
        """Get patch history from journal."""
        if self._rollback_journal:
            return self._rollback_journal.get_patch_history()
        return []

    def cleanup(self) -> None:
        """Remove sandbox directory."""
        if self.sandbox_dir and self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir.parent, ignore_errors=True)
            self.sandbox_dir = None
            self._last_changed_files.clear()
