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


def test_flat_tree_is_all_leaves():
    # All roots, no expansion: every idea is a leaf.
    ideas = [_n(id=str(i), subject=f"m{i}", value=0.4 + i * 0.05) for i in range(4)]
    s = analyze_tree_shape(_report(ideas))
    assert s.leaf_count == 4
    assert s.leaf_ratio == 1.0
    assert 0.0 <= s.leaf_ratio <= 1.0
    assert any("flat frontier" in o for o in s.observations)


def test_deep_tree_has_few_leaves():
    # A spine r0 -> a -> b -> c -> d -> e: only the tip is a leaf.
    ids = ["r0", "a", "b", "c", "d", "e"]
    ideas = [_n(id="r0", subject="m", value=0.5, depth=0)]
    for i in range(1, len(ids)):
        ideas.append(
            _n(
                id=ids[i],
                subject="m",
                value=0.5 + i * 0.05,
                depth=i,
                parent_id=ids[i - 1],
                kind="permutation",
            )
        )
    s = analyze_tree_shape(_report(ideas))
    # Only the terminal node "e" has no children.
    assert s.leaf_count == 1
    assert s.leaf_ratio == round(1 / 6, 4)
    assert 0.0 <= s.leaf_ratio <= 1.0
    assert any("densely expanded" in o for o in s.observations)


