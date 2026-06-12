"""Signal trends — the time axis of convergence (an Apex original).

Spatial convergence says *independent signals agree on this module*. This
module adds the temporal question: **is it getting worse?** A module whose
churn is *rising* while a risk on it *ages* (old debt markers or an old
security finding) is an *accelerating hotspot* — a different urgency than a
stable one, even when today's snapshot looks identical.

Mechanics mirror ``IdeaMemory``: maintenance runs record the current signal
magnitudes to ``.apex/signal-history.json``; later runs compare against the
last recording. No file → no trends → behavior identical to a fresh engine,
so determinism is preserved for a given (repo state + .apex state).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Churn must rise by at least this many commits between snapshots to count
# as a trend (one extra touch is noise).
RISE_THRESHOLD = 2


class SignalTrends:
    def __init__(self, project_root: str | Path) -> None:
        self.path = Path(project_root) / ".apex" / "signal-history.json"

    # -- persistence -------------------------------------------------------
    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def record(self, profile: Any) -> None:
        """Persist today's magnitudes as the baseline for the next run."""
        snapshot = {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "churn": {c["module"]: c["commits"]
                      for c in (getattr(profile, "churn_hotspots", []) or [])},
            "debt_ages": dict(getattr(profile, "debt_marker_ages", {}) or {}),
            "security_ages": dict(getattr(profile, "security_finding_ages", {}) or {}),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        except OSError:
            pass  # history is an enhancement, never a failure mode

    # -- the trend question --------------------------------------------------
    def accelerating(self, profile: Any) -> list[dict[str, Any]]:
        """Modules whose churn ROSE since the last snapshot while a risk on
        them AGES (debt markers or a security finding sitting in the code).
        Empty without a baseline — a single observation has no slope."""
        prev = self.load()
        if not prev:
            return []
        prev_churn: dict[str, int] = prev.get("churn", {}) or {}
        out: list[dict[str, Any]] = []
        for entry in getattr(profile, "churn_hotspots", []) or []:
            module, now = entry["module"], entry["commits"]
            before = prev_churn.get(module)
            if before is None or now - before < RISE_THRESHOLD:
                continue
            aging = []
            if (getattr(profile, "debt_marker_ages", {}) or {}).get(module, 0) >= 90:
                aging.append("debt")
            if (getattr(profile, "security_finding_ages", {}) or {}).get(module, 0) >= 90:
                aging.append("security")
            if not aging:
                continue
            out.append({"module": module, "churn_before": before,
                        "churn_now": now, "aging": aging})
        out.sort(key=lambda d: (-(d["churn_now"] - d["churn_before"]), d["module"]))
        return out
