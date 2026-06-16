"""Idea portfolio optimization — the best *set* of work for an effort budget.

A ranking answers "what's the single best idea?". A team with finite time needs
the harder answer: *which combination* of ideas delivers the most impact for the
effort I can spend? That is a **precedence-constrained knapsack** — maximize total
impact subject to total effort ≤ budget, while respecting that you can't pick
"harden X" without also picking its prerequisite "test X".

This module solves it with a deterministic dependency-closure greedy: it considers
ideas best-ROI-first, and for each one prices in the *closure* of its not-yet-
selected prerequisites, taking the whole bundle only if it still fits. The result
is the recommended portfolio plus what was deliberately left out.

Pure and deterministic. No LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.engine.idea_dependencies import infer_dependencies
from app.models.idea import IdeaTreeReport


@dataclass
class PortfolioItem:
    branch_path: str
    title: str
    impact: float
    effort: float
    roi: float
    pulled_in_as_prerequisite: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Portfolio:
    budget: float
    total_impact: float
    total_effort: float
    selected: list[PortfolioItem] = field(default_factory=list)
    excluded_count: int = 0

    @property
    def utilization(self) -> float:
        return round(self.total_effort / self.budget, 4) if self.budget else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["utilization"] = self.utilization
        return d


def _dependency_closure(
    idea_id: str, chosen: set[str], deps: dict[str, set[str]], path_by_id: dict[str, str]
) -> set[str]:
    """The idea plus all transitive prerequisites not already chosen."""
    out: set[str] = set()
    stack = [idea_id]
    while stack:
        cur = stack.pop()
        if cur in chosen or cur in out:
            continue
        out.add(cur)
        stack.extend(d for d in deps.get(cur, set()) if d in path_by_id)
    return out


def _greedy_select(
    candidates: list,
    budget: float,
    deps: dict[str, set[str]],
    path_by_id: dict[str, str],
    eff: Callable[[str], float],
) -> tuple[set[str], set[str], float]:
    """Take ideas best-first, pricing in each one's prerequisite closure; return
    (chosen ids, prereq-only ids, total effort)."""
    chosen: set[str] = set()
    prereq_only: set[str] = set()
    total_effort = 0.0
    for idea in candidates:
        if idea.id in chosen:
            continue
        bundle = _dependency_closure(idea.id, chosen, deps, path_by_id)
        bundle_effort = round(sum(eff(b) for b in bundle), 4)
        if total_effort + bundle_effort <= budget + 1e-9:
            chosen |= bundle
            total_effort = round(total_effort + bundle_effort, 4)
            # Anything in the bundle other than the idea itself came along as a prereq.
            prereq_only |= (bundle - {idea.id})
    return chosen, prereq_only, total_effort


def optimize_portfolio(report: IdeaTreeReport, budget: float, roadmap=None) -> Portfolio:
    """Select the highest-impact set of ideas whose total effort fits ``budget``,
    respecting dependency prerequisites (a dependent drags in its prereqs)."""
    if roadmap is None:
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = RoadmapSynthesizer().build(report)

    item_by_path = {i.branch_path: i for ph in roadmap.phases for i in ph.items}
    path_by_id = {i.id: i.branch_path for i in report.ideas}
    deps = infer_dependencies(report.ideas)  # id -> set(prereq ids)

    def _item(idea_id: str):
        return item_by_path.get(path_by_id.get(idea_id, ""))

    def _eff(idea_id: str) -> float:
        it = _item(idea_id)
        return it.effort if it else 1.0

    def _imp(idea_id: str) -> float:
        it = _item(idea_id)
        return it.impact if it else 0.0

    def _roi(idea_id: str) -> float:
        it = _item(idea_id)
        return it.roi if it else 0.0

    # Best ROI first; deterministic tie-break on (impact, branch_path).
    candidates = sorted(
        report.ideas,
        key=lambda i: (_roi(i.id), _imp(i.id), i.branch_path),
        reverse=True,
    )

    chosen, prereq_only, total_effort = _greedy_select(
        candidates, budget, deps, path_by_id, _eff
    )

    selected = [
        PortfolioItem(
            branch_path=path_by_id[i.id], title=i.title,
            impact=_imp(i.id), effort=_eff(i.id), roi=_roi(i.id),
            pulled_in_as_prerequisite=(i.id in prereq_only),
        )
        for i in report.ideas if i.id in chosen
    ]
    # Present highest-impact first (use --sequence for true execution order).
    selected.sort(key=lambda s: (-s.impact, s.branch_path))
    total_impact = round(sum(s.impact for s in selected), 4)
    return Portfolio(
        budget=budget,
        total_impact=total_impact,
        total_effort=total_effort,
        selected=selected,
        excluded_count=len(report.ideas) - len(selected),
    )


def render_portfolio_markdown(portfolio: Portfolio) -> str:
    """Render the optimal portfolio as a decision-ready plan."""
    lines = [f"# Optimal portfolio for an effort budget of {portfolio.budget}", ""]
    if not portfolio.selected:
        lines += ["_Nothing fits this budget — try a larger one._", ""]
        return "\n".join(lines)
    lines.append(
        f"**{len(portfolio.selected)} ideas** · total impact **{portfolio.total_impact}** · "
        f"effort {portfolio.total_effort}/{portfolio.budget} "
        f"({int(portfolio.utilization * 100)}% used) · "
        f"{portfolio.excluded_count} ideas left out"
    )
    lines.append("")
    lines.append("Maximizes impact within budget; prerequisites are pulled in automatically.\n")
    for s in portfolio.selected:
        tag = " _(prerequisite)_" if s.pulled_in_as_prerequisite else ""
        lines.append(
            f"- `{s.branch_path}` **{s.title}**{tag}  "
            f"(impact {s.impact} · effort {s.effort} · ROI {s.roi})"
        )
    lines.append("")
    return "\n".join(lines)
