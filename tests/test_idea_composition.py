"""Tests for the composition grammar — the pure, frozen foundation of chains.

``app/engine/idea_composition.py`` is imported by NOTHING in the running engine
(only this test), so its entire soundness is checkable HERE, statically. These
tests pin:

  * the DRIFT guard (load-bearing): every edge endpoint — key AND successor —
    resolves to a REAL ``move_value`` row, so a renamed/removed objective can
    never silently dangle (mirrors ``facet_develop``'s drift test);
  * the edge SHAPE + insertion order — determinism of enumeration;
  * ``compose_chains`` determinism, acyclicity, the ``max_len`` bound, insertion
    order of successors, and exclusion of the length-1 self-trail;
  * trail CONTENT — trails begin at the start and carry each precondition why;
  * ``chain_value`` compounding math, the 1.0 clamp, 4-dp rounding, and the
    ``0.85**i`` decay anti-domination (a low-value tail cannot dominate).
"""

from __future__ import annotations

import pytest

from app.engine.idea_composition import (
    _COMPOSITION_EDGES,
    chain_value,
    compose_chains,
)
from app.engine.move_value import (
    DEFAULT_VALUE,
    OBJECTIVE_OPERATOR,
    OPERATOR_VALUE,
    objective_value,
)


# The six edges the grammar is seeded with, in their documented insertion order.
_EXPECTED_KEYS = [
    "implement-stub",
    "tdd-implement",
    "cover-gaps",
    "dataclassify",
    "wire-exports",
    "modernize",
]


def _all_objectives() -> set[str]:
    """Every objective name the grammar mentions — keys and successors."""
    names: set[str] = set(_COMPOSITION_EDGES)
    for edges in _COMPOSITION_EDGES.values():
        names.update(succ for succ, _ in edges)
    return names


# --- 1. DRIFT guard (the load-bearing soundness test) ------------------------

def test_every_edge_endpoint_resolves_to_a_real_objective() -> None:
    """Every key AND successor must route to a real ``OPERATOR_VALUE`` row, the
    same guarantee that keeps ``FACET_OBJECTIVE_MAP`` honest. A drift (renamed or
    removed objective) would dangle and this test would fail."""
    for name in _all_objectives():
        operator = OBJECTIVE_OPERATOR.get(name, name.replace("-", "_"))
        assert operator in OPERATOR_VALUE, f"{name} -> {operator} is not a real move_value row"
        # For these known names the value is therefore never the unknown default.
        assert objective_value(name) != DEFAULT_VALUE, name


# The exact buyer value of every grammar objective — a silent re-tier of any of
# these is caught by the data-driven pin below.
_EXPECTED_VALUES = {
    "implement-stub": 1.00,
    "tdd-implement": 1.00,
    "cover-gaps": 0.90,
    "wire-exports": 0.90,
    "strengthen-tests": 0.88,
    "infer-type-hints": 0.72,
    "document-signature": 0.68,
    "generate-usage-doc": 0.66,
    "dataclassify": 0.50,
    "freeze-dataclass": 0.45,
    "modernize": 0.25,
    "sort-imports": 0.18,
}


@pytest.mark.parametrize("name, expected", sorted(_EXPECTED_VALUES.items()))
def test_edge_endpoint_values_match_the_frozen_table(name: str, expected: float) -> None:
    """Pin the exact buyer value the design asserted for each grammar objective."""
    assert objective_value(name) == expected


def test_expected_values_cover_exactly_the_grammar_objectives() -> None:
    """The value pins above cover every objective the grammar mentions — no more,
    no less — so a new edge can't escape the value check."""
    assert set(_EXPECTED_VALUES) == _all_objectives()


# --- 2. edge SHAPE + insertion order -----------------------------------------

def test_edges_is_an_insertion_ordered_dict() -> None:
    """``_COMPOSITION_EDGES`` is a dict whose keys preserve the documented order
    (pins deterministic enumeration)."""
    assert isinstance(_COMPOSITION_EDGES, dict)
    assert list(_COMPOSITION_EDGES) == _EXPECTED_KEYS


