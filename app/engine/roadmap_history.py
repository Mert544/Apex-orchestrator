"""Compare engineering roadmaps across runs — the engine's progress memory.

A single roadmap answers "what should we do next?". Saved across runs, two
roadmaps answer the follow-up a team actually lives by: *"did our work move the
needle?"* This module snapshots a roadmap to disk and diffs a fresh one against
it, surfacing what is **new**, what **no longer surfaces** (likely addressed),
what **moved phase**, and where **ROI shifted**.

Ideas are matched by title (subject + lens chain), which is stable across runs
for unchanged code and changes meaningfully when the code does — exactly the
signal we want. Deterministic, stdlib-only (json).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ROI must move by at least this much to count as a change (vs. float noise).
_ROI_EPS = 0.1


@dataclass
class RoadmapChange:
    title: str
    subject: str
    status: str = "stable"    # new | dropped | phase_moved | roi_up | roi_down | stable
    prev_phase: str = ""
    curr_phase: str = ""
    prev_roi: float = 0.0
    curr_roi: float = 0.0
    roi_delta: float = 0.0
    grounded_in: str = ""     # the seeding fact behind the idea ("churn-hotspot: …")

    @property
    def signal(self) -> str:
        """The fact label alone ("churn-hotspot"), for grouping by signal."""
        return self.grounded_in.split(":", 1)[0].strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoadmapDiff:
    new: list[RoadmapChange] = field(default_factory=list)
    dropped: list[RoadmapChange] = field(default_factory=list)
    phase_moved: list[RoadmapChange] = field(default_factory=list)
    roi_improved: list[RoadmapChange] = field(default_factory=list)
    roi_regressed: list[RoadmapChange] = field(default_factory=list)
    stable_count: int = 0
    previous_generated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "new": [c.to_dict() for c in self.new],
            "dropped": [c.to_dict() for c in self.dropped],
            "phase_moved": [c.to_dict() for c in self.phase_moved],
            "roi_improved": [c.to_dict() for c in self.roi_improved],
            "roi_regressed": [c.to_dict() for c in self.roi_regressed],
            "stable_count": self.stable_count,
            "previous_generated": self.previous_generated,
        }


def _flatten(roadmap) -> dict[str, dict[str, Any]]:
    """Map a Roadmap's items by title -> {phase, roi, ...}."""
    out: dict[str, dict[str, Any]] = {}
    for phase in roadmap.phases:
        for item in phase.items:
            out[item.title] = {
                "title": item.title,
                "subject": item.subject,
                "phase": phase.name,
                "roi": item.roi,
                "impact": item.impact,
                "effort": item.effort,
                # Provenance travels with the snapshot so a later diff can say
                # *why* an idea appeared or stopped surfacing, not just that it did.
                "grounded_in": (item.source_facts[0] if item.source_facts else ""),
            }
    return out


def snapshot_roadmap(roadmap, path: str | Path) -> Path:
    """Write a roadmap snapshot (flattened items + timestamp) as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(roadmap_to_snapshot(roadmap), indent=2), encoding="utf-8")
    return path


def roadmap_to_snapshot(roadmap) -> dict[str, Any]:
    """Build the in-memory snapshot dict for a roadmap (no file I/O).

    Same shape ``diff_roadmaps`` expects as ``previous`` — useful for comparing
    two roadmaps within a single process (e.g. before/after a self-improvement
    cycle) without touching disk.
    """
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "project_root": roadmap.project_root,
        "objective": roadmap.objective,
        "items": list(_flatten(roadmap).values()),
    }


def load_snapshot(path: str | Path) -> dict[str, Any] | None:
    """Load a previously saved snapshot, or None if absent/unreadable."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def diff_roadmaps(previous: dict[str, Any], current) -> RoadmapDiff:
    """Diff a current Roadmap against a previously-saved snapshot dict."""
    prev_items = {it["title"]: it for it in previous.get("items", [])}
    curr_items = _flatten(current)
    diff = RoadmapDiff(previous_generated=previous.get("generated", ""))

    for title, cur in curr_items.items():
        if title not in prev_items:
            diff.new.append(RoadmapChange(
                title=title, subject=cur["subject"], status="new",
                curr_phase=cur["phase"], curr_roi=cur["roi"],
                grounded_in=cur.get("grounded_in", ""),
            ))
            continue
        prev = prev_items[title]
        roi_delta = round(cur["roi"] - prev.get("roi", 0.0), 4)
        change = RoadmapChange(
            title=title, subject=cur["subject"],
            prev_phase=prev.get("phase", ""), curr_phase=cur["phase"],
            prev_roi=prev.get("roi", 0.0), curr_roi=cur["roi"], roi_delta=roi_delta,
        )
        if prev.get("phase") != cur["phase"]:
            change.status = "phase_moved"
            diff.phase_moved.append(change)
        elif roi_delta >= _ROI_EPS:
            change.status = "roi_up"
            diff.roi_improved.append(change)
        elif roi_delta <= -_ROI_EPS:
            change.status = "roi_down"
            diff.roi_regressed.append(change)
        else:
            diff.stable_count += 1

    for title, prev in prev_items.items():
        if title not in curr_items:
            diff.dropped.append(RoadmapChange(
                title=title, subject=prev.get("subject", ""), status="dropped",
                prev_phase=prev.get("phase", ""), prev_roi=prev.get("roi", 0.0),
                grounded_in=prev.get("grounded_in", ""),
            ))
    return diff


