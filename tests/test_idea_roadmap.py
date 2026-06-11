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
    # estimate_impact now seeds from the structural axes (relevance/novelty), not
    # from value, so the fixture must supply realistic, sub-1.0 structural signals
    # the way IdeaPermutationEngine._score does. Leaving them at the model default
    # of 1.0 would saturate the impact seed and mask the structural boosts under
    # the min(1.0, ...) cap — an artifact of the fixture, not of production runs.
    base = dict(id="i", title="t", subject="s", relevance=0.5, novelty=0.5,
                value=0.6, feasibility=0.6, depth=1)
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


def test_impact_is_independent_of_feasibility():
    # Core of the fix: feasibility must NOT enter impact (it owns the effort
    # axis). Two ideas identical in every structural signal (relevance, novelty,
    # label, kind, fan-in) but differing only in feasibility must get the SAME
    # impact — otherwise feasibility would be double-counted in ROI (raising
    # impact AND lowering effort at once). Effort and ROI still diverge.
    low_feas = _node(relevance=0.6, novelty=0.4, feasibility=0.2,
                     source_facts=["sensitive-path: app/auth.py"])
    high_feas = _node(relevance=0.6, novelty=0.4, feasibility=0.9,
                      source_facts=["sensitive-path: app/auth.py"])
    # Same structural seed + same boosts -> identical impact, regardless of feasibility.
    assert estimate_impact(low_feas) == estimate_impact(high_feas)
    # But effort still tracks feasibility, so ROI legitimately differs.
    assert estimate_effort(high_feas) < estimate_effort(low_feas)
    roi_high = estimate_impact(high_feas) / estimate_effort(high_feas)
    roi_low = estimate_impact(low_feas) / estimate_effort(low_feas)
    assert roi_high > roi_low


def test_impact_ignores_value_feasibility_component():
    # Decoupling is exact w.r.t. node.value: even if two nodes carry very
    # different `value` (because value folds in feasibility), impact depends only
    # on the structural axes. Same relevance/novelty -> same impact, different value.
    a = _node(relevance=0.5, novelty=0.5, value=0.3, feasibility=0.1)
    b = _node(relevance=0.5, novelty=0.5, value=0.9, feasibility=0.9)
    assert estimate_impact(a) == estimate_impact(b)


def test_impact_grounded_in_measured_fan_in():
    # A subject imported by many modules has real blast radius.
    base = _node(value=0.5)
    assert estimate_impact(base, fan_in=5) > estimate_impact(base, fan_in=0)
    # Fan-in contribution is capped so it can't dominate the score.
    assert estimate_impact(base, fan_in=100) <= 1.0
    assert estimate_impact(base, fan_in=100) == estimate_impact(base, fan_in=5)


def test_effort_uses_report_metrics_stat():
    # The synthesizer reads per-module metrics from report.stats and inflates the
    # effort of a large, complex subject relative to a tiny one of equal value.
    ideas = [
        _node(id="big", branch_path="x.b", subject="app/big.py", value=0.6,
              feasibility=0.7, operator="harden", source_facts=["sensitive-path: app/big.py"]),
        _node(id="small", branch_path="x.s", subject="app/small.py", value=0.6,
              feasibility=0.7, operator="harden", source_facts=["sensitive-path: app/small.py"]),
    ]
    rep = IdeaTreeReport(ideas=ideas, stats={"metrics": {
        "app/big.py": {"loc": 800, "complexity": 80},
        "app/small.py": {"loc": 20, "complexity": 1},
    }})
    rm = RoadmapSynthesizer().build(rep)
    items = {i.subject: i for ph in rm.phases for i in ph.items}
    assert items["app/big.py"].effort > items["app/small.py"].effort
    assert items["app/big.py"].loc == 800
    # Equal value + impact, but the cheap module wins on ROI.
    assert items["app/small.py"].roi > items["app/big.py"].roi