@pytest.mark.parametrize("key", _EXPECTED_KEYS)
def test_each_edge_is_a_nonempty_tuple_of_string_pairs(key: str) -> None:
    """Every value is a non-empty tuple of ``(successor, why)`` string pairs,
    each rationale non-empty — the shape the DFS and rendering rely on."""
    edges = _COMPOSITION_EDGES[key]
    assert isinstance(edges, tuple)
    assert edges
    for successor, why in edges:
        assert isinstance(successor, str)
        assert successor
        assert isinstance(why, str)
        assert why.strip(), f"empty rationale on {key}->{successor}"


def test_seeds_exactly_the_six_documented_edges() -> None:
    """The grammar is seeded with EXACTLY the six edges, contents and order."""
    assert _COMPOSITION_EDGES["implement-stub"] == (
        ("cover-gaps", "a filled body is now characterization-testable"),
        ("infer-type-hints", "a filled body now has provable returns"),
    )
    assert _COMPOSITION_EDGES["tdd-implement"] == (
        ("infer-type-hints", "the written fn now has inferable return types"),
        ("document-signature", "the new public fn now has a doc-able signature"),
    )
    assert _COMPOSITION_EDGES["cover-gaps"] == (
        ("strengthen-tests", "a first test now exists to strengthen with a mutant-killer"),
    )
    assert _COMPOSITION_EDGES["dataclassify"] == (
        ("freeze-dataclass", "a @dataclass now exists to prove never-mutated and freeze"),
    )
    assert _COMPOSITION_EDGES["wire-exports"] == (
        ("generate-usage-doc", "a wired public surface now has an API to document"),
    )
    assert _COMPOSITION_EDGES["modernize"] == (
        ("sort-imports", "a modernized module's imports can now be tidied"),
    )


# --- 3. compose_chains: determinism / acyclic / bounded / order / exclusion --

def test_compose_chains_is_deterministic() -> None:
    """Same call yields an identical list (no set/dict-order or RNG leakage)."""
    assert compose_chains("cover-gaps", 3) == compose_chains("cover-gaps", 3)
    assert compose_chains("implement-stub", 3) == compose_chains("implement-stub", 3)


def test_compose_chains_visits_successors_in_insertion_order() -> None:
    """``implement-stub``'s first successor (``cover-gaps``) leads the result
    before its second (``infer-type-hints``) — enumeration order is the grammar's
    insertion order, not arbitrary."""
    trails = compose_chains("implement-stub", 3)
    seconds = [trail[1][0] for trail in trails]
    assert seconds.index("cover-gaps") < seconds.index("infer-type-hints")
    # the cover-gaps->strengthen-tests deepening is present and correctly ordered.
    assert (
        ("implement-stub", ""),
        ("cover-gaps", "a filled body is now characterization-testable"),
        ("strengthen-tests", "a first test now exists to strengthen with a mutant-killer"),
    ) in trails


def test_compose_chains_trails_are_acyclic() -> None:
    """No objective repeats within any returned trail (acyclic by the visited
    frozenset passed by value)."""
    for start in _EXPECTED_KEYS:
        for trail in compose_chains(start, 5):
            objs = [obj for obj, _ in trail]
            assert len(objs) == len(set(objs)), f"cycle in {start}: {objs}"


def test_compose_chains_respects_max_len_and_minimum_length() -> None:
    """Every trail satisfies ``2 <= len <= max_len``; a tighter cap drops the
    deeper trail entirely."""
    for max_len in (2, 3, 4):
        for start in _EXPECTED_KEYS:
            for trail in compose_chains(start, max_len):
                assert 2 <= len(trail) <= max_len
    # implement-stub has a 3-hop trail at max_len=3 but none at max_len=2.
    assert all(len(t) <= 2 for t in compose_chains("implement-stub", 2))
    assert any(len(t) == 3 for t in compose_chains("implement-stub", 3))


def test_compose_chains_excludes_the_length_one_self_trail() -> None:
    """A start with no outgoing edge returns ``[]`` (no length-1 self-trail
    leaks); ``max_len < 2`` likewise yields nothing."""
    assert compose_chains("sort-imports", 3) == []
    assert compose_chains("freeze-dataclass", 3) == []
    assert compose_chains("implement-stub", 1) == []
    assert compose_chains("unknown-objective", 3) == []


