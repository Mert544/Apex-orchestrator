from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AgentLearning:
    """Behavioral learning from past agent runs.

    Tracks per-agent, per-pattern success rates and adjusts:
    - Thresholds (e.g. fewer false positives over time)
    - Priorities (which checks to run first based on past hit rate)
    - Confidence calibration (EMA of past accuracy)

    Usage:
        learning = AgentLearning(project_root=".")
        learning.record_result(agent="security", pattern="eval", success=True)
        tips = learning.get_tips(agent="security")
        # tips: {"eval": {"success_rate": 0.95, "suggested_priority": 1}}
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self._data: dict[str, Any] = {"agents": {}}
        self._load()

    def _file(self) -> Path:
        return self.project_root / ".apex" / "agent_learning.json"

    def _load(self) -> None:
        f = self._file()
        if f.exists():
            try:
                self._data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _save(self) -> None:
        self._file().parent.mkdir(parents=True, exist_ok=True)
        self._file().write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def record_result(self, agent: str, pattern: str, success: bool) -> None:
        """Record whether a pattern detection succeeded or failed."""
        agents = self._data.setdefault("agents", {})
        a = agents.setdefault(agent, {})
        patterns = a.setdefault("patterns", {})
        p = patterns.setdefault(pattern, {"success": 0, "failure": 0, "ema": 0.5})
        if success:
            p["success"] += 1
        else:
            p["failure"] += 1
        # EMA update (alpha=0.3)
        p["ema"] = 0.7 * p["ema"] + 0.3 * (1.0 if success else 0.0)
        self._save()

    def get_tips(self, agent: str) -> dict[str, Any]:
        """Return learned tips for an agent."""
        agents = self._data.get("agents", {})
        a = agents.get(agent, {})
        patterns = a.get("patterns", {})
        tips: dict[str, Any] = {}
        for pattern, stats in patterns.items():
            total = stats["success"] + stats["failure"]
            if total == 0:
                continue
            rate = stats["success"] / total
            tips[pattern] = {
                "success_rate": round(rate, 2),
                "total_runs": total,
                "ema_confidence": round(stats["ema"], 2),
                "suggested_priority": self._priority_from_rate(rate),
            }
        return tips

    def get_priority_list(self, agent: str) -> list[str]:
        """Return patterns sorted by learned priority (highest first)."""
        tips = self.get_tips(agent)
        return sorted(tips.keys(), key=lambda p: tips[p]["suggested_priority"])

    def should_skip(self, agent: str, pattern: str, min_ema: float = 0.3) -> bool:
        """If a pattern consistently fails, suggest skipping it."""
        tips = self.get_tips(agent)
        if pattern not in tips:
            return False
        return tips[pattern]["ema_confidence"] < min_ema

    def _priority_from_rate(self, rate: float) -> int:
        if rate >= 0.9:
            return 1
        if rate >= 0.7:
            return 2
        if rate >= 0.5:
            return 3
        return 4
