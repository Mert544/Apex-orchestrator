from __future__ import annotations

from app.engine.idea_permutation import IdeaPermutationEngine
from app.engine.idea_portfolio import (
    Portfolio,
    optimize_portfolio,
    render_portfolio_markdown,
)
from app.engine.idea_roadmap import RoadmapItem, RoadmapPhase, Roadmap
from app.models.idea import IdeaNode, IdeaTreeReport


def _report_and_roadmap(specs):
    """specs: list of (id, branch_path, operator, subject, impact, effort)."""
    ideas, items = [], []
    for _id, bp, op, subj, impact, effort in specs:
        ideas.append(IdeaNode(id=_id, branch_path=bp, operator=op, subject=subj,
                              title=f"{op}: {subj}", value=impact))
        items.append(RoadmapItem(branch_path=bp, title=f"{op}: {subj}", subject=subj,
                                 phase="Stabilize", impact=impact, effort=effort,
                                 roi=round(impact / effort, 4), value=impact, kind="permutation",
                                 rationale=""))
    report = IdeaTreeReport(ideas=ideas)
    roadmap = Roadmap(objective="", project_root="/p",
                      phases=[RoadmapPhase(name="Stabilize", theme="t", items=items)])
    return report, roadmap


def test_picks_highest_impact_within_budget():
    report, rm = _report_and_roadmap([
        ("a", "x.a", "test", "app/a.py", 0.9, 0.5),
        ("b", "x.b", "test", "app/b.py", 0.8, 0.5),
        ("c", "x.c", "test", "app/c.py", 0.3, 0.5),
    ])
    p = optimize_portfolio(report, budget=1.0, roadmap=rm)
    assert isinstance(p, Portfolio)
    paths = {s.branch_path for s in p.selected}
    # Budget 1.0 fits exactly two 0.5-effort ideas -> the two highest-impact.
    assert paths == {"x.a", "x.b"}
    assert p.total_effort <= 1.0
    assert p.excluded_count == 1


def test_respects_budget_zero_selects_nothing():
    report, rm = _report_and_roadmap([("a", "x.a", "test", "app/a.py", 0.9, 0.5)])
    p = optimize_portfolio(report, budget=0.1, roadmap=rm)
    assert p.selected == []
    assert "Nothing fits" in render_portfolio_markdown(p)


def test_prerequisite_is_pulled_in():
    # Selecting the harden idea must also include the test it depends on.
    report, rm = _report_and_roadmap([
        ("t", "x.t", "test", "app/a.py", 0.5, 0.3),
        ("h", "x.h", "harden", "app/a.py", 0.95, 0.3),  # depends on x.t
    ])
    p = optimize_portfolio(report, budget=1.0, roadmap=rm)
    paths = {s.branch_path for s in p.selected}
    assert "x.h" in paths and "x.t" in paths  # prereq came along
    test_item = next(s for s in p.selected if s.branch_path == "x.t")
    assert test_item.pulled_in_as_prerequisite is True


def test_harden_excluded_if_prereq_bundle_too_big():
    # The harden+test bundle costs 0.6; a lone cheaper idea wins a 0.5 budget.
    report, rm = _report_and_roadmap([
        ("t", "x.t", "test", "app/a.py", 0.4, 0.3),
        ("h", "x.h", "harden", "app/a.py", 0.95, 0.3),  # needs x.t -> bundle 0.6
        ("c", "x.c", "test", "app/c.py", 0.5, 0.4),
    ])
    p = optimize_portfolio(report, budget=0.5, roadmap=rm)
    paths = {s.branch_path for s in p.selected}
    assert "x.h" not in paths            # its test+harden bundle (0.6) didn't fit
    assert p.total_effort <= 0.5         # budget respected
    assert p.selected                    # but something cheaper was still chosen


def test_utilization_and_to_dict():
    report, rm = _report_and_roadmap([
        ("a", "x.a", "test", "app/a.py", 0.9, 0.5),
        ("b", "x.b", "test", "app/b.py", 0.8, 0.5),
    ])
    p = optimize_portfolio(report, budget=2.0, roadmap=rm)
    assert 0.0 <= p.utilization <= 1.0
    d = p.to_dict()
    assert "selected" in d and "utilization" in d


def test_deterministic_and_end_to_end(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def r(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 5}, tmp_path).run()
    a = optimize_portfolio(rep, budget=2.0)
    b = optimize_portfolio(rep, budget=2.0)
    assert [s.branch_path for s in a.selected] == [s.branch_path for s in b.selected]
    assert a.total_effort <= 2.0 + 1e-6
    assert "Optimal portfolio" in render_portfolio_markdown(a)
