from __future__ import annotations

from app.engine.idea_tree_shape import (
    analyze_tree_shape,
    render_tree_shape_markdown,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _n(**kw) -> IdeaNode:
    base = dict(id="i", title="t", subject="s", value=0.5, depth=0)
    base.update(kw)
    return IdeaNode(**base)


def _report(ideas) -> IdeaTreeReport:
    return IdeaTreeReport(ideas=ideas)


def test_single_operator_tree():
    ideas = [
        _n(id=str(i), subject=f"m{i}", value=0.4 + i * 0.05, operator="untangle")
        for i in range(4)
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.distinct_operators == 1
    assert s.dominant_operator == "untangle"
    assert s.dominant_operator_share == 1.0
    assert 0.0 <= s.dominant_operator_share <= 1.0
    # A single lens everywhere -> single-lens observation fires.
    assert any("single lens" in o.lower() for o in s.observations)


def test_multi_operator_tree():
    ideas = [
        _n(id="a", subject="a", value=0.9, operator="untangle"),
        _n(id="b", subject="b", value=0.7, operator="harden"),
        _n(id="c", subject="c", value=0.6, operator="test"),
        _n(id="d", subject="d", value=0.4, operator="untangle"),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.distinct_operators == 3
    # Tie-break is deterministic: count desc, name asc -> "untangle" (count 2).
    assert s.dominant_operator == "untangle"
    assert s.dominant_operator_share == 0.5
    assert 0.0 <= s.dominant_operator_share <= 1.0
    # Spread across lenses, but the top lens is exactly half -> not > 0.5,
    # so the "one lens drives most" observation must NOT fire.
    assert not any("drives most" in o for o in s.observations)


def test_dominant_operator_observation_fires():
    ideas = [
        _n(id="a", subject="a", value=0.9, operator="untangle"),
        _n(id="b", subject="b", value=0.7, operator="untangle"),
        _n(id="c", subject="c", value=0.6, operator="untangle"),
        _n(id="d", subject="d", value=0.4, operator="harden"),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.distinct_operators == 2
    assert s.dominant_operator == "untangle"
    assert s.dominant_operator_share == 0.75
    assert any("drives most" in o for o in s.observations)


def test_empty_tree_diversity_is_safe():
    s = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert s.distinct_operators == 0
    assert s.dominant_operator == ""
    assert s.dominant_operator_share == 0.0
    assert 0.0 <= s.dominant_operator_share <= 1.0


def test_diversity_tie_break_is_name_ascending():
    # Two operators each used once -> tie on count, break on name ascending.
    ideas = [
        _n(id="a", subject="a", value=0.9, operator="zeta"),
        _n(id="b", subject="b", value=0.6, operator="alpha"),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.distinct_operators == 2
    assert s.dominant_operator == "alpha"
    assert s.dominant_operator_share == 0.5


def test_diversity_is_deterministic():
    ideas = [
        _n(id="a", subject="a", value=0.9, operator="untangle"),
        _n(id="b", subject="b", value=0.6, operator="harden"),
        _n(id="c", subject="c", value=0.3, operator="untangle"),
    ]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.distinct_operators == second.distinct_operators
    assert first.dominant_operator == second.dominant_operator
    assert first.dominant_operator_share == second.dominant_operator_share
    assert first.to_dict() == second.to_dict()


def test_diversity_surfaced_in_markdown():
    ideas = [
        _n(id="a", subject="a", value=0.9, operator="untangle"),
        _n(id="b", subject="b", value=0.6, operator="harden"),
    ]
    md = render_tree_shape_markdown(analyze_tree_shape(_report(ideas)))
    assert "Lens diversity:" in md
    assert "untangle" in md or "harden" in md
