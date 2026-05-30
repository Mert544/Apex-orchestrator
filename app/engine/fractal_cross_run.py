from __future__ import annotations

from pathlib import Path
from typing import Any

from app.memory.cross_run_tracker import CrossRunTracker, ClaimStatus


class FractalCrossRunBridge:
    """Bridge fractal analysis with cross-run memory.

    Records fractal findings as tracked claims so Apex can ask
    'is this still true?' across multiple runs.

    Usage:
        bridge = FractalCrossRunBridge(project_root=".")
        bridge.record_findings(run_id="run-1", findings=[...])
        recall = bridge.build_recall_prompt()
    """

    def __init__(self, project_root: str | Path) -> None:
        self.tracker = CrossRunTracker(project_root)

    def record_findings(self, run_id: str, findings: list[dict[str, Any]]) -> None:
        """Convert fractal findings into tracked claims."""
        claims = []
        for f in findings:
            issue = f.get("issue") or f.get("risk_type", "unknown")
            file = f.get("file", "unknown")
            severity = f.get("severity", "info")
            confidence = 1.0 if severity == "critical" else 0.8 if severity == "high" else 0.5
            claims.append({
                "claim": f"{issue} in {file}",
                "branch": file,
                "confidence": confidence,
            })
        self.tracker.record_run_claims(run_id=run_id, claims=claims)

    def get_persistent_findings(self) -> list[dict[str, Any]]:
        """Get findings that have persisted across multiple runs."""
        open_claims = self.tracker.get_open_claims()
        # Sort by run_count to surface chronic issues
        open_claims.sort(key=lambda x: x.get("run_count", 1), reverse=True)
        return open_claims

    def build_recall_prompt(self) -> str:
        """Generate a recall prompt for the next run."""
        return self.tracker.build_recall_prompt()

    def mark_resolved(self, claim_text: str) -> None:
        """Manually mark a claim as resolved."""
        self.tracker.update_claim_status(claim_text, ClaimStatus.RESOLVED)