def test_end_to_end_synthesizer_consumes_engine_output(tmp_path):
    # End-to-end: the synthesizer must build a sane roadmap from *real* engine
    # output. NOTE: the engine (IdeaPermutationEngine.run) does not currently
    # attach "metrics"/"fan_in" to report.stats — that wiring lives in
    # idea_permutation.py, which is out of scope for this fix. The synthesizer
    # already degrades gracefully when those stats are absent (loc/fan_in default
    # to 0), so we assert the in-scope contract: a valid, bounded roadmap is
    # produced. The metrics-driven behavior is exercised directly against a
    # constructed report.stats in test_effort_uses_report_metrics_stat and
    # test_build_uses_report_fan_in_stat.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def core(x):\n    if x:\n        return 1\n    return 0\n"
    )
    (tmp_path / "app" / "user.py").write_text("import app.core\ndef u():\n    return app.core.core(1)\n")
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 1}, tmp_path).run()
    rm = RoadmapSynthesizer().build(rep)
    assert isinstance(rm, Roadmap)
    assert rm.stats["total_items"] == len(rep.ideas) > 0
    # Every produced item stays in sane, decoupled bounds.
    for ph in rm.phases:
        for i in ph.items:
            assert 0.0 <= i.impact <= 1.0
            assert 0.1 <= i.effort <= 1.0
            assert i.roi == round(i.impact / i.effort, 4)


def test_build_uses_report_fan_in_stat():
    # The synthesizer reads fan-in from report.stats and applies it per subject,
    # stripping any " :: facet" suffix back to the base module.
    ideas = [
        _node(id="hub", branch_path="x.h", subject="app/core.py", value=0.5,
              operator="harden", source_facts=["dependency-hub: app/core.py"]),
        _node(id="leaf", branch_path="x.l", subject="app/leaf.py", value=0.5,
              operator="harden", source_facts=["sensitive-path: app/leaf.py"]),
    ]
    rep = IdeaTreeReport(ideas=ideas, stats={"fan_in": {"app/core.py": 4}})
    rm = RoadmapSynthesizer().build(rep)
    items = {i.subject: i for ph in rm.phases for i in ph.items}
    # The heavily-imported hub outscores the leaf on impact, thanks to fan-in.
    assert items["app/core.py"].impact > items["app/leaf.py"].impact


def test_effort_is_floored_and_depth_sensitive():
    shallow = _node(feasibility=0.9, depth=0)
    deep = _node(feasibility=0.9, depth=3)
    assert estimate_effort(deep) > estimate_effort(shallow)
    # Floor keeps ROI bounded even for a perfectly-feasible shallow idea.
    assert estimate_effort(_node(feasibility=1.0, depth=0)) >= 0.1


def test_effort_grounded_in_size_and_complexity():
    base = _node(feasibility=0.7, depth=1)
    small = estimate_effort(base, loc=20, complexity=2)
    big = estimate_effort(base, loc=800, complexity=80)
    assert big > small
    # Both size and complexity contributions are capped (can't exceed ceiling).
    assert estimate_effort(base, loc=100000, complexity=100000) <= 1.0
    # A big, branch-heavy module raises effort over the size-less baseline.
    assert estimate_effort(base, loc=600, complexity=60) > estimate_effort(base)


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


def test_complexity_hotspot_is_high_impact_and_stabilize():
    # A de-risk-the-hotspot idea is high structural impact and belongs in the
    # Stabilize phase (make it safe before changing it).
    plain = _node(source_facts=["top-directory: app"])
    hot = _node(operator="root",
                source_facts=["complexity-hotspot: app/core.py (high complexity x fan-in, thin tests)"])
    assert estimate_impact(hot) > estimate_impact(plain)
    assert classify_phase(hot) == STABILIZE


def test_hotspot_function_routes_to_stabilize_with_high_impact():
    f = _node(source_facts=["hotspot-function: app/core.py::Engine.crunch (complexity 14, line 40, no direct tests)"])
    plain = _node()
    assert classify_phase(f) == "Stabilize"
    assert estimate_impact(f) > estimate_impact(plain)
