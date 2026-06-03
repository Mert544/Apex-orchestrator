"""Investment curve — how much impact each level of effort buys, and where to stop.

The portfolio optimizer answers "best ideas for *this* budget". Sweep the budget
from small to large and a deeper question appears: what are the **diminishing
returns** of investing more effort? Early effort buys cheap high-impact wins;
past some point each additional unit of effort returns far less.

This module computes that production-possibility frontier — for a ladder of
budgets, the maximum achievable impact (via the knapsack optimizer) — then finds
the **knee**: the last budget where the marginal return still clears half the
peak. That's the "invest up to here, then reassess" line.

Pure and deterministic. No LLM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.engine.idea_portfolio import optimize_portfolio
from app.models.idea import IdeaTreeReport


@dataclass
class CurvePoint:
    budget: float
    total_impact: float
    n_ideas: int
    marginal_return: float   # impact gained per unit effort since the previous point
    is_knee: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def investment_curve(report: IdeaTreeReport, steps: int = 8, roadmap=None) -> list[CurvePoint]:
    """Max achievable impact across a ladder of effort budgets, with the knee marked."""
    if roadmap is None:
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = RoadmapSynthesizer().build(report)

    total_effort = round(sum(i.effort for ph in roadmap.phases for i in ph.items), 4)
    if total_effort <= 0 or steps < 1:
        return []

    points: list[CurvePoint] = []
    prev_impact = 0.0
    prev_budget = 0.0
    for k in range(1, steps + 1):
        budget = round(total_effort * k / steps, 4)
        p = optimize_portfolio(report, budget, roadmap=roadmap)
        d_budget = round(budget - prev_budget, 4)
        marginal = round((p.total_impact - prev_impact) / d_budget, 4) if d_budget > 0 else 0.0
        points.append(CurvePoint(budget, p.total_impact, len(p.selected), marginal))
        prev_impact = p.total_impact
        prev_budget = budget

    # Knee: the last budget whose marginal return still clears half the peak.
    peak = max((pt.marginal_return for pt in points), default=0.0)
    threshold = 0.5 * peak
    knee_idx = 0
    for i, pt in enumerate(points):
        if pt.marginal_return >= threshold:
            knee_idx = i
    if points:
        points[knee_idx].is_knee = True
    return points


def render_investment_markdown(points: list[CurvePoint]) -> str:
    """Render the investment curve with an ASCII impact sparkline and the knee."""
    lines = ["# Investment curve — impact vs. effort (diminishing returns)", ""]
    if not points:
        lines += ["_No ideas to analyze._", ""]
        return "\n".join(lines)

    max_impact = max(p.total_impact for p in points) or 1.0
    knee = next((p for p in points if p.is_knee), None)
    if knee is not None:
        lines.append(
            f"**Recommended investment: up to ~{knee.budget} effort** "
            f"({knee.n_ideas} ideas, impact {knee.total_impact}). Beyond that, each unit "
            f"of effort returns less than half the early payoff."
        )
        lines.append("")
    lines.append("| Effort budget | Ideas | Total impact | Marginal | |")
    lines.append("|---:|---:|---:|---:|:--|")
    for p in points:
        bar = "█" * max(1, round(20 * p.total_impact / max_impact))
        star = " ⟵ knee" if p.is_knee else ""
        lines.append(
            f"| {p.budget} | {p.n_ideas} | {p.total_impact} | {p.marginal_return} | "
            f"`{bar}`{star} |"
        )
    lines.append("")
    return "\n".join(lines)
