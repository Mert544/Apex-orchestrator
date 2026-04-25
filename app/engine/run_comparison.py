from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class RunSnapshot:
    """Snapshot of a single run for comparison."""

    run_id: str
    timestamp: str
    mode: str
    goal: str
    findings_count: int
    patches_applied: int
    patches_blocked: int
    tests_passed: bool
    duration_seconds: float
    safety_gates_passed: bool
    autonomy_level: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "goal": self.goal,
            "findings_count": self.findings_count,
            "patches_applied": self.patches_applied,
            "patches_blocked": self.patches_blocked,
            "tests_passed": self.tests_passed,
            "duration_seconds": self.duration_seconds,
            "safety_gates_passed": self.safety_gates_passed,
            "autonomy_level": self.autonomy_level,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class RunComparison:
    """Compare runs to track progress and identify trends.

    Usage:
        comparison = RunComparison(project_root=".")
        comparison.record_run(...)
        report = comparison.compare_recent(n=5)
    """

    def __init__(self, project_root: str = ".", log_dir: str = ".apex") -> None:
        self.project_root = Path(project_root)
        self.log_path = Path(log_dir) / "run_history.json"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs: list[RunSnapshot] = []
        self._load()

    def _load(self) -> None:
        if self.log_path.exists():
            try:
                data = json.loads(self.log_path.read_text(encoding="utf-8"))
                self.runs = [RunSnapshot(**r) for r in data.get("runs", [])]
            except Exception:
                self.runs = []

    def _save(self) -> None:
        self.log_path.write_text(
            json.dumps(
                {"runs": [r.to_dict() for r in self.runs], "version": "2.0"},
                indent=2,
            ),
            encoding="utf-8",
        )

    def record_run(
        self,
        run_id: str,
        mode: str,
        goal: str,
        findings_count: int = 0,
        patches_applied: int = 0,
        patches_blocked: int = 0,
        tests_passed: bool = True,
        duration_seconds: float = 0.0,
        safety_gates_passed: bool = True,
        autonomy_level: str = "report",
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Record a run snapshot."""
        snapshot = RunSnapshot(
            run_id=run_id,
            timestamp=datetime.now().isoformat(),
            mode=mode,
            goal=goal,
            findings_count=findings_count,
            patches_applied=patches_applied,
            patches_blocked=patches_blocked,
            tests_passed=tests_passed,
            duration_seconds=duration_seconds,
            safety_gates_passed=safety_gates_passed,
            autonomy_level=autonomy_level,
            errors=errors or [],
            warnings=warnings or [],
        )

        self.runs.append(snapshot)

        if len(self.runs) > 100:
            self.runs = self.runs[-100:]

        self._save()

    def compare_recent(self, n: int = 5) -> dict[str, Any]:
        """Compare recent n runs."""
        recent = self.runs[-n:] if len(self.runs) >= n else self.runs

        if not recent:
            return {"error": "No runs to compare"}

        avg_duration = sum(r.duration_seconds for r in recent) / len(recent)
        total_patches = sum(r.patches_applied for r in recent)
        total_blocked = sum(r.patches_blocked for r in recent)
        pass_rate = sum(1 for r in recent if r.tests_passed) / len(recent)
        gate_pass_rate = sum(1 for r in recent if r.safety_gates_passed) / len(recent)

        return {
            "runs_compared": len(recent),
            "date_range": {
                "start": recent[0].timestamp,
                "end": recent[-1].timestamp,
            },
            "summary": {
                "avg_duration_seconds": round(avg_duration, 2),
                "total_patches_applied": total_patches,
                "total_patches_blocked": total_blocked,
                "test_pass_rate": round(pass_rate * 100, 1),
                "safety_gate_pass_rate": round(gate_pass_rate * 100, 1),
            },
            "trend": self._calculate_trend(recent),
            "runs": [r.to_dict() for r in recent],
        }

    def _calculate_trend(self, runs: list[RunSnapshot]) -> dict[str, str]:
        """Calculate trend direction for key metrics."""
        if len(runs) < 2:
            return {"patches": "insufficient_data", "tests": "insufficient_data"}

        first_half = runs[: len(runs) // 2]
        second_half = runs[len(runs) // 2 :]

        first_patches = sum(r.patches_applied for r in first_half)
        second_patches = sum(r.patches_applied for r in second_half)

        first_tests = sum(1 for r in first_half if r.tests_passed)
        second_tests = sum(1 for r in second_half if r.tests_passed)

        return {
            "patches": "increasing"
            if second_patches > first_patches
            else "stable"
            if second_patches == first_patches
            else "decreasing",
            "tests": "improving"
            if second_tests > first_tests
            else "stable"
            if second_tests == first_tests
            else "declining",
        }

    def get_last_run(self) -> RunSnapshot | None:
        """Get the most recent run."""
        return self.runs[-1] if self.runs else None

    def get_statistics(self) -> dict[str, Any]:
        """Get overall statistics."""
        if not self.runs:
            return {"total_runs": 0}

        modes = {}
        for r in self.runs:
            modes[r.mode] = modes.get(r.mode, 0) + 1

        return {
            "total_runs": len(self.runs),
            "modes": modes,
            "first_run": self.runs[0].timestamp if self.runs else None,
            "last_run": self.runs[-1].timestamp if self.runs else None,
            "avg_duration": round(
                sum(r.duration_seconds for r in self.runs) / len(self.runs), 2
            ),
        }
