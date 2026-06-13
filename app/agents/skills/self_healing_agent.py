"""Self-Healing Agent Skill — auto-fix common issues with Apex's own engines.

Uses Apex's Idea Permutation Engine + IdeaActionBridge to apply deterministic,
test-verified fixes (with automatic rollback), then reports what changed. No
external dependency — fully in-process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess


@dataclass
class HealingResult:
    """Result of a self-healing operation."""

    success: bool
    files_modified: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    test_passed: bool = False
    message: str = ""


class SelfHealingAgent:
    """Automatically fix code issues using Apex's verified-apply pipeline.

    Usage:
        healer = SelfHealingAgent(project_root="/path/to/code")
        result = healer.heal(dry_run=True)
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def heal(self, dry_run: bool = True, max_apply: int = 10) -> HealingResult:
        """Generate fixes and (unless dry_run) apply them, verified with tests.

        Args:
            dry_run: If True, only report what would change (nothing applied).
            max_apply: Cap on the number of fixes to apply.
        """
        from app.engine.idea_action_bridge import IdeaActionBridge
        from app.engine.idea_permutation import IdeaPermutationEngine

        try:
            report = IdeaPermutationEngine(
                {"max_total_ideas": 30, "max_idea_depth": 1, "breadth": 4},
                str(self.project_root),
            ).run()
        except Exception as exc:
            return HealingResult(success=False, message=f"Analysis failed: {exc}")

        bridge = IdeaActionBridge()
        plan = bridge.plan_tree(report, project_root=str(self.project_root))

        if dry_run:
            preview = bridge.dry_run_plan(plan, str(self.project_root))
            would = [p for p in preview["results"] if p.get("applicable")]
            files = sorted({f for p in would for f in (p.get("files") or [])})
            return HealingResult(
                success=True,
                files_modified=files,
                message=f"{len(would)} fixes would be applied (dry run).",
            )

        # Apply, test-verified with automatic rollback per step.
        summary = bridge.apply_plan(
            plan, str(self.project_root), mode="supervised",
            verify=True, max_apply=max_apply,
        )
        modified = sorted({
            f for r in summary["results"] if r.get("applied")
            for f in (r.get("changed_files") or [])
        })
        return HealingResult(
            success=True,
            files_modified=modified,
            test_passed=summary["rolled_back"] == 0 and summary["applied"] > 0,
            message=(
                f"applied {summary['applied']}, rolled back "
                f"{summary['rolled_back']}, blocked {summary['blocked']}"
            ),
        )

    def _run_tests(self) -> bool:
        """Run the project's tests; True if they pass."""
        from app.skills.execution.run_tests import RunTestsSkill

        try:
            return RunTestsSkill().run(str(self.project_root)).ok
        except Exception:
            return False

    def rollback(self, backup_dir: str | Path | None = None) -> bool:
        """Rollback uncommitted changes via git restore."""
        try:
            subprocess.run(
                ["git", "restore", "."],
                capture_output=True, text=True,
                cwd=str(self.project_root), timeout=30,
            )
            return True
        except Exception:
            return False
