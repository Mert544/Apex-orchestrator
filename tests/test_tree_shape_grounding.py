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


def test_all_grounded_ratio_is_one():
    ideas = [
        _n(id=str(i), subject=f"m{i}", value=0.5 + i * 0.05, source_facts=["fact"])
        for i in range(4)
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.grounded_count == 4
    assert s.grounding_ratio == 1.0
    assert 0.0 <= s.grounding_ratio <= 1.0
    # Fully grounded -> no weak-grounding observation.
    assert not any("Weakly grounded" in o for o in s.observations)


def test_none_grounded_ratio_is_zero():
    ideas = [_n(id=str(i), subject=f"m{i}", value=0.5 + i * 0.05) for i in range(4)]
    s = analyze_tree_shape(_report(ideas))
    assert s.grounded_count == 0
    assert s.grounding_ratio == 0.0
    assert 0.0 <= s.grounding_ratio <= 1.0
    assert any("Weakly grounded" in o for o in s.observations)


def test_mixed_grounding_ratio():
    ideas = [
        _n(id="a", subject="a", value=0.9, source_facts=["f1"]),
        _n(id="b", subject="b", value=0.7, source_facts=["f2", "f3"]),
        _n(id="c", subject="c", value=0.6),
        _n(id="d", subject="d", value=0.4),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.grounded_count == 2
    assert s.grounding_ratio == 0.5
    assert 0.0 <= s.grounding_ratio <= 1.0


def test_empty_tree_grounding_is_safe():
    s = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert s.grounded_count == 0
    assert s.grounding_ratio == 0.0
    assert 0.0 <= s.grounding_ratio <= 1.0


def test_grounding_is_deterministic():
    ideas = [
        _n(id="a", subject="a", value=0.9, source_facts=["f1"]),
        _n(id="b", subject="b", value=0.6),
        _n(id="c", subject="c", value=0.3, source_facts=["f2"]),
    ]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.grounding_ratio == second.grounding_ratio
    assert first.grounded_count == second.grounded_count
    assert first.to_dict() == second.to_dict()


def test_grounding_surfaced_in_markdown():
    ideas = [
        _n(id="a", subject="a", value=0.9, source_facts=["f1"]),
        _n(id="b", subject="b", value=0.6),
    ]
    md = render_tree_shape_markdown(analyze_tree_shape(_report(ideas)))
    assert "Grounding:" in md
    assert "1/2" in md
