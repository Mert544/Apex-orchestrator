"""Mutation-hardening for ``app/engine/idea_permutation.py``.

Each test pins the EXACT behaviour one seeded mutant (in the first 30 sites the
mutation tester scores) would break — flipping a constructor default, an
operator feasibility weight, a boolean fallback, or a list concatenation. They
are deterministic and hermetic: a ``tmp_path`` project root, constructed inputs,
no network or wall-clock.

Companion to the existing ``test_idea_permutation_*`` suites — these target the
construction-time blind spots (defaults + operator alphabet) the behavioural
characterizations don't directly assert.
"""

import dataclasses

import pytest

from app.engine.idea_permutation import (
    DEVELOPMENT_OPERATORS,
    IdeaPermutationEngine,
    Operator,
    _PairState,
)


# --- _PairState default (line 32: pidx default 0) ---------------------------


def test_pairstate_defaults_start_at_zero_and_empty():
    # The shared pair-synthesis counter must START at 0 (a `pidx = 1` mutant
    # would make the first pair idea claim branch path x.p1 instead of x.p0).
    state = _PairState()
    assert state.pidx == 0
    assert state.seen_pairs == set()


# --- Operator is frozen (line 36: @dataclass(frozen=True)) -------------------


def test_operator_dataclass_is_frozen():
    # Operators are immutable, hashable lenses; a `frozen=False` mutant would
    # let an Operator be mutated in place (and silently drop hashability).
    op = Operator("extend", "Extend {x}", 0.6)
    with pytest.raises(dataclasses.FrozenInstanceError):
        op.name = "mutated"  # type: ignore[misc]


# --- Operator feasibility weights (lines 56-66) -----------------------------


def test_development_operator_feasibility_weights_are_pinned():
    # The cheap-lens feasibility weights drive the value function; a `0.6 -> 1.6`
    # (etc.) mutant on any line would silently re-rank every idea. Pin the whole
    # name->feasibility table.
    weights = {op.name: op.feasibility for op in DEVELOPMENT_OPERATORS}
    assert weights == {
        "extend": 0.6,
        "harden": 0.6,
        "test": 0.85,
        "simplify": 0.5,
        "document": 0.85,
        "integrate": 0.4,
        "generalize": 0.45,
        "observe": 0.7,
        "decouple": 0.45,
        "verify": 0.5,
        "fortify": 0.5,
    }


def test_development_operator_feasibility_all_in_unit_range():
    # Every weight is a real 0..1 cheapness signal; a `+1.0` mutant pushes one
    # past 1.0, breaking the "cheaper lenses score higher" contract.
    for op in DEVELOPMENT_OPERATORS:
        assert 0.0 <= op.feasibility <= 1.0


# --- config-or-default fallback (line 100: cfg = config or {}) --------------


def test_engine_constructs_with_none_config(tmp_path):
    # `config or {}` must tolerate config=None; an `and` mutant would make it
    # `None and {}` -> None, crashing on the first `.get`.
    eng = IdeaPermutationEngine(None, tmp_path)
    assert eng.max_depth == 2  # defaults still applied


# --- extra_operators-or-empty fallback (line 107) ---------------------------


def test_engine_constructs_with_none_extra_operators(tmp_path):
    # `extra_operators or []` must tolerate None; an `and` mutant yields
    # `None and []` -> None, which is not iterable.
    eng = IdeaPermutationEngine({}, tmp_path, extra_operators=None)
    assert len(eng.operators) == len(DEVELOPMENT_OPERATORS)


# --- extra-operator concatenation (line 110: DEVELOPMENT_OPERATORS + extra) --


def test_extra_dict_operator_is_appended(tmp_path):
    # The alphabet is widened by concatenation; a `-` mutant (list - list) would
    # raise, and a wrong base would drop the contributed lens.
    eng = IdeaPermutationEngine(
        {}, tmp_path,
        extra_operators=[{"name": "z", "template": "Z {x}", "feasibility": 0.3}],
    )
    assert len(eng.operators) == len(DEVELOPMENT_OPERATORS) + 1
    assert eng.operators[-1].name == "z"
    # The base alphabet is preserved ahead of the contribution.
    assert eng.operators[: len(DEVELOPMENT_OPERATORS)] == DEVELOPMENT_OPERATORS


# --- extra-operator filter (line 108: isinstance(...) or "{x}" in template) --


def test_dict_operator_without_placeholder_is_filtered(tmp_path):
    # A dict template lacking the `{x}` placeholder can't be applied to a
    # subject, so it is dropped. An `and`/`not in` mutant would either admit it
    # or reject a valid one.
    eng = IdeaPermutationEngine(
        {}, tmp_path,
        extra_operators=[{"name": "bad", "template": "no placeholder", "feasibility": 0.3}],
    )
    assert len(eng.operators) == len(DEVELOPMENT_OPERATORS)


def test_operator_instance_kept_even_without_placeholder(tmp_path):
    # An explicit Operator instance is always admitted (the isinstance arm of the
    # `or`), regardless of whether its template carries `{x}`.
    keep = Operator("keep", "no placeholder", 0.3)
    eng = IdeaPermutationEngine({}, tmp_path, extra_operators=[keep])
    assert keep in eng.operators
    assert len(eng.operators) == len(DEVELOPMENT_OPERATORS) + 1


# --- Constructor numeric / boolean defaults (lines 112-136) -----------------


def test_constructor_defaults_are_pinned(tmp_path):
    # Each default is the documented contract; an off-by-one or boolean-flip
    # mutant on any line silently changes the engine's behaviour for every
    # caller relying on the defaults.
    eng = IdeaPermutationEngine({}, tmp_path)
    assert eng.max_depth == 2                      # line 112
    assert eng.breadth == 4                        # line 113
    assert eng.min_relevance == 0.0                # line 114
    assert eng.learning is True                    # line 117
    assert eng.adaptive_depth is False             # line 122
    assert eng.adaptive_depth_bonus == 2           # line 123
    assert eng.adaptive_depth_threshold == 0.6     # line 126
    assert eng.fractal_facets is False             # line 131
    assert eng.facets_per_idea == 2                # line 132
    assert eng.facet_depth == 1                    # line 135
    assert eng.budget.max_total_nodes == 40        # line 136
    assert eng.security_aware is True              # line 138


def test_min_relevance_default_disables_relevance_pruning(tmp_path):
    # min_relevance default 0.0 means "off"; a `1.0` mutant would prune nearly
    # every idea below relevance 1.0. The `> 0.0` guard at the prune site reads
    # this, so the default's value is load-bearing, not cosmetic.
    eng = IdeaPermutationEngine({"max_total_ideas": 20, "security_aware": False}, tmp_path)
    assert eng.min_relevance == 0.0


def test_facet_depth_default_floor_is_one(tmp_path):
    # facet_depth = max(1, int(cfg.get("facet_depth", 1))) — the default and the
    # floor are both 1; a `max(2, ...)` or default-2 mutant would over-zoom.
    eng = IdeaPermutationEngine({"facet_depth": 0}, tmp_path)
    assert eng.facet_depth == 1  # floored, never below 1
    eng_default = IdeaPermutationEngine({}, tmp_path)
    assert eng_default.facet_depth == 1
