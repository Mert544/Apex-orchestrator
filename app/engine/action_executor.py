from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.fractal_patch_generator import FractalPatch


@dataclass
class ActionResult:
    """Result of an action executed by Hands."""

    action_type: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    changed_files: list[str] = field(default_factory=list)
    feedback_score: float = 0.0  # +1.0 success, -0.5 failure, 0.0 unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "changed_files": self.changed_files,
            "feedback_score": self.feedback_score,
        }


class ActionExecutor:
    """Action layer (Hands) — executes decisions in sandbox.

    Never modifies the original project directly.
    Always works in a temporary copy unless explicitly approved.

    Usage:
        executor = ActionExecutor(project_root=".")
        result = executor.execute_patch(patch, run_tests=True)
        if result.success:
            executor.promote_to_original()
    """

    def __init__(self, project_root: str = ".") -> None:
        self.project_root = Path(project_root).resolve()
        self.sandbox_dir: Path | None = None
        self._last_changed_files: list[str] = []

    def create_sandbox(self) -> Path:
        """Create a temporary copy of the project for safe execution."""
        tmp = Path(tempfile.mkdtemp(prefix="apex_sandbox_"))
        # Copy project files (excluding .git, node_modules, etc.)
        ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "node_modules", ".apex")
        shutil.copytree(self.project_root, tmp / "project", ignore=ignore)
        self.sandbox_dir = tmp / "project"
        return self.sandbox_dir

    def execute_patch(self, patch: FractalPatch, run_tests: bool = False) -> ActionResult:
        """Apply a patch in sandbox and optionally run tests."""
        if not self.sandbox_dir:
            self.create_sandbox()

        sandbox_path = self.sandbox_dir / patch.file
        if not sandbox_path.exists():
            return ActionResult(action_type="patch", success=False, stderr="File not found in sandbox")

        content = sandbox_path.read_text(encoding="utf-8")
        if patch.old_code not in content:
            return ActionResult(action_type="patch", success=False, stderr="old_code not found in file")

        # Apply patch
        content = content.replace(patch.old_code, patch.new_code, 1)
        sandbox_path.write_text(content, encoding="utf-8")
        patch.applied = True
        self._last_changed_files.append(str(patch.file))

        # Optionally run tests
        if run_tests:
            return self._run_tests()

        return ActionResult(
            action_type="patch",
            success=True,
            changed_files=self._last_changed_files.copy(),
            feedback_score=0.0,  # Applied but not tested
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
        return True

    def cleanup(self) -> None:
        """Remove sandbox directory."""
        if self.sandbox_dir and self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir.parent, ignore_errors=True)
            self.sandbox_dir = None
            self._last_changed_files.clear()
