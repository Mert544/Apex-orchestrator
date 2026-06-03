from __future__ import annotations

from dataclasses import dataclass

from app.engine.idea_pareto import (
    ParetoPoint,
    frontier_from_roadmap,
    pareto_frontier,
    render_pareto_markdown,
)
from app.engine.idea_roadmap import RoadmapSynthesizer
from app.engine.idea_permutation import IdeaPermutationEngine


@dataclass
class _Item:
    branch_path: str
    title: str
    impact: float
    effort: float
    value: float
    roi: float
    phase: str = "Stabilize"


def test_empty_frontier():
    assert pareto_frontier([]) == []
    assert "No ideas" in render_pareto_markdown([])


def test_dominated_idea_is_excluded():
    # b beats a on all three objectives -> a is dominated and dropped.
    a = _Item("x.a", "weak", impact=0.4, effort=0.6, value=0.4, roi=0.67)
    b = _Item("x.b", "strong", impact=0.9, effort=0.2, value=0.9, roi=4.5)
    front = pareto_frontier([a, b])
    paths = {p.branch_path for p in front}
    assert "x.b" in paths and "x.a" not in paths


def test_tradeoffs_both_survive():
    # High impact/high effort vs low impact/low effort: neither dominates.
    big = _Item("x.big", "architectural", impact=1.0, effort=0.9, value=0.8, roi=1.11)
    small = _Item("x.small", "cleanup", impact=0.4, effort=0.1, value=0.5, roi=4.0)
    front = pareto_frontier([big, small])
    assert {p.branch_path for p in front} == {"x.big", "x.small"}


def test_reasons_annotated():
    big = _Item("x.big", "arch", impact=1.0, effort=0.9, value=0.6, roi=1.1)
    cheap = _Item("x.cheap", "tiny", impact=0.5, effort=0.1, value=0.9, roi=5.0)
    front = pareto_frontier([big, cheap])
    by_path = {p.branch_path: p for p in front}
    assert "highest impact" in by_path["x.big"].reasons
    assert "lowest effort" in by_path["x.cheap"].reasons
    assert "best ROI" in by_path["x.cheap"].reasons


def test_identical_vectors_deduped():
    a = _Item("x.a", "a", impact=0.8, effort=0.3, value=0.7, roi=2.67)
    b = _Item("x.b", "b", impact=0.8, effort=0.3, value=0.7, roi=2.67)
    front = pareto_frontier([a, b])
    assert len(front) == 1  # identical objective vectors collapse to one point


def test_frontier_is_deterministic():
    items = [
        _Item("x.a", "a", 1.0, 0.2, 0.9, 5.0),
        _Item("x.b", "b", 0.6, 0.1, 0.5, 6.0),
        _Item("x.c", "c", 0.3, 0.5, 0.3, 0.6),
    ]
    assert [p.branch_path for p in pareto_frontier(items)] == \
           [p.branch_path for p in pareto_frontier(items)]


def test_end_to_end_frontier_from_roadmap(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("def run(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 4}, tmp_path).run()
    front = frontier_from_roadmap(RoadmapSynthesizer().build(rep))
    assert front and all(isinstance(p, ParetoPoint) for p in front)
    # The frontier is a strict subset of all ideas.
    assert len(front) <= rep.stats["total_ideas"]
    md = render_pareto_markdown(front, total_ideas=rep.stats["total_ideas"])
    assert "Efficient frontier" in md
