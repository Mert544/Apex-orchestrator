from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PersistentMemoryStore:
    def __init__(
        self,
        project_root: str | Path,
        memory_dir_name: str = ".epistemic",
        max_claims: int = 500,
        max_questions: int = 500,
        max_state_size_mb: float = 10.0,
    ) -> None:
        self.project_root = Path(project_root)
        self.memory_dir = self.project_root / memory_dir_name
        self.memory_file = self.memory_dir / "memory.json"
        self.max_claims = max_claims
        self.max_questions = max_questions
        self.max_state_size_bytes = max_state_size_mb * 1024 * 1024
        self._state_cache: dict[str, Any] | None = None

    def hydrate_graph(self, graph) -> dict[str, Any]:
        state = self.load_state()
        for claim in state.get("known_claims", []):
            graph.load_memory_claim(claim)
        for question in state.get("known_questions", []):
            graph.load_memory_question(question)
        return state

    def estimated_bytes(self) -> int:
        state = self.load_state()
        return len(json.dumps(state, default=str).encode("utf-8"))

    def persist_run(self, objective: str, report, nodes) -> dict[str, Any]:
        state = self.load_state()
        run_id = self._make_run_id()

        # Evict oversized collections before mutating
        state = self._evict(state)

        sorted_nodes = sorted(nodes, key=lambda n: n.claim_priority, reverse=True)
        branch_history = []
        for node in sorted_nodes:
            branch_history.append(
                {
                    "branch_path": node.branch_path,
                    "claim": node.claim,
                    "claim_type": node.claim_type.value,
                    "claim_priority": round(node.claim_priority, 4),
                    "confidence": round(node.confidence, 4),
                    "risk": round(node.risk, 4),
                    "status": node.status.value,
                    "stop_reason": node.stop_reason.value if node.stop_reason else None,
                    "source_question": node.source_question,
                }
            )

        report_dump = report.model_dump()
        state["schema_version"] = 1
        state["project_root"] = str(self.project_root)
        state["known_claims"] = self._dedupe([*state.get("known_claims", []), *report.confidence_map.keys()])
        state["known_questions"] = self._dedupe([*state.get("known_questions", []), *report.unresolved_questions])
        state["last_report"] = report_dump
        if not getattr(report, "focus_branch", None):
            state["last_full_report"] = report_dump

        runs = state.get("runs", [])
        previous_run_count = len(runs)
        runs.append(
            {
                "run_id": run_id,
                "timestamp": self._utc_now(),
                "objective": objective,
                "run_mode": "focused" if getattr(report, "focus_branch", None) else "full",
                "focus_branch": getattr(report, "focus_branch", None),
                "main_findings": report.main_findings[:10],
                "recommended_actions": report.recommended_actions[:10],
                "branch_count": len(report.branch_map),
                "memory_file": str(self.memory_file),
            }
        )
        state["runs"] = runs[-25:]
        state["branch_history"] = branch_history[:250]

        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        self._state_cache = state

        return {
            "memory_file": str(self.memory_file),
            "run_id": run_id,
            "known_claim_count": len(state.get("known_claims", [])),
            "known_question_count": len(state.get("known_questions", [])),
            "previous_run_count": previous_run_count,
        }

    def load_state(self) -> dict[str, Any]:
        if self._state_cache is not None:
            return self._state_cache
        default = {
            "schema_version": 1,
            "project_root": str(self.project_root),
            "known_claims": [],
            "known_questions": [],
            "runs": [],
            "branch_history": [],
            "last_report": {},
            "last_full_report": {},
        }
        if not self.memory_file.exists():
            self._state_cache = default
            return default
        try:
            raw = json.loads(self.memory_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("last_full_report", {})
                self._state_cache = raw
                return raw
        except Exception:
            pass
        self._state_cache = default
        return default

    def _make_run_id(self) -> str:
        return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _evict(self, state: dict[str, Any]) -> dict[str, Any]:
        """Trim state to keep within size and count limits."""
        for key, limit in (("known_claims", self.max_claims), ("known_questions", self.max_questions)):
            items = state.get(key, [])
            if len(items) > limit:
                # Keep most recent (end of list) — they were added last
                state[key] = items[-limit:]

        # If still oversized, trim more aggressively
        size = len(json.dumps(state, default=str).encode("utf-8"))
        if size > self.max_state_size_bytes:
            overshoot_ratio = size / self.max_state_size_bytes
            for key, limit in (("known_claims", self.max_claims), ("known_questions", self.max_questions)):
                items = state.get(key, [])
                new_limit = max(10, int(limit / overshoot_ratio))
                if len(items) > new_limit:
                    state[key] = items[-new_limit:]
            # Also trim branch_history
            bh = state.get("branch_history", [])
            if bh:
                state["branch_history"] = bh[-100:]
        return state

    def _dedupe(self, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            lowered = value.strip().lower()
            if not lowered or lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(value)
        return cleaned
