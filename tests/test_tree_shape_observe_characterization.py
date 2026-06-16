"""Characterization tests pinning ``_observe`` output byte-for-byte.

``_observe`` is a pure function of a ``TreeShape`` plus the ``by_kind`` mix. It
emits a deterministic list of threshold-based observation strings. These tests
build ``TreeShape`` instances directly to trip every observation branch (and the
empty / fallback paths) and assert the EXACT emitted strings and their order, so
any behavioral drift in the refactored helpers is caught immediately.
"""

from __future__ import annotations

from app.engine.idea_tree_shape import TreeShape, _observe


def _shape(**kw) -> TreeShape:
    """A neutral baseline TreeShape that fires NO observation, overridable."""
    base = dict(
        total_ideas=10,
        roots=2,
        max_depth=3,
        by_kind={"permutation": 10},
        depth_distribution={0: 2, 1: 4, 2: 3, 3: 1},
        branching_factor=2.0,        # >= 1.5 -> no sparse branching
        distinct_subjects=2,         # < max(3, roots=2)=3 -> no breadth note
        top_subject="alpha",
        top_subject_share=0.3,       # <= 0.5
        facet_penetration=0.25,      # != 0 -> "facets are N%"
        mean_value=0.5,
        value_range=0.4,
        distinct_values=9,           # >= max(3, 10//3=3) -> no clustering note
        heaviest_module="",
        heaviest_loc=0,
        total_measured_loc=0,
        grounded_count=8,
        grounding_ratio=0.8,         # >= 0.5
        distinct_operators=4,        # > 1
        dominant_operator="o1",
        dominant_operator_share=0.3,  # <= 0.5
        leaf_count=5,
        leaf_ratio=0.5,              # between 0.25 and 0.9
        mean_depth=1.5,
        depth_balance=0.5,           # >= 0.34
        subject_concentration=0.2,   # < 0.34
        anchored_count=6,
        anchor_coverage=0.6,         # >= 0.5 -> function-grain note
    )
    base.update(kw)
    return TreeShape(**base)


# --- The neutral baseline fires exactly the two always-evaluated "good" notes --


def test_baseline_emits_coupling_facet_and_anchor_notes_in_order():
    # Default by_kind has no synthesis/pair -> the coupling note fires, then the
    # facet note, then the function-grain note (this is the exact emit order).
    obs = _observe(_shape(), {"permutation": 10})
    assert obs == [
        "No synthesis/pair ideas — few cross-module couplings were found.",
        "Fractal facets are 25% of the tree.",
        "Function-grain: 60% of ideas name a concrete symbol/line to act on first, "
        "not just a file.",
    ]


# --- Each branch in isolation, asserting the exact string -------------------


def test_shallow_tree_note():
    obs = _observe(_shape(max_depth=1), {"permutation": 10})
    assert obs[0] == "Tree is shallow (depth ≤ 1) — raise --depth to permute further."


def test_sparse_branching_note():
    obs = _observe(_shape(branching_factor=1.2), {"permutation": 10})
    assert "Sparse branching — raise --breadth to apply more lenses per idea." in obs


def test_zero_branching_factor_does_not_fire_sparse():
    # branching_factor == 0 is falsy -> the sparse note must NOT fire.
    obs = _observe(_shape(branching_factor=0.0), {"permutation": 10})
    assert not any("Sparse branching" in o for o in obs)


def test_flat_frontier_note():
    obs = _observe(_shape(leaf_ratio=0.95), {"permutation": 10})
    assert any("flat frontier" in o for o in obs)
    assert not any("densely expanded" in o for o in obs)


def test_dense_frontier_note():
    obs = _observe(_shape(leaf_ratio=0.2), {"permutation": 10})
    assert any("densely expanded" in o for o in obs)
    assert not any("flat frontier" in o for o in obs)


def test_top_heavy_note():
    obs = _observe(_shape(max_depth=4, depth_balance=0.3), {"permutation": 10})
    assert any("top-heavy" in o for o in obs)


