from __future__ import annotations

from app.engine.idea_investment import (
    CurvePoint,
    investment_curve,
    render_investment_markdown,
)
from app.engine.idea_permutation import IdeaPermutationEngine
from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase
from app.models.idea import IdeaNode, IdeaTreeReport


def _report_and_roadmap(specs):
    ideas, items = [], []
    for _id, bp, impact, effort in specs:
        ideas.append(IdeaNode(id=_id, branch_path=bp, operator="test", subject=f"app/{_id}.py",
                              title=f"Test: {_id}", value=impact))
        items.append(RoadmapItem(branch_path=bp, title=f"Test: {_id}", subject=f"app/{_id}.py",
                                 phase="Stabilize", impact=impact, effort=effort,
                                 roi=round(impact / effort, 4), value=impact, kind="permutation",
                                 rationale=""))
    report = IdeaTreeReport(ideas=ideas)
    roadmap = Roadmap(objective="", project_root="/p",
                      phases=[RoadmapPhase(name="Stabilize", theme="t", items=items)])
    return report, roadmap


def test_empty_curve():
    assert investment_curve(IdeaTreeReport(ideas=[])) == []
    assert "No ideas" in render_investment_markdown([])


def test_curve_is_monotincreasing_impact():
    report, rm = _report_and_roadmap([
        ("a", "x.a", 0.9, 0.5), ("b", "x.b", 0.7, 0.5),
        ("c", "x.c", 0.5, 0.5), ("d", "x.d", 0.3, 0.5),
    ])
    pts = investment_curve(report, steps=4, roadmap=rm)
    assert len(pts) == 4
    impacts = [p.total_impact for p in pts]
    # More budget never buys less impact.
    assert impacts == sorted(impacts)
    # The last point spends (close to) the full effort and takes all ideas.
    assert pts[-1].n_ideas == 4


def test_diminishing_returns_and_knee():
    # Front-loaded impact: first ideas are cheap & strong, later ones weak.
    report, rm = _report_and_roadmap([
        ("a", "x.a", 1.0, 0.5), ("b", "x.b", 0.9, 0.5),
        ("c", "x.c", 0.2, 0.5), ("d", "x.d", 0.1, 0.5),
    ])
    pts = investment_curve(report, steps=4, roadmap=rm)
    # Marginal return should trend downward (diminishing returns).
    assert pts[0].marginal_return >= pts[-1].marginal_return
    # Exactly one knee is marked.
    assert sum(1 for p in pts if p.is_knee) == 1


def test_render_has_sparkline_and_recommendation():
    report, rm = _report_and_roadmap([("a", "x.a", 0.9, 0.5), ("b", "x.b", 0.4, 0.5)])
    md = render_investment_markdown(investment_curve(report, steps=2, roadmap=rm))
    assert "Investment curve" in md
    assert "Recommended investment" in md
    assert "█" in md  # sparkline rendered


def test_deterministic_end_to_end(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def r(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 5}, tmp_path).run()
    a = investment_curve(rep)
    b = investment_curve(rep)
    assert all(isinstance(p, CurvePoint) for p in a)
    assert [p.to_dict() for p in a] == [p.to_dict() for p in b]
