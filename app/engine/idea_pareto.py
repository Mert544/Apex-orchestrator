"""The Pareto frontier of development ideas — the efficient trade-off set.

ROI collapses every idea to a single number (impact ÷ effort), which hides
genuine trade-offs: a high-impact, high-effort architectural fix and a tiny,
modest-impact cleanup can both be rational choices. This module instead computes
the **Pareto frontier** across three competing objectives — maximize *impact*,
minimize *effort*, maximize *value* — and returns only the **non-dominated**
ideas: those for which no other idea is at least as good on all three and better
on at least one.

Everything else is *dominated* (strictly beaten by some frontier idea) and can be
ignored. The frontier is the short list actually worth deliberating over.
Deterministic; pure set logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ParetoPoint:
    branch_path: str
    title: str
    phase: str
    impact: float
    effort: float
    value: float
    roi: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dominates(b: Any, a: Any) -> bool:
    """True if idea ``b`` dominates ``a``: at least as good on every objective
    (impact↑, effort↓, value↑) and strictly better on at least one."""
    at_least = (b.impact >= a.impact) and (b.effort <= a.effort) and (b.value >= a.value)
    strictly = (b.impact > a.impact) or (b.effort < a.effort) or (b.value > a.value)
    return at_least and strictly


def pareto_frontier(items: list[Any]) -> list[ParetoPoint]:
    """Return the non-dominated ideas, deduped by objective vector, annotated.

    ``items`` are objects exposing ``.impact``, ``.effort``, ``.value`` (plus
    ``.roi``, ``.title``, ``.branch_path``, ``.phase``) — e.g. RoadmapItems.
    """
    if not items:
        return []

    # Dedup identical objective vectors (they can't dominate each other, so all
    # would survive); keep the best-ROI representative for a clean frontier.
    by_vector: dict[tuple[float, float, float], Any] = {}
    for it in items:
        key = (round(it.impact, 4), round(it.effort, 4), round(it.value, 4))
        cur = by_vector.get(key)
        if cur is None or (it.roi, it.branch_path) > (cur.roi, cur.branch_path):
            by_vector[key] = it
    unique = list(by_vector.values())

    frontier = [a for a in unique if not any(_dominates(b, a) for b in unique if b is not a)]

    # Annotate why each point earns its place (extremes vs. balanced trade-off).
    max_impact = max(p.impact for p in frontier)
    min_effort = min(p.effort for p in frontier)
    max_value = max(p.value for p in frontier)
    max_roi = max(p.roi for p in frontier)
    points: list[ParetoPoint] = []
    for p in frontier:
        reasons: list[str] = []
        if p.impact == max_impact:
            reasons.append("highest impact")
        if p.effort == min_effort:
            reasons.append("lowest effort")
        if p.value == max_value:
            reasons.append("highest value")
        if p.roi == max_roi:
            reasons.append("best ROI")
        if not reasons:
            reasons.append("balanced trade-off")
        points.append(ParetoPoint(
            branch_path=p.branch_path, title=p.title, phase=getattr(p, "phase", ""),
            impact=p.impact, effort=p.effort, value=p.value, roi=p.roi, reasons=reasons,
        ))
    # Strongest impact first; ties broken by lower effort then path (deterministic).
    points.sort(key=lambda p: (-p.impact, p.effort, p.branch_path))
    return points


def _bang_for_buck(p: ParetoPoint) -> float:
    """Value bought per unit of effort. Effort is floored by a tiny epsilon so a
    zero-effort point stays finite (and ranks highest) instead of dividing by
    zero."""
    return p.value / max(p.effort, 1e-9)


def knee_point(points: list[Any]) -> ParetoPoint | None:
    """The single best-bang-for-buck pick — "if you do ONE thing, do this."

    Among the (already non-dominated) frontier ``points``, returns the idea with
    the highest *value-per-effort* ratio: the knee where each additional unit of
    effort still buys the most value. Accepts either a list of ``ParetoPoint`` or
    raw items (it computes the frontier first), so a caller can pass whatever it
    has. Empty-safe: no points → ``None``.

    Ties on the ratio break deterministically: higher value, then lower effort,
    then higher ROI, then ``branch_path`` (lexicographically smallest) — the same
    stable ordering the frontier itself uses.
    """
    if not points:
        return None
    frontier = (
        points if all(isinstance(p, ParetoPoint) for p in points)
        else pareto_frontier(points)
    )
    if not frontier:
        return None
    # Sort best-first; ratio↓, value↓, effort↑, roi↓, path↑ are all deterministic.
    return sorted(
        frontier,
        key=lambda p: (-_bang_for_buck(p), -p.value, p.effort, -p.roi, p.branch_path),
    )[0]


def frontier_from_roadmap(roadmap: Any) -> list[ParetoPoint]:
    """Convenience: compute the frontier over all of a roadmap's items."""
    items = [i for ph in roadmap.phases for i in ph.items]
    return pareto_frontier(items)


def render_pareto_markdown(points: list[ParetoPoint], total_ideas: int = 0) -> str:
    """Render the efficient frontier as a decision-ready short list."""
    lines = ["# Efficient frontier — the ideas actually worth deliberating", ""]
    if not points:
        lines += ["_No ideas to analyze._", ""]
        return "\n".join(lines)
    note = f"{len(points)} non-dominated"
    if total_ideas:
        dominated = max(0, total_ideas - len(points))
        note += f" of {total_ideas} ideas · {dominated} dominated (safely ignorable)"
    lines += [note, ""]
    lines.append("Each idea below is the best choice for *some* trade-off. Everything not "
                 "listed is beaten by one of these on impact, effort, and value at once.\n")
    for p in points:
        why = ", ".join(p.reasons)
        phase = f"[{p.phase}] " if p.phase else ""
        lines.append(
            f"- `{p.branch_path}` {phase}**{p.title}** — _{why}_  "
            f"(impact {p.impact} · effort {p.effort} · value {p.value} · ROI {p.roi})"
        )
    lines.append("")
    return "\n".join(lines)
