"""Tests for the reasoning-enricher seam ``app/engine/idea_reasoning.py``.

Each registered per-lens enricher is exercised with REAL converging signal
labels (not stubs) so its lazy import + delegation runs, and ``enrich_converging``
is driven with a label set that makes EVERY lens fire so the registry-order
concatenation is pinned. Deterministic: fixed labels, no time/random/network.
"""

from __future__ import annotations

from app.engine.idea_reasoning import (
    _abductive,
    _counterfactual,
    _effort,
    _hypothesis,
    _interaction,
    _remediation,
    enrich_converging,
)

# A converging label set that drives every registered lens to fire:
#   eval + deep-nesting + complexity-hotspot -> 3 abductive observations,
#   security-finding(eval) + untested -> an interaction pair,
#   and >= 2 mappable concerns for counterfactual / remediation / effort /
#   hypothesis alike.
_ALL_FIRING = ["untested", "eval", "deep-nesting", "complexity-hotspot", "hub"]


# --- individual enricher wrappers ------------------------------------------

def test_abductive_fires_with_two_observations():
    clause, facts = _abductive(["deep-nesting", "eval"])
    assert clause.startswith("root cause:")
    assert facts == [f"abductive: {clause}"]


def test_abductive_none_below_two_observations():
    # one mappable observation is not a convergence worth explaining.
    assert _abductive(["deep-nesting"]) == (None, None)
    assert _abductive([]) == (None, None)


def test_abductive_none_when_result_has_no_clause():
    # A real result with two observations always yields root causes, so the
    # empty-clause abstain is reached only via a result that names none. Stub
    # explain_signals to that degenerate result, restoring it afterwards.
    import app.engine.abductive_reasoning as abductive

    empty = abductive.AbductionResult(root_causes=[], confidence=0.0)
    saved = abductive.explain_signals
    abductive.explain_signals = lambda labels: empty
    try:
        assert _abductive(["deep-nesting", "eval"]) == (None, None)
    finally:
        abductive.explain_signals = saved


def test_interaction_wrapper_delegates():
    clause, facts = _interaction(["untested", "hub"])
    assert clause.startswith("compounding:")
    assert facts == [f"interaction: {clause}"]


def test_counterfactual_wrapper_delegates():
    clause, facts = _counterfactual(["untested", "eval"])
    assert clause.startswith("risk if unaddressed:")
    assert facts == [f"counterfactual: {clause}"]


def test_remediation_wrapper_delegates():
    clause, facts = _remediation(["untested", "eval"])
    assert clause.startswith("fix order:")
    assert facts == [f"sequence: {clause}"]


def test_effort_wrapper_delegates():
    clause, facts = _effort(["untested", "hub"])
    assert clause.startswith("effort:")
    assert facts == [f"effort: {clause}"]


def test_hypothesis_wrapper_delegates():
    clause, facts = _hypothesis(["untested", "complexity-hotspot"])
    assert clause.startswith("hypothesis:")
    # the hypothesis clause already carries its own prefix, so the fact is the
    # clause itself (no doubled prefix).
    assert facts == [clause]


def test_wrappers_abstain_on_single_label():
    # every lens needs >= 2 mappable concerns; a single label is no convergence.
    assert _interaction(["untested"]) == (None, None)
    assert _counterfactual(["untested"]) == (None, None)
    assert _remediation(["untested"]) == (None, None)
    assert _effort(["untested"]) == (None, None)
    assert _hypothesis(["untested"]) == (None, None)


# --- the combinator --------------------------------------------------------

def test_enrich_converging_combines_every_lens_in_order():
    clause, facts = enrich_converging(_ALL_FIRING)
    assert clause is not None
    assert facts is not None
    # clauses are concatenated in registry order: abductive -> interaction ->
    # counterfactual -> remediation -> effort -> hypothesis.
    order = [
        "root cause:",
        "compounding:",
        "risk if unaddressed:",
        "fix order:",
        "effort:",
        "hypothesis:",
    ]
    positions = [clause.index(prefix) for prefix in order]
    assert positions == sorted(positions)


def test_enrich_converging_facts_carry_each_lens_prefix():
    _clause, facts = enrich_converging(_ALL_FIRING)
    prefixes = (
        "abductive:",
        "interaction:",
        "counterfactual:",
        "sequence:",
        "effort:",
        "hypothesis:",
    )
    for prefix in prefixes:
        assert any(f.startswith(prefix) for f in facts)


def test_enrich_converging_partial_fire_skips_silent_lenses():
    # abductive needs two mapped observations (only eval maps here) and eval has
    # no hypothesis probe, so both stay silent and never appear in the clause.
    clause, _facts = enrich_converging(["untested", "eval"])
    assert "root cause:" not in clause
    assert "hypothesis:" not in clause
    for prefix in ("compounding:", "risk if unaddressed:", "fix order:", "effort:"):
        assert prefix in clause


def test_enrich_converging_none_when_nothing_fires():
    assert enrich_converging(["totally-unknown-label"]) == (None, None)


def test_enrich_converging_empty_and_none_inputs():
    assert enrich_converging([]) == (None, None)
    assert enrich_converging(None) == (None, None)


def test_enrich_converging_deterministic():
    first = enrich_converging(_ALL_FIRING)
    for _ in range(3):
        assert enrich_converging(_ALL_FIRING) == first
