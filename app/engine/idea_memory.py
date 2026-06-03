"""Idea learning memory — the engine grows wiser about *this* project over time.

The permutation engine is deterministic, but it need not be amnesiac. Each time
Apex applies fixes, the outcomes (which kinds of ideas actually landed cleanly vs.
rolled back vs. couldn't be applied) are recorded here, keyed by the development
lens (`operator`) or root seeding fact (`label`). On the next run the engine
consults this memory and gives a small, bounded feasibility nudge: lenses with a
strong track record on this codebase rise; ones that keep failing recede.

It is **opt-in by construction**: with no memory file, scoring is byte-identical
to a fresh engine (so determinism and every existing test are unaffected). The
nudge is bounded to ±10% and clamped, so memory shapes priorities without ever
overriding the grounded scores. Persisted to ``.apex/idea-memory.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MEMORY_REL = ".apex/idea-memory.json"

# Bounded nudge: a perfect track record multiplies feasibility by at most this;
# a poor one divides by it. Small on purpose — memory tilts, never dictates.
_MAX_NUDGE = 0.10
# Don't trust a key until it has at least this many recorded outcomes.
_MIN_SAMPLES = 2


@dataclass
class _Stat:
    applied: int = 0
    rolled_back: int = 0
    blocked: int = 0

    @property
    def total(self) -> int:
        return self.applied + self.rolled_back + self.blocked

    @property
    def success_rate(self) -> float:
        return self.applied / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, int]:
        return {"applied": self.applied, "rolled_back": self.rolled_back, "blocked": self.blocked}


@dataclass
class IdeaMemory:
    """Per-key outcome tallies that bias future feasibility scoring."""

    by_operator: dict[str, _Stat] = field(default_factory=dict)
    by_label: dict[str, _Stat] = field(default_factory=dict)

    # --- persistence ---------------------------------------------------------

    @classmethod
    def load(cls, project_root: str | Path, path: str | Path | None = None) -> IdeaMemory:
        p = Path(path) if path else Path(project_root) / MEMORY_REL
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            by_operator={k: _Stat(**v) for k, v in (data.get("by_operator") or {}).items()},
            by_label={k: _Stat(**v) for k, v in (data.get("by_label") or {}).items()},
        )

    def save(self, project_root: str | Path, path: str | Path | None = None) -> Path:
        p = Path(path) if path else Path(project_root) / MEMORY_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_operator": {k: v.to_dict() for k, v in sorted(self.by_operator.items())},
            "by_label": {k: v.to_dict() for k, v in sorted(self.by_label.items())},
        }

    # --- recording -----------------------------------------------------------

    def record_outcomes(self, summary: dict[str, Any]) -> None:
        """Tally the results of an apply_plan/maintenance summary."""
        for r in summary.get("results", []) or []:
            outcome = "applied" if r.get("applied") else ("rolled_back" if r.get("rolled_back") else "blocked")
            op = r.get("operator") or ""
            label = r.get("label") or ""
            if op and op != "root":
                self._bump(self.by_operator, op, outcome)
            if label:
                self._bump(self.by_label, label, outcome)

    @staticmethod
    def _bump(table: dict[str, _Stat], key: str, outcome: str) -> None:
        stat = table.setdefault(key, _Stat())
        setattr(stat, outcome, getattr(stat, outcome) + 1)

    # --- influence on scoring ------------------------------------------------

    def feasibility_factor(self, operator: str, label: str = "") -> float:
        """A bounded multiplier in [1-_MAX_NUDGE, 1+_MAX_NUDGE] from track record.

        Roots are keyed by their seeding ``label``; other ideas by ``operator``.
        Keys with too few samples return a neutral 1.0 (no opinion yet).
        """
        stat = None
        if operator and operator != "root" and operator in self.by_operator:
            stat = self.by_operator[operator]
        elif label and label in self.by_label:
            stat = self.by_label[label]
        if stat is None or stat.total < _MIN_SAMPLES:
            return 1.0
        # success_rate 0.5 → neutral; 1.0 → +_MAX_NUDGE; 0.0 → -_MAX_NUDGE.
        return round(1.0 + (stat.success_rate - 0.5) * 2.0 * _MAX_NUDGE, 4)

    @classmethod
    def learn_from(cls, summary: dict[str, Any], project_root: str | Path,
                   path: str | Path | None = None) -> IdeaMemory:
        """Load → record this run's outcomes → save. The full learning step."""
        mem = cls.load(project_root, path)
        mem.record_outcomes(summary)
        mem.save(project_root, path)
        return mem

    def summary(self) -> dict[str, Any]:
        """A compact, human-facing view of what the engine has learned."""
        def _top(table: dict[str, _Stat], best: bool) -> list[dict[str, Any]]:
            seen = [(k, s) for k, s in table.items() if s.total >= _MIN_SAMPLES]
            seen.sort(key=lambda kv: (kv[1].success_rate, kv[1].total), reverse=best)
            return [{"key": k, "success_rate": round(s.success_rate, 3), "samples": s.total}
                    for k, s in seen[:5]]

        return {
            "operators_tracked": len(self.by_operator),
            "labels_tracked": len(self.by_label),
            "most_reliable": _top(self.by_operator, best=True),
            "least_reliable": _top(self.by_operator, best=False),
        }
