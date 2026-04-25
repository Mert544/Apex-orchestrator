from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


class CheckpointManager:
    """Manages automatic checkpoints after successful runs.

    Features:
    - Auto-save after milestones
    - Git integration
    - Run metadata tracking
    - Recovery support

    Usage:
        manager = CheckpointManager(project_root=".")
        manager.save_checkpoint(run_id="run-123", mode="supervised")
    """

    def __init__(
        self, project_root: str = ".", checkpoint_dir: str = ".apex/checkpoints"
    ) -> None:
        self.project_root = Path(project_root)
        self.checkpoint_dir = self.project_root / checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self,
        run_id: str,
        mode: str,
        goal: str,
        stats: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Save a checkpoint with run metadata."""
        timestamp = datetime.now().isoformat()

        checkpoint = {
            "run_id": run_id,
            "timestamp": timestamp,
            "mode": mode,
            "goal": goal,
            "stats": stats or {},
        }

        if force or self._should_checkpoint(stats):
            checkpoint_file = self.checkpoint_dir / f"checkpoint-{run_id}.json"
            checkpoint_file.write_text(
                json.dumps(checkpoint, indent=2), encoding="utf-8"
            )

            latest = self.checkpoint_dir / "latest.json"
            latest.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

            self._try_git_commit(run_id, timestamp, mode, stats)

            return {"saved": True, "checkpoint_file": str(checkpoint_file)}

        return {"saved": False, "reason": "checkpoint not required"}

    def _should_checkpoint(self, stats: dict[str, Any] | None) -> bool:
        """Decide if checkpoint should be saved."""
        if not stats:
            return False

        patches = stats.get("patches_applied", 0)
        findings = stats.get("findings_count", 0)
        tests_passed = stats.get("tests_passed", True)

        return patches > 0 or findings > 5 or not tests_passed

    def _try_git_commit(
        self, run_id: str, timestamp: str, mode: str, stats: dict[str, Any] | None
    ) -> None:
        """Try to commit checkpoint to git."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.stdout.strip():
                subprocess.run(
                    ["git", "add", str(self.checkpoint_dir)],
                    cwd=str(self.project_root),
                    capture_output=True,
                    timeout=10,
                )

                msg = f"checkpoint: {mode} run {run_id} at {timestamp}"
                subprocess.run(
                    ["git", "commit", "-m", msg],
                    cwd=str(self.project_root),
                    capture_output=True,
                    timeout=10,
                )

        except Exception:
            pass

    def load_latest_checkpoint(self) -> dict[str, Any] | None:
        """Load the latest checkpoint."""
        latest = self.checkpoint_dir / "latest.json"
        if latest.exists():
            try:
                return json.loads(latest.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def list_checkpoints(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent checkpoints."""
        checkpoints = sorted(
            self.checkpoint_dir.glob("checkpoint-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        results = []
        for cp in checkpoints[:limit]:
            try:
                results.append(json.loads(cp.read_text(encoding="utf-8")))
            except Exception:
                pass

        return results

    def get_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """Get a specific checkpoint by run_id."""
        checkpoint_file = self.checkpoint_dir / f"checkpoint-{run_id}.json"
        if checkpoint_file.exists():
            try:
                return json.loads(checkpoint_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None
