from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.learning import AgentLearning
from app.memory.cross_run_tracker import CrossRunTracker
from app.memory.findings_persistence import FindingsPersistence


@dataclass
class UnifiedClaim:
    claim: str
    branch: str = ""
    confidence: float = 0.0
    status: str = "open"
    first_seen_run: str = ""
    last_seen_run: str = ""
    run_count: int = 0
    source: str = ""  # "cross_run", "findings", "learning"
    metadata: dict[str, Any] = field(default_factory=dict)


class CentralMemoryBridge:
    """Unify CrossRunTracker, FindingsPersistence, and AgentLearning into a single interface.

    Usage:
        bridge = CentralMemoryBridge(project_root=".")
        bridge.record_findings("run-1", [{"claim": "eval() in auth.py"}])
        open_claims = bridge.get_open_claims()
        learning_tips = bridge.get_learning_tips("security")
    """

    def __init__(
        self,
        project_root: str,
        memory_dir: str = ".epistemic",
        backend: str = "json",
    ) -> None:
        self.cross_run = CrossRunTracker(project_root, memory_dir_name=memory_dir)
        self.findings = FindingsPersistence(project_root, memory_dir_name=memory_dir, backend=backend)
        self.learning = AgentLearning(project_root)

    def record_run(self, run_id: str, claims: list[dict[str, Any]], findings: list[dict[str, Any]] | None = None) -> None:
        """Record claims and findings from a run across all memory stores."""
        self.cross_run.record_run_claims(run_id, claims)
        # Also persist claims as findings for unified persistence queries
        self.findings.record_findings(run_id, claims)
        if findings:
            self.findings.record_findings(run_id, findings)

    def record_learning(self, agent: str, pattern: str, success: bool) -> None:
        """Record a learning result."""
        self.learning.record_result(agent, pattern, success)

    def get_open_claims(self) -> list[UnifiedClaim]:
        """Aggregate open claims from cross-run tracker and findings persistence."""
        unified: list[UnifiedClaim] = []
        seen: set[str] = set()

        for c in self.cross_run.get_open_claims():
            key = c["claim"].strip().lower()
            if key not in seen:
                seen.add(key)
                unified.append(UnifiedClaim(
                    claim=c["claim"],
                    branch=c.get("branch", ""),
                    confidence=c.get("confidence", 0.0),
                    status=c.get("status", "open"),
                    first_seen_run=c.get("first_seen_run", ""),
                    last_seen_run=c.get("last_seen_run", ""),
                    run_count=c.get("run_count", 1),
                    source="cross_run",
                    metadata=c.get("history", []),
                ))

        for c in self.findings.get_open_claims():
            key = c["claim"].strip().lower()
            if key not in seen:
                seen.add(key)
                unified.append(UnifiedClaim(
                    claim=c["claim"],
                    branch=c.get("branch", ""),
                    confidence=c.get("confidence", 0.0),
                    status=c.get("status", "open"),
                    first_seen_run=c.get("first_seen_run", ""),
                    last_seen_run=c.get("last_seen_run", ""),
                    run_count=c.get("run_count", 1),
                    source="findings",
                    metadata=c.get("history", []),
                ))

        return unified

    def get_persistent_claims(self, min_runs: int = 2) -> list[dict[str, Any]]:
        """Return claims seen across multiple runs."""
        return self.findings.get_persistent_findings(min_runs=min_runs)

    def get_learning_tips(self, agent: str) -> dict[str, Any]:
        """Return learning tips for an agent."""
        return self.learning.get_tips(agent)

    def build_recall_prompt(self) -> str:
        """Build a recall prompt from cross-run tracker."""
        return self.cross_run.build_recall_prompt()

    def close(self) -> None:
        self.findings.close()

    def __enter__(self) -> CentralMemoryBridge:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
