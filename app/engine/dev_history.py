"""A persistent development log — the organism's training trajectory.

Each ``apex develop`` campaign that does real work (verified moves > 0) is
appended here as a dated ``DevRun``: what objective it pursued, how many moves
it composed, and the project-health grade before and after. Read back across
runs, it is a fitness log — a chronological record that the assistant has been
developing the project over time, and by how much health it has gained.

This is deliberately *flat and chronological* (unlike the MAP-Elites
``composition_archive``, which keeps only the single best elite per cell): a
trajectory keeps every campaign, in order, so the trend itself is the artefact.

Persisted to ``.apex/dev-history.json``; stdlib-only. A missing or corrupt file
loads as an empty history, so this is always safe to read.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import json
from pathlib import Path
from typing import Any

HISTORY_REL = ".apex/dev-history.json"

__all__ = [
    "DevRun", "DevHistory", "record_run", "render_history_markdown",
]


@dataclass
class DevRun:
    """One development campaign and the health gain it produced."""

    date: str
    objective: str
    moves: int
    grade_before: int
    grade_after: int

    @property
    def delta(self) -> int:
        """Health-grade change this campaign produced (after − before)."""
        return self.grade_after - self.grade_before

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DevHistory:
    """A chronological list of development campaigns — the fitness log."""

    runs: list[DevRun] = field(default_factory=list)

    @classmethod
    def load(cls, project_root: str | Path, path: str | Path | None = None) -> DevHistory:
        p = Path(path) if path else Path(project_root) / HISTORY_REL
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        runs: list[DevRun] = []
        for v in (data.get("runs") or []):
            if isinstance(v, dict):
                try:
                    runs.append(DevRun(**v))
                except TypeError:
                    continue
        return cls(runs=runs)

    def save(self, project_root: str | Path, path: str | Path | None = None) -> Path:
        p = Path(path) if path else Path(project_root) / HISTORY_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    def to_dict(self) -> dict[str, Any]:
        return {"runs": [r.to_dict() for r in self.runs]}

    def record(self, run: DevRun) -> None:
        """Append a campaign to the trajectory, preserving order."""
        self.runs.append(run)

    def total_gain(self) -> int:
        """Total health gained across every recorded campaign (sum of deltas)."""
        return sum(r.delta for r in self.runs)

    def entries(self) -> list[DevRun]:
        """The campaigns in the order they were recorded (chronological)."""
        return list(self.runs)


def record_run(project_root: str | Path, objective: str, moves: int,
               grade_before: int, grade_after: int) -> bool:
    """Load → append a dated ``DevRun`` → save. Best-effort persistence: never
    raises into the caller (swallows ``OSError``). Skips campaigns that did no
    real work (``moves == 0``) so only genuine campaigns enter the log. Returns
    whether a run was recorded."""
    if moves == 0:
        return False
    try:
        history = DevHistory.load(project_root)
        history.record(DevRun(
            date=date.today().isoformat(),
            objective=objective,
            moves=moves,
            grade_before=grade_before,
            grade_after=grade_after,
        ))
        history.save(project_root)
    except OSError:
        return False
    return True


def render_history_markdown(history: DevHistory) -> str:
    """Render the development trajectory — a table of campaigns and the headline
    total health gained. An empty history renders a clean placeholder."""
    entries = history.entries()
    if not entries:
        return ("# Development history\n\n_No development campaigns recorded yet — "
                "run `apex develop --apply` to start the trajectory._\n")
    total = history.total_gain()
    lines = [f"# Development history — {len(entries)} campaign(s)", "",
             f"**Total health gained across {len(entries)} campaign(s): "
             f"{total:+d}**", "",
             "| Date | Objective | Moves | Grade | Delta |",
             "|---|---|---:|---:|---:|"]
    for r in entries:
        lines.append(f"| {r.date} | {r.objective} | {r.moves} | "
                     f"{r.grade_before}→{r.grade_after} | {r.delta:+d} |")
    lines.append("")
    return "\n".join(lines)
