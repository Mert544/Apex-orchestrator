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


def _anchor(symbol: str) -> dict:
    return {"module": "m", "symbol": symbol, "line": 1, "metric": "cyclomatic 18"}


def test_all_anchored_coverage_is_one():
    ideas = [
        _n(id=str(i), subject=f"m{i}", value=0.5 + i * 0.05, anchors=[_anchor(f"f{i}")])
        for i in range(4)
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.anchored_count == 4
    assert s.anchor_coverage == 1.0
    assert 0.0 <= s.anchor_coverage <= 1.0
    # Fully anchored -> the "no anchors" observation must not fire.
    assert not any("No function-grain anchors" in o for o in s.observations)
    assert any("Function-grain:" in o for o in s.observations)


def test_none_anchored_coverage_is_zero():
    ideas = [_n(id=str(i), subject=f"m{i}", value=0.5 + i * 0.05) for i in range(4)]
    s = analyze_tree_shape(_report(ideas))
    assert s.anchored_count == 0
    assert s.anchor_coverage == 0.0
    assert 0.0 <= s.anchor_coverage <= 1.0
    assert any("No function-grain anchors" in o for o in s.observations)


def test_mixed_anchor_coverage():
    ideas = [
        _n(id="a", subject="a", value=0.9, anchors=[_anchor("fa")]),
        _n(id="b", subject="b", value=0.7, anchors=[_anchor("fb"), _anchor("fc")]),
        _n(id="c", subject="c", value=0.6),
        _n(id="d", subject="d", value=0.4),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.anchored_count == 2
    assert s.anchor_coverage == 0.5
    assert 0.0 <= s.anchor_coverage <= 1.0
    # Exactly half anchored -> high-coverage observation fires (>= 0.5).
    assert any("Function-grain:" in o for o in s.observations)


def test_low_anchor_coverage_no_high_observation():
    # One of four ideas anchored: below the high-coverage threshold and above 0,
    # so neither the "no anchors" nor the "function-grain" observation fires.
    ideas = [
        _n(id="a", subject="a", value=0.9, anchors=[_anchor("fa")]),
        _n(id="b", subject="b", value=0.7),
        _n(id="c", subject="c", value=0.6),
        _n(id="d", subject="d", value=0.4),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.anchored_count == 1
    assert s.anchor_coverage == 0.25
    assert not any("No function-grain anchors" in o for o in s.observations)
    assert not any("Function-grain:" in o for o in s.observations)


def test_empty_tree_anchor_coverage_is_safe():
    s = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert s.anchored_count == 0
    assert s.anchor_coverage == 0.0
    assert 0.0 <= s.anchor_coverage <= 1.0
    # Empty tree short-circuits to the empty observation only.
    assert not any("function-grain" in o.lower() for o in s.observations)


def test_single_anchored_idea_coverage_is_one():
    s = analyze_tree_shape(_report([_n(id="a", subject="a", anchors=[_anchor("fa")])]))
    assert s.anchored_count == 1
    assert s.anchor_coverage == 1.0
    assert 0.0 <= s.anchor_coverage <= 1.0


def test_single_unanchored_idea_coverage_is_zero():
    s = analyze_tree_shape(_report([_n(id="a", subject="a")]))
    assert s.anchored_count == 0
    assert s.anchor_coverage == 0.0
    assert any("No function-grain anchors" in o for o in s.observations)


def test_anchor_coverage_is_deterministic():
    ideas = [
        _n(id="a", subject="a", value=0.9, anchors=[_anchor("fa")]),
        _n(id="b", subject="b", value=0.6),
        _n(id="c", subject="c", value=0.3, anchors=[_anchor("fc")]),
    ]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.anchor_coverage == second.anchor_coverage
    assert first.anchored_count == second.anchored_count
    assert first.to_dict() == second.to_dict()


def test_anchor_coverage_surfaced_in_markdown():
    ideas = [
        _n(id="a", subject="a", value=0.9, anchors=[_anchor("fa")]),
        _n(id="b", subject="b", value=0.6),
    ]
    md = render_tree_shape_markdown(analyze_tree_shape(_report(ideas)))
    assert "Function-grain:" in md
    assert "1/2" in md