def test_dominant_subject_note():
    obs = _observe(_shape(top_subject_share=0.7, top_subject="alpha"), {"permutation": 10})
    assert (
        "One subject dominates (70% of ideas: `alpha`) — coverage is narrow." in obs
    )


def test_good_breadth_note():
    obs = _observe(_shape(distinct_subjects=5, roots=2), {"permutation": 10})
    assert "Ideas spread across 5 subjects — good breadth of coverage." in obs


def test_subject_clumping_note():
    obs = _observe(
        _shape(distinct_subjects=3, top_subject_share=0.4, subject_concentration=0.4),
        {"permutation": 10},
    )
    assert any("clump onto a handful of subjects" in o for o in obs)


def test_no_synthesis_pair_note():
    obs = _observe(_shape(), {"permutation": 10})
    assert "No synthesis/pair ideas — few cross-module couplings were found." in obs


def test_synthesis_present_suppresses_coupling_note():
    obs = _observe(_shape(), {"permutation": 8, "synthesis": 2})
    assert not any("No synthesis/pair ideas" in o for o in obs)


def test_no_facets_note():
    obs = _observe(_shape(facet_penetration=0.0), {"permutation": 10})
    assert "No fractal facets — enable --facets to drill into specifics." in obs


def test_clustered_scores_note():
    obs = _observe(_shape(distinct_values=2), {"permutation": 10})
    assert (
        "Scores are clustered — limited prioritization signal between ideas." in obs
    )


def test_single_lens_note():
    obs = _observe(_shape(distinct_operators=1), {"permutation": 10})
    assert any("A single lens shapes the whole tree" in o for o in obs)


def test_dominant_lens_note():
    obs = _observe(
        _shape(distinct_operators=3, dominant_operator="lensX", dominant_operator_share=0.6),
        {"permutation": 10},
    )
    assert (
        "One lens (`lensX`) drives most ideas — reasoning leans on a single "
        "development operator." in obs
    )


def test_weak_grounding_note():
    obs = _observe(_shape(grounding_ratio=0.3), {"permutation": 10})
    assert any("Weakly grounded — only 30% of ideas" in o for o in obs)


def test_no_anchors_note():
    obs = _observe(_shape(anchor_coverage=0.0), {"permutation": 10})
    assert any("No function-grain anchors" in o for o in obs)
    assert not any("Function-grain: " in o for o in obs)


def test_loc_concentration_note():
    obs = _observe(
        _shape(total_measured_loc=1000, heaviest_loc=500, heaviest_module="big.py"),
        {"permutation": 10},
    )
    assert (
        "Most measured code sits in `big.py` (50% of 1000 LOC) — a refactor/test "
        "focus." in obs
    )


# --- Always-present facet line + fallback semantics --------------------------


def test_single_quiet_observation_when_only_facet_fires():
    # anchor_coverage in (0, 0.5) -> neither anchor note fires; with everything
    # else neutral the facet block is the ONLY line, so the well-shaped fallback
    # never appends.
    obs = _observe(_shape(anchor_coverage=0.4), {"permutation": 8, "synthesis": 2})
    assert obs == ["Fractal facets are 25% of the tree."]
    assert not any("Well-shaped tree" in o for o in obs)


def test_no_facets_line_is_always_emitted():
    # The facet block emits one of two lines unconditionally, so obs is never
    # empty and the bare "Well-shaped tree" fallback stays unreachable in
    # practice. Pin the zero-facet branch's exact string here.
    obs = _observe(
        _shape(facet_penetration=0.0, anchor_coverage=0.4),
        {"permutation": 8, "synthesis": 2},
    )
    assert "No fractal facets — enable --facets to drill into specifics." in obs
    assert not any("Well-shaped tree" in o for o in obs)


def test_observe_is_deterministic():
    s = _shape(max_depth=1, leaf_ratio=0.95, grounding_ratio=0.2)
    first = _observe(s, {"permutation": 10})
    second = _observe(s, {"permutation": 10})
    assert first == second
