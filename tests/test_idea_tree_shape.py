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


def test_empty_tree_is_safe():
    shape = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert shape.total_ideas == 0
    assert "Empty" in shape.observations[0]
    assert "Idea Tree Shape" in render_tree_shape_markdown(shape)


def test_counts_kinds_depths_and_branching():
    ideas = [
        _n(id="r", subject="a", depth=0, value=0.9),
        _n(id="c1", parent_id="r", subject="a", depth=1, value=0.7),
        _n(id="c2", parent_id="r", subject="a", depth=1, value=0.6),
        _n(id="g1", parent_id="c1", subject="a", depth=2, value=0.4, kind="facet"),
    ]
    s = analyze_tree_shape(IdeaTreeReport(ideas=ideas))
    assert s.total_ideas == 4
    assert s.roots == 1
    assert s.max_depth == 2
    assert s.by_kind == {"permutation": 3, "facet": 1}
    assert s.depth_distribution == {0: 1, 1: 2, 2: 1}
    # Two parents (r has 2 children, c1 has 1) -> 3 children / 2 parents = 1.5.
    assert s.branching_factor == 1.5
    assert s.facet_penetration == 0.25


def test_dominant_subject_observation():
    ideas = [_n(id=str(i), subject="hub", depth=i % 2, value=0.5 + i * 0.01) for i in range(6)]
    s = analyze_tree_shape(IdeaTreeReport(ideas=ideas))
    assert s.top_subject == "hub"
    assert s.top_subject_share == 1.0
    assert any("dominates" in o for o in s.observations)


def test_shallow_and_no_facet_observations():
    ideas = [_n(id=str(i), subject=f"m{i}", depth=0, value=0.5) for i in range(4)]
    s = analyze_tree_shape(IdeaTreeReport(ideas=ideas))
    assert any("shallow" in o.lower() for o in s.observations)
    assert any("facet" in o.lower() for o in s.observations)


def test_clustered_scores_observation():
    # All identical values -> clustered-scores reading.
    ideas = [_n(id=str(i), subject=f"m{i}", depth=1, parent_id="r", value=0.5) for i in range(9)]
    ideas.append(_n(id="r", subject="root", depth=0, value=0.5))
    s = analyze_tree_shape(IdeaTreeReport(ideas=ideas))
    assert s.distinct_values == 1
    assert any("clustered" in o.lower() for o in s.observations)


def test_render_markdown_sections():
    ideas = [
        _n(id="r", subject="a", depth=0, value=0.9),
        _n(id="c", parent_id="r", subject="a", depth=1, value=0.6, kind="synthesis"),
    ]
    md = render_tree_shape_markdown(analyze_tree_shape(IdeaTreeReport(ideas=ideas)))
    assert "Idea Tree Shape" in md
    assert "Observations" in md
    assert "Branching factor" in md


def test_measured_loc_telemetry_computed():
    ideas = [
        _n(id="a", subject="app/big.py", depth=0, value=0.6),
        _n(id="b", subject="app/small.py", depth=1, parent_id="a", value=0.5),
    ]
    rep = IdeaTreeReport(ideas=ideas, stats={"metrics": {
        "app/big.py": {"loc": 400},
        "app/small.py": {"loc": 100},
    }})
    s = analyze_tree_shape(rep)
    assert s.heaviest_module == "app/big.py"
    assert s.heaviest_loc == 400
    assert s.total_measured_loc == 500
    md = render_tree_shape_markdown(s)
    assert "Measured size:" in md and "app/big.py" in md


def test_dominant_loc_observation_fires():
    ideas = [_n(id="a", subject="app/huge.py", depth=0, value=0.6)]
    rep = IdeaTreeReport(ideas=ideas, stats={"metrics": {
        "app/huge.py": {"loc": 900},
        "app/tiny.py": {"loc": 100},
    }})
    s = analyze_tree_shape(rep)
    # huge.py is 90% of measured LOC -> dominant-LOC observation.
    assert any("Most measured code sits in" in o for o in s.observations)


def test_no_metrics_means_zero_loc_telemetry():
    s = analyze_tree_shape(IdeaTreeReport(ideas=[_n(id="a", subject="x", value=0.5)]))
    assert s.heaviest_module == "" and s.total_measured_loc == 0
    # And the empty-tree path is likewise safe.
    empty = analyze_tree_shape(IdeaTreeReport(ideas=[]))
    assert empty.total_measured_loc == 0


def test_heaviest_tie_break_is_deterministic():
    ideas = [_n(id="a", subject="app/a.py", value=0.5)]
    rep = IdeaTreeReport(ideas=ideas, stats={"metrics": {
        "app/b.py": {"loc": 200}, "app/a.py": {"loc": 200},
    }})
    # Equal LOC -> lexicographically smallest path wins.
    assert analyze_tree_shape(rep).heaviest_module == "app/a.py"


def test_end_to_end_from_engine(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return eval(x)\n")
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 3}, tmp_path
    ).run()
    s = analyze_tree_shape(rep)
    assert s.total_ideas == rep.stats["total_ideas"]
    assert s.max_depth >= 1
    assert s.observations