def _count_signals(changes: list[RoadmapChange]) -> list[tuple[str, int]]:
    """Distinct fact labels among ``changes`` with counts, most frequent first
    (ties alphabetical — deterministic)."""
    counts: dict[str, int] = {}
    for c in changes:
        if c.signal:
            counts[c.signal] = counts.get(c.signal, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _signal_phrase(signals: list[tuple[str, int]]) -> str:
    return ", ".join(
        f"`{label}` ×{n}" if n > 1 else f"`{label}`" for label, n in signals
    )


def render_diff_markdown(diff: RoadmapDiff) -> str:
    """Render a roadmap diff as a readable progress report."""
    lines = ["# Roadmap Changes Since Last Run", ""]
    if diff.previous_generated:
        lines.append(f"_compared against snapshot from {diff.previous_generated}_")
    lines.append(
        f"{len(diff.new)} new · {len(diff.dropped)} no longer surfaced · "
        f"{len(diff.phase_moved)} moved phase · {len(diff.roi_improved)} ROI↑ · "
        f"{len(diff.roi_regressed)} ROI↓ · {diff.stable_count} stable"
    )
    lines.append("")

    # Narrate *why* the roadmap changed: which signals produced the new work,
    # and which stopped firing — the cross-run story, not just the delta.
    new_signals = _count_signals(diff.new)
    gone_signals = _count_signals(diff.dropped)
    if new_signals:
        lines.append(f"**Where the new work comes from:** {_signal_phrase(new_signals)}")
    if gone_signals:
        lines.append(f"**Signals that stopped firing:** {_signal_phrase(gone_signals)}")
    if new_signals or gone_signals:
        lines.append("")

    def _section(title: str, items: list[RoadmapChange], fmt) -> None:
        if not items:
            return
        lines.append(f"## {title}")
        for c in items:
            lines.append(f"- {fmt(c)}")
        lines.append("")

    def _new_line(c: RoadmapChange) -> str:
        base = f"[{c.curr_phase}] {c.title}  (ROI {c.curr_roi})"
        return f"{base} — grounded in `{c.grounded_in}`" if c.grounded_in else base

    def _dropped_line(c: RoadmapChange) -> str:
        base = f"[{c.prev_phase}] {c.title}  (was ROI {c.prev_roi})"
        return f"{base} — its `{c.signal}` signal no longer fires" if c.signal else base

    _section("🆕 New ideas", diff.new, _new_line)
    _section("✅ No longer surfaced (likely addressed)", diff.dropped, _dropped_line)
    _section("🔀 Moved phase", diff.phase_moved,
             lambda c: f"{c.title}: {c.prev_phase} → {c.curr_phase}")
    _section("📈 ROI improved", diff.roi_improved,
             lambda c: f"{c.title}: {c.prev_roi} → {c.curr_roi}  (+{c.roi_delta})")
    _section("📉 ROI regressed", diff.roi_regressed,
             lambda c: f"{c.title}: {c.prev_roi} → {c.curr_roi}  ({c.roi_delta})")
    if not (diff.new or diff.dropped or diff.phase_moved or diff.roi_improved or diff.roi_regressed):
        lines.append("_No changes since the last snapshot._")
        lines.append("")
    return "\n".join(lines)
