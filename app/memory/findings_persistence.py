from __future__ import annotations

import json
import shelve
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ClaimStatus:
    OPEN = "open"
    STILL_OPEN = "still_open"
    POTENTIALLY_RESOLVED = "potentially_resolved"
    RESOLVED = "resolved"
    WORSENED = "worsened"


class _BaseBackend(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save(self, state: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class _JsonBackend(_BaseBackend):
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return self._default()

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def close(self) -> None:
        pass

    @staticmethod
    def _default() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "claim_tracker": [],
            "runs": [],
        }


class _ShelveBackend(_BaseBackend):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: shelve.Shelf | None = None

    def load(self) -> dict[str, Any]:
        try:
            self._ensure_open()
            if self._db is None:
                return self._default()
            raw = self._db.get("state")
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return self._default()

    def save(self, state: dict[str, Any]) -> None:
        self._ensure_open()
        if self._db is not None:
            self._db["state"] = state
            self._db.sync()

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def _ensure_open(self) -> None:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = shelve.open(str(self.path), flag="c")

    @staticmethod
    def _default() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "claim_tracker": [],
            "runs": [],
        }


class FindingsPersistence:
    """Cross-run findings persistence with pluggable backends (json/shelve).

    Usage:
        store = FindingsPersistence(project_root=".", backend="shelve")
        store.record_findings("run-1", [{"claim": "eval() usage", ...}])
        persistent = store.get_persistent_findings(min_runs=2)
        prompt = store.build_recall_prompt()
    """

    MAX_CLAIMS = 500
    MAX_RUNS = 100

    def __init__(
        self,
        project_root: str | Path,
        memory_dir_name: str = ".epistemic",
        backend: str = "json",
        max_claims: int = MAX_CLAIMS,
        max_runs: int = MAX_RUNS,
    ) -> None:
        if backend not in ("json", "shelve"):
            raise ValueError(f"Unsupported backend: {backend}. Use 'json' or 'shelve'.")

        self.project_root = Path(project_root)
        self.memory_dir = self.project_root / memory_dir_name
        self.backend_name = backend
        self.max_claims = max_claims
        self.max_runs = max_runs

        if backend == "json":
            self._backend: _BaseBackend = _JsonBackend(self.memory_dir / "findings.json")
        else:
            self._backend = _ShelveBackend(self.memory_dir / "findings")

    def record_findings(
        self, run_id: str, findings: list[dict[str, Any]], run_meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Record findings from a new run and update statuses of existing claims."""
        state = self._backend.load()
        tracker: list[dict[str, Any]] = list(state.get("claim_tracker", []))
        run_claims_set = {self._normalize(f.get("claim", "")) for f in findings}

        # Update existing claims
        for tc in tracker:
            norm = self._normalize(tc.get("claim", ""))
            if norm in run_claims_set:
                if tc.get("status") == ClaimStatus.OPEN:
                    tc["status"] = ClaimStatus.STILL_OPEN
                tc["last_seen_run"] = run_id
                tc["run_count"] = tc.get("run_count", 1) + 1
                tc["history"].append({"run_id": run_id, "confidence": self._find_confidence(findings, norm)})
            else:
                if tc.get("status") in (ClaimStatus.OPEN, ClaimStatus.STILL_OPEN):
                    tc["status"] = ClaimStatus.POTENTIALLY_RESOLVED
                tc["history"].append({"run_id": run_id, "status_change": "absent"})

        # Add new claims
        existing_norms = {self._normalize(tc.get("claim", "")) for tc in tracker}
        for f in findings:
            norm = self._normalize(f.get("claim", ""))
            if norm and norm not in existing_norms:
                tracker.append({
                    "claim": f["claim"],
                    "branch": f.get("branch", ""),
                    "confidence": f.get("confidence", 0.0),
                    "status": ClaimStatus.OPEN,
                    "first_seen_run": run_id,
                    "last_seen_run": run_id,
                    "run_count": 1,
                    "history": [{"run_id": run_id, "confidence": f.get("confidence", 0.0)}],
                })

        # Evict oldest / least-seen claims to stay within limits
        tracker.sort(key=lambda x: (x.get("run_count", 1), x.get("last_seen_run", "")), reverse=True)
        tracker = tracker[: self.max_claims]

        state["claim_tracker"] = tracker
        runs = state.get("runs", [])
        runs.append({
            "run_id": run_id,
            "timestamp": self._utc_now(),
            "claim_count": len(findings),
            **(run_meta or {}),
        })
        state["runs"] = runs[-self.max_runs :]

        self._backend.save(state)
        return {
            "recorded": len(findings),
            "total_tracked": len(tracker),
            "total_runs": len(runs),
        }

    def get_persistent_findings(self, min_runs: int = 2) -> list[dict[str, Any]]:
        """Return claims seen in at least *min_runs* runs."""
        state = self._backend.load()
        return [
            tc for tc in state.get("claim_tracker", [])
            if tc.get("run_count", 1) >= min_runs
        ]

    def get_resolved_findings(self) -> list[dict[str, Any]]:
        """Return claims marked as resolved or potentially resolved."""
        state = self._backend.load()
        resolved_statuses = {ClaimStatus.POTENTIALLY_RESOLVED, ClaimStatus.RESOLVED}
        return [tc for tc in state.get("claim_tracker", []) if tc.get("status") in resolved_statuses]

    def update_claim_status(self, claim_text: str, status: str) -> None:
        state = self._backend.load()
        for tc in state.get("claim_tracker", []):
            if self._normalize(tc.get("claim", "")) == self._normalize(claim_text):
                tc["status"] = status
                break
        self._backend.save(state)

    def get_open_claims(self) -> list[dict[str, Any]]:
        state = self._backend.load()
        open_statuses = {ClaimStatus.OPEN, ClaimStatus.STILL_OPEN, ClaimStatus.WORSENED}
        return [tc for tc in state.get("claim_tracker", []) if tc.get("status") in open_statuses]

    def build_recall_prompt(self) -> str:
        open_claims = self.get_open_claims()
        if not open_claims:
            return "No previously identified open issues on record."
        lines = ["Previously identified issues:", ""]
        for oc in open_claims:
            lines.append(
                f"- [{oc['status']}] {oc['claim']} (branch: {oc.get('branch', '')}, "
                f"first seen: {oc['first_seen_run']}, runs: {oc.get('run_count', 1)})"
            )
        lines.append("")
        lines.append("For each issue above, verify if it is still present. If resolved, note what changed.")
        return "\n".join(lines)

    def export_state(self, path: str | Path | None = None) -> str:
        """Export current state as JSON string (useful for backups or migration)."""
        state = self._backend.load()
        raw = json.dumps(state, indent=2, ensure_ascii=False)
        if path:
            Path(path).write_text(raw, encoding="utf-8")
        return raw

    def import_state(self, raw: str) -> None:
        """Import state from JSON string."""
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("Invalid state JSON")
        self._backend.save(state)

    def close(self) -> None:
        self._backend.close()

    def __enter__(self) -> FindingsPersistence:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    @staticmethod
    def _normalize(text: str) -> str:
        return text.strip().lower()

    @staticmethod
    def _find_confidence(findings: list[dict[str, Any]], norm_claim: str) -> float:
        for f in findings:
            if FindingsPersistence._normalize(f.get("claim", "")) == norm_claim:
                return f.get("confidence", 0.0)
        return 0.0

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
