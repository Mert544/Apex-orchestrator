from __future__ import annotations

from app.engine.idea_tree_shape import analyze_tree_shape
from app.models.idea import IdeaNode, IdeaTreeReport


def _n(**kw) -> IdeaNode:
    base = dict(id="i", title="t", subject="s", value=0.5, depth=0)
    base.update(kw)
    return IdeaNode(**base)


def _report(ideas) -> IdeaTreeReport:
    return IdeaTreeReport(ideas=ideas)


# ---- empty-operator branch ---------------------------------------------------

def test_blank_operators_yield_empty_dominant_lens():
    # Every idea carries an empty operator, so the operators Counter is empty and
    # the dominant-lens fields fall back to ("", 0.0) rather than crashing.
    ideas = [
        _n(id=str(i), subject=f"m{i}", value=0.5 + i * 0.05, operator="")
        for i in range(4)
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.distinct_operators == 0
    assert s.dominant_operator == ""
    assert s.dominant_operator_share == 0.0
    # With no distinct operators the single-lens observation still fires.
    assert any("single lens" in o.lower() for o in s.observations)


def test_blank_operators_are_deterministic():
    ideas = [_n(id=str(i), subject=f"m{i}", value=0.3 + i * 0.1, operator="") for i in range(3)]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.to_dict() == second.to_dict()


# ---- subject-concentration clump observation ---------------------------------

def test_high_concentration_without_dominant_subject_observation():
    # Distribution A:2, B:1, C:1 over 4 ideas:
    #   top_subject_share = 0.5 (no single dominator)
    #   distinct_subjects = 3
    #   Herfindahl = .25 + .0625 + .0625 = .375 (>= 0.34)
    # -> the "ideas clump onto a handful of subjects" observation fires.
    ideas = [
        _n(id="1", subject="A", depth=0, value=0.5),
        _n(id="2", subject="A", depth=1, parent_id="1", value=0.6),
        _n(id="3", subject="B", depth=1, parent_id="1", value=0.7),
        _n(id="4", subject="C", depth=2, parent_id="3", value=0.8),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.distinct_subjects == 3
    assert s.top_subject_share == 0.5
    assert s.subject_concentration == 0.375
    assert any("clump onto a handful of subjects" in o for o in s.observations)
    # No single subject crosses the 0.5 dominance threshold, so the
    # narrow-coverage "One subject dominates" observation must not fire.
    assert not any("coverage is narrow" in o for o in s.observations)


def test_concentration_observation_is_deterministic():
    ideas = [
        _n(id="1", subject="A", depth=0, value=0.5),
        _n(id="2", subject="A", depth=1, parent_id="1", value=0.6),
        _n(id="3", subject="B", depth=1, parent_id="1", value=0.7),
        _n(id="4", subject="C", depth=2, parent_id="3", value=0.8),
    ]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.observations == second.observations
