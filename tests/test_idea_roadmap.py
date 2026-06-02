from __future__ import annotations

from app.engine.idea_roadmap import (
    EVOLVE,
    PHASE_ORDER,
    REFINE,
    SECURE,
    STABILIZE,
    Roadmap,
    RoadmapSynthesizer,
    classify_phase,
    estimate_effort,
    estimate_impact,
    render_roadmap_markdown,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _node(**kw) -> IdeaNode:
    base = dict(id="i", title="t", subject="s", value=0.6, feasibility=0.6, depth=1)
    base.update(kw)
    return IdeaNode(**base)


# --- impact / effort ----------------------------------------------------------

def test_impact_boosted_by_structural_risk():
    plain = _node(source_facts=["entrypoint: app/cli.py"])
    fragile = _node(source_facts=["fragile: app/core.py (high in-degree, thin tests)"])
    assert estimate_impact(fragile) > estimate_impact(plain)
    assert estimate_impact(fragile) <= 1.0


def test_impact_boosted_by_cycle_and_kind():
    cyc = _node(kind="pair", source_facts=["dependency-cycle"])
    assert estimate_impact(cyc) >= estimate_impact(_node())


def test_effort_is_floored_and_depth_sensitive():
    shallow = _node(feasibility=0.9, depth=0)
    deep = _node(feasibility=0.9, depth=3)
    assert estimate_effort(deep) > estimate_effort(shallow)
    # Floor keeps ROI bounded even for a perfectly-feasible shallow idea.
    assert estimate_effort(_node(feasibility=1.0, depth=0)) >= 0.1


# --- phase classification (the engineering thesis) ----------------------------

def test_test_lens_routes_to_stabilize():
    assert classify_phase(_node(operator="test", source_facts=["untested: m.py"])) == STABILIZE


def test_harden_on_sensitive_path_routes_to_secure():
    n = _node(operator="harden", source_facts=["sensitive-path: app/auth.py"])
    assert classify_phase(n) == SECURE


def test_synthesis_routes_to_secure_and_pair_to_evolve():
    assert classify_phase(_node(kind="synthesis", operator="synthesis")) == SECURE
    assert classify_phase(_node(kind="pair", operator="synthesis")) == EVOLVE


def test_evolve_and_refine_lenses():
    assert classify_phase(_node(operator="extend", source_facts=["dependency-hub: x"])) == EVOLVE
    assert classify_phase(_node(operator="document", source_facts=["config: c.toml"])) == REFINE


# --- end-to-end synthesis -----------------------------------------------------

def _report() -> IdeaTreeReport:
    ideas = [
        _node(id="1", branch_path="x.a", operator="test", value=0.8, feasibility=0.85,
              source_facts=["untested: app/m.py"]),
        _node(id="2", branch_path="x.b", operator="harden", value=0.7, feasibility=0.6,
              source_facts=["sensitive-path: app/auth.py"]),
        _node(id="3", branch_path="x.c", operator="extend", value=0.6, feasibility=0.5,
              source_facts=["dependency-hub: app/core.py"]),
        _node(id="4", branch_path="x.d", operator="document", value=0.4, feasibility=0.85,
              source_facts=["config: pyproject.toml"]),
    ]
    return IdeaTreeReport(objective="harden auth", project_root="/proj", ideas=ideas)


def test_build_orders_phases_and_computes_stats():
    rm = RoadmapSynthesizer().build(_report())
    assert isinstance(rm, Roadmap)
    names = [p.name for p in rm.phases]
    # Phases appear in canonical engineering order.
    assert names == [n for n in PHASE_ORDER if n in names]
    assert rm.stats["total_items"] == 4
    assert set(rm.stats["phase_counts"]) == set(names)
    # Each of the four ideas landed in a distinct phase.
    assert names == [STABILIZE, SECURE, EVOLVE, REFINE]


def test_items_within_phase_sorted_by_roi():
    ideas = [
        _node(id="lo", branch_path="x.lo", operator="test", value=0.3, feasibility=0.4,
              source_facts=["untested: a.py"]),
        _node(id="hi", branch_path="x.hi", operator="test", value=0.9, feasibility=0.9,
              source_facts=["fragile: b.py (high in-degree, thin tests)"]),
    ]
    rm = RoadmapSynthesizer().build(IdeaTreeReport(ideas=ideas))
    stabilize = next(p for p in rm.phases if p.name == STABILIZE)
    rois = [i.roi for i in stabilize.items]
    assert rois == sorted(rois, reverse=True)
    assert stabilize.items[0].branch_path == "x.hi"


def test_quick_wins_are_high_roi_only():
    rm = RoadmapSynthesizer(quick_win_count=2, quick_win_min_roi=2.0).build(_report())
    assert len(rm.quick_wins) <= 2
    assert all(i.roi >= 2.0 for i in rm.quick_wins)


def test_render_markdown_has_phases_and_quick_wins():
    rm = RoadmapSynthesizer().build(_report())
    md = render_roadmap_markdown(rm)
    assert "Engineering Roadmap" in md
    assert "Phase 1: Stabilize" in md
    assert "harden auth" in md  # objective surfaced


def test_empty_report_is_safe():
    rm = RoadmapSynthesizer().build(IdeaTreeReport(ideas=[]))
    assert rm.phases == []
    assert rm.stats["total_items"] == 0
    assert rm.stats["mean_roi"] == 0.0
    # Rendering an empty roadmap still produces a header, not a crash.
    assert "Engineering Roadmap" in render_roadmap_markdown(rm)


def test_roadmap_to_dict_roundtrips():
    rm = RoadmapSynthesizer().build(_report())
    d = rm.to_dict()
    assert d["objective"] == "harden auth"
    assert isinstance(d["phases"], list) and d["phases"]
    assert "items" in d["phases"][0]