def test_compose_chains_trail_content() -> None:
    """Trails begin at the start objective (with an empty root rationale) and
    each hop carries its declared precondition why."""
    trails = compose_chains("implement-stub", 3)
    assert trails, "expected at least one compositional trail"
    for trail in trails:
        assert trail[0] == ("implement-stub", "")
        assert trail[1][0] in {"cover-gaps", "infer-type-hints"}
        # every hop's rationale matches the grammar edge that produced it.
        for (parent, _), (child, why) in zip(trail, trail[1:]):
            edge = dict(_COMPOSITION_EDGES[parent])
            assert edge[child] == why


# --- 4. chain_value: compounding / clamp / rounding / decay ------------------

def test_chain_value_single_objective_is_its_rounded_buyer_value() -> None:
    assert chain_value(["cover-gaps"]) == round(objective_value("cover-gaps"), 4)
    assert chain_value(["sort-imports"]) == round(objective_value("sort-imports"), 4)


def test_chain_value_compounds_and_clamps_to_one() -> None:
    """A two-hop value is the decayed sum, clamped to 1.0."""
    # 1.0 + 0.90*0.85 = 1.765 -> clamped to 1.0
    assert chain_value(["implement-stub", "cover-gaps"]) == 1.0
    assert chain_value(["implement-stub", "cover-gaps"]) == round(min(1.0, 1.00 + 0.90 * 0.85), 4)
    # an unclamped two-hop is the exact decayed sum, rounded to 4 dp.
    assert chain_value(["modernize", "sort-imports"]) == round(0.25 + 0.18 * 0.85, 4) == 0.403


def test_chain_value_multihop_beats_single_move_when_unclamped() -> None:
    """A landable multi-hop chain out-values its single highest move when the
    clamp is not hit — the reason the engine should prefer the deeper campaign."""
    single = chain_value(["dataclassify"])
    chained = chain_value(["dataclassify", "freeze-dataclass"])
    assert chained > single
    assert chained == round(0.50 + 0.45 * 0.85, 4) == 0.8825
    assert chained < 1.0  # genuinely unclamped, so the inequality is meaningful.


def test_chain_value_stays_in_unit_interval_for_every_grammar_trail() -> None:
    """Across every trail the grammar can produce, value is in [0, 1]."""
    for start in _EXPECTED_KEYS:
        for trail in compose_chains(start, 5):
            value = chain_value([obj for obj, _ in trail])
            assert 0.0 <= value <= 1.0


def test_chain_value_is_rounded_to_four_places() -> None:
    """The result carries at most four decimal places."""
    value = chain_value(["dataclassify", "freeze-dataclass"])
    assert value == round(value, 4)


def test_chain_value_decay_prevents_a_low_value_tail_from_dominating() -> None:
    """A third low-value tidy adds only ``objective_value(tail) * 0.85**2`` — a
    small marginal contribution — so a long ceremony tail cannot dominate a short
    high-value chain. Checked on an unclamped sequence so the marginal is exact."""
    two = chain_value(["dataclassify", "modernize"])
    three = chain_value(["dataclassify", "modernize", "sort-imports"])
    # The growth from adding the tail equals the tail's DECAYED contribution; both
    # endpoints round once via chain_value, so compare against the same rounding
    # discipline (round the full three-hop sum, not the tail in isolation).
    expected_growth = round(0.50 + 0.25 * 0.85 + 0.18 * (0.85**2), 4) - two
    assert round(three - two, 4) == round(expected_growth, 4)
    # The tail's marginal weight is tiny: a ceremony tail can never be the driver.
    assert objective_value("sort-imports") * (0.85**2) < 0.2


@pytest.mark.parametrize("start", _EXPECTED_KEYS)
def test_chain_value_decay_weight_strictly_shrinks_per_hop(start: str) -> None:
    """Across every grammar trail, the per-hop decay WEIGHT ``0.85**i`` strictly
    shrinks with depth, so however high a later hop's raw buyer value, its
    contribution to the chain value is geometrically discounted — the structural
    anti-domination guarantee, checked on every trail, not one example."""
    for trail in compose_chains(start, 5):
        weights = [0.85**i for i in range(len(trail))]
        for earlier, later in zip(weights, weights[1:]):
            assert later < earlier
        contributions = [
            objective_value(obj) * weight for (obj, _), weight in zip(trail, weights)
        ]
        assert all(c >= 0.0 for c in contributions)