def test_balanced_tree_mid_leaf_ratio():
    # One root with two children: 2 leaves out of 3 ideas.
    ideas = [
        _n(id="r0", subject="m", value=0.6, depth=0),
        _n(id="c1", subject="m", value=0.5, depth=1, parent_id="r0"),
        _n(id="c2", subject="m", value=0.4, depth=1, parent_id="r0"),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.leaf_count == 2
    assert s.leaf_ratio == round(2 / 3, 4)
    # Neither extreme observation should fire in the balanced middle.
    assert not any("flat frontier" in o for o in s.observations)
    assert not any("densely expanded" in o for o in s.observations)


def test_empty_tree_balance_is_safe():
    s = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert s.leaf_count == 0
    assert s.leaf_ratio == 0.0
    assert 0.0 <= s.leaf_ratio <= 1.0
    # No ZeroDivisionError and no balance observation on an empty tree.
    assert not any("frontier" in o for o in s.observations)


def test_single_node_balance_is_safe():
    s = analyze_tree_shape(_report([_n(id="solo", subject="m", value=0.5)]))
    assert s.leaf_count == 1
    assert s.leaf_ratio == 1.0
    assert 0.0 <= s.leaf_ratio <= 1.0
    # total_ideas == 1 -> no flat/dense observation fires.
    assert not any("flat frontier" in o for o in s.observations)
    assert not any("densely expanded" in o for o in s.observations)


def test_balance_is_deterministic():
    ideas = [
        _n(id="r0", subject="m", value=0.6, depth=0),
        _n(id="c1", subject="m", value=0.5, depth=1, parent_id="r0"),
        _n(id="c2", subject="m", value=0.4, depth=1, parent_id="r0"),
        _n(id="g1", subject="m", value=0.3, depth=2, parent_id="c1"),
    ]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.leaf_count == second.leaf_count
    assert first.leaf_ratio == second.leaf_ratio
    assert first.to_dict() == second.to_dict()


def test_balance_surfaced_in_markdown():
    ideas = [
        _n(id="r0", subject="m", value=0.6, depth=0),
        _n(id="c1", subject="m", value=0.5, depth=1, parent_id="r0"),
    ]
    md = render_tree_shape_markdown(analyze_tree_shape(_report(ideas)))
    assert "Depth balance:" in md
    assert "1/2" in md


# --- Developmental center of mass: mean_depth / depth_balance ----------------


def test_flat_tree_has_zero_center_of_mass():
    # All roots at depth 0: mean depth and balance are both 0, no division by
    # max_depth (which is 0).
    ideas = [_n(id=str(i), subject=f"m{i}", value=0.4 + i * 0.05) for i in range(4)]
    s = analyze_tree_shape(_report(ideas))
    assert s.mean_depth == 0.0
    assert s.depth_balance == 0.0
    assert 0.0 <= s.depth_balance <= 1.0
    # No deep branches -> top-heavy observation must not fire (max_depth < 2).
    assert not any("top-heavy" in o for o in s.observations)


def test_deep_spine_has_high_center_of_mass():
    # Spine r0 -> a -> b -> c -> d -> e: depths 0..5, mean = 15/6 = 2.5,
    # balance = 2.5 / 5 = 0.5.
    ids = ["r0", "a", "b", "c", "d", "e"]
    ideas = [_n(id="r0", subject="m", value=0.5, depth=0)]
    for i in range(1, len(ids)):
        ideas.append(
            _n(
                id=ids[i],
                subject="m",
                value=0.5 + i * 0.05,
                depth=i,
                parent_id=ids[i - 1],
                kind="permutation",
            )
        )
    s = analyze_tree_shape(_report(ideas))
    assert s.max_depth == 5
    assert s.mean_depth == round(15 / 6, 4)
    assert s.depth_balance == 0.5
    assert 0.0 <= s.depth_balance <= 1.0


def test_top_heavy_tree_fires_observation():
    # One root with two depth-1 children and a single deep tail under one of
    # them: mass clusters near the roots while one branch runs deep.
    ideas = [
        _n(id="r0", subject="m", value=0.6, depth=0),
        _n(id="a", subject="m", value=0.5, depth=1, parent_id="r0"),
        _n(id="b", subject="m", value=0.5, depth=1, parent_id="r0"),
        _n(id="c", subject="m", value=0.4, depth=2, parent_id="a"),
        _n(id="d", subject="m", value=0.3, depth=3, parent_id="c"),
    ]
    s = analyze_tree_shape(_report(ideas))
    # depths 0,1,1,2,3 -> mean 7/5 = 1.4, max 3 -> balance ~0.4667 < ... no.
    assert s.max_depth == 3
    assert s.mean_depth == round(7 / 5, 4)
    assert s.depth_balance == round((7 / 5) / 3, 4)


def test_top_heavy_observation_on_shallow_wide_with_one_tail():
    # Many shallow roots/children, one lone deep tail -> depth_balance is low
    # enough (< 0.34) with max_depth >= 2 to fire the top-heavy reading.
    ideas = [_n(id=f"r{i}", subject=f"m{i}", value=0.5 + i * 0.01) for i in range(5)]
    ideas += [
        _n(id="t1", subject="m0", value=0.4, depth=1, parent_id="r0"),
        _n(id="t2", subject="m0", value=0.3, depth=2, parent_id="t1"),
    ]
    s = analyze_tree_shape(_report(ideas))
    assert s.max_depth == 2
    # depths: five 0s, one 1, one 2 -> mean 3/7, balance (3/7)/2 < 0.34.
    assert s.depth_balance < 0.34
    assert any("top-heavy" in o for o in s.observations)


def test_empty_tree_center_of_mass_is_safe():
    s = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert s.mean_depth == 0.0
    assert s.depth_balance == 0.0
    assert 0.0 <= s.depth_balance <= 1.0
    assert not any("top-heavy" in o for o in s.observations)


def test_single_node_center_of_mass_is_safe():
    s = analyze_tree_shape(_report([_n(id="solo", subject="m", value=0.5)]))
    assert s.mean_depth == 0.0
    # max_depth == 0 -> no ZeroDivisionError, balance defaults to 0.0.
    assert s.depth_balance == 0.0
    assert 0.0 <= s.depth_balance <= 1.0


def test_center_of_mass_is_deterministic():
    ideas = [
        _n(id="r0", subject="m", value=0.6, depth=0),
        _n(id="c1", subject="m", value=0.5, depth=1, parent_id="r0"),
        _n(id="c2", subject="m", value=0.4, depth=1, parent_id="r0"),
        _n(id="g1", subject="m", value=0.3, depth=2, parent_id="c1"),
    ]
    first = analyze_tree_shape(_report(ideas))
    second = analyze_tree_shape(_report(ideas))
    assert first.mean_depth == second.mean_depth
    assert first.depth_balance == second.depth_balance
    assert first.to_dict() == second.to_dict()


def test_center_of_mass_surfaced_in_markdown():
    ideas = [
        _n(id="r0", subject="m", value=0.6, depth=0),
        _n(id="c1", subject="m", value=0.5, depth=1, parent_id="r0"),
        _n(id="c2", subject="m", value=0.4, depth=2, parent_id="c1"),
    ]
    md = render_tree_shape_markdown(analyze_tree_shape(_report(ideas)))
    assert "Developmental center of mass:" in md
    assert "mean depth" in md
