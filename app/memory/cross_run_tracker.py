from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ClaimStatus(Enum):
    OPEN = "open"
    STILL_OPEN = "still_open"
    POTENTIALLY_RESOLVED = "potentially_resolved"
    RESOLVED = "resolved"
    WORSENED = "worsened"


@dataclass
class TrackedClaim:
    claim: str
    branch: str
    confidence: float
    status: ClaimStatus
    first_seen_run: str
    last_seen_run: str
    run_count: int
    history: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "branch": self.branch,
            "confidence": self.confidence,
            "status": self.status.value,
            "first_seen_run": self.first_seen_run,
            "last_seen_run": self.last_seen_run,
            "run_count": self.run_count,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackedClaim":
        return cls(
            claim=data["claim"],
            branch=data.get("branch", ""),
            confidence=data.get("confidence", 0.0),
            status=ClaimStatus(data.get("status", "open")),
            first_seen_run=data.get("first_seen_run", ""),
            last_seen_run=data.get("last_seen_run", ""),
            run_count=data.get("run_count", 1),
            history=data.get("history", []),
        )


class CrossRunTracker:
    """Track claims across multiple runs, detect resolution, worsening, or persistence.

    This enables the agent to 'remember' what it found before and ask
    'is this still true?' on subsequent runs.
    """

    MAX_CLAIMS = 50

    def __init__(self, project_root: str | Path, memory_dir_name: str = ".epistemic") -> None:
        self.project_root = Path(project_root)
        self.memory_dir = self.project_root / memory_dir_name
        self.memory_file = self.memory_dir / "cross_run_tracker.json"

    def load_state(self) -> dict[str, Any]:
        if not self.memory_file.exists():
            return {"schema_version": 1, "claim_tracker": [], "runs": []}
        try:
            raw = json.loads(self.memory_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {"schema_version": 1, "claim_tracker": [], "runs": []}

    def save_state(self, state: dict[str, Any]) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def record_run_claims(self, run_id: str, claims: list[dict[str, Any]]) -> None:
        """Record claims from a new run and update statuses of existing claims."""
        state = self.load_state()
        tracker: list[dict[str, Any]] = list(state.get("claim_tracker", []))
        run_claims_set = {self._normalize(c["claim"]) for c in claims}

        # Update existing claims
        for tc in tracker:
            norm = self._normalize(tc["claim"])
            if norm in run_claims_set:
                # Claim still present
                if tc["status"] == ClaimStatus.OPEN.value:
                    tc["status"] = ClaimStatus.STILL_OPEN.value
                tc["last_seen_run"] = run_id
                tc["run_count"] = tc.get("run_count", 1) + 1
                tc["history"].append({"run_id": run_id, "confidence": self._find_confidence(claims, norm)})
            else:
                # Claim no longer present
                if tc["status"] in (ClaimStatus.OPEN.value, ClaimStatus.STILL_OPEN.value):
                    tc["status"] = ClaimStatus.POTENTIALLY_RESOLVED.value
                tc["history"].append({"run_id": run_id, "status_change": "absent"})

        # Add new claims
        existing_norms = {self._normalize(tc["claim"]) for tc in tracker}
        for c in claims:
            norm = self._normalize(c["claim"])
            if norm not in existing_norms:
                tracker.append({
                    "claim": c["claim"],
                    "branch": c.get("branch", ""),
                    "confidence": c.get("confidence", 0.0),
                    "status": ClaimStatus.OPEN.value,
                    "first_seen_run": run_id,
                    "last_seen_run": run_id,
                    "run_count": 1,
                    "history": [{"run_id": run_id, "confidence": c.get("confidence", 0.0)}],
                })

        # Cap size
        tracker.sort(key=lambda x: x.get("run_count", 1), reverse=True)
        tracker = tracker[: self.MAX_CLAIMS]

        state["claim_tracker"] = tracker
        runs = state.get("runs", [])
        runs.append({"run_id": run_id, "timestamp": self._utc_now(), "claim_count": len(claims)})
        state["runs"] = runs[-25:]
        self.save_state(state)

    def update_claim_status(self, claim_text: str, status: ClaimStatus) -> None:
        state = self.load_state()
        for tc in state.get("claim_tracker", []):
            if self._normalize(tc["claim"]) == self._normalize(claim_text):
                tc["status"] = status.value
                break
        self.save_state(state)

    def get_open_claims(self) -> list[dict[str, Any]]:
        state = self.load_state()
        open_statuses = {ClaimStatus.OPEN.value, ClaimStatus.STILL_OPEN.value, ClaimStatus.WORSENED.value}
        return [tc for tc in state.get("claim_tracker", []) if tc.get("status") in open_statuses]

    def build_recall_prompt(self) -> str:
        open_claims = self.get_open_claims()
        if not open_claims:
            return "No previously identified open issues on record."
        lines = ["Previously identified issues:", ""]
        for oc in open_claims:
            lines.append(f"- [{oc['status']}] {oc['claim']} (branch: {oc['branch']}, first seen: {oc['first_seen_run']}, runs: {oc['run_count']})")
        lines.append("")
        lines.append("For each issue above, verify if it is still present. If resolved, note what changed.")
        return "\n".join(lines)

    @staticmethod
    def _normalize(text: str) -> str:
        return text.strip().lower()

    @staticmethod
    def _find_confidence(claims: list[dict[str, Any]], norm_claim: str) -> float:
        for c in claims:
            if CrossRunTracker._normalize(c["claim"]) == norm_claim:
                return c.get("confidence", 0.0)
        return 0.0

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
