"""Tests for the counterfactual "risk if unaddressed" reasoning enricher.

The enricher mirrors the ``_abductive`` enricher contract in
``app/engine/idea_reasoning.py``: a pure function over the converging signal
labels of a high-signal idea returning ``(clause, [f"counterfactual: {clause}"])``
or ``(None, None)`` when fewer than 2 distinct labels are mappable.
"""

from __future__ import annotations

from app.engine.counterfactual_generator import (
    _SIGNAL_CONSEQUENCE_MAP,
    counterfactual_enrichment,
)


def test_hub_plus_untested_is_grounded():
    clause, facts = counterfactual_enrichment(("hub", "symbol-hub", "untested"))
    assert clause is not None
    assert clause.startswith("risk if unaddressed: ")
    # both distinct converging concerns appear, joined with " and "
    assert "a change here ripples to every dependent" in clause
    assert "there is no test to catch the regression" in clause
    assert " and " in clause


def test_returned_fact_is_exactly_one_prefixed_clause():
    clause, facts = counterfactual_enrichment(("hub", "untested"))
    assert facts == [f"counterfactual: {clause}"]
    assert len(facts) == 1


def test_security_convergence_clause():
    clause, facts = counterfactual_enrichment(("sensitive-path", "security-finding"))
    assert clause is not None
    assert "an attacker can reach this path with crafted input" in clause
    assert "untrusted input flows into a dangerous call unchecked" in clause
    assert facts == [f"counterfactual: {clause}"]


def test_deterministic_same_labels_same_output():
    labels = ("missing-ci", "complexity-hotspot", "untested")
    first = counterfactual_enrichment(labels)
    second = counterfactual_enrichment(labels)
    assert first == second
    assert first[0] is not None


def test_order_follows_label_order():
    a = counterfactual_enrichment(("hub", "untested"))
    b = counterfactual_enrichment(("untested", "hub"))
    # order is grounded in the label order, so reversing labels reverses the clause
    assert a[0] != b[0]
    assert a[0].index("ripples") < a[0].index("no test")
    assert b[0].index("no test") < b[0].index("ripples")


def test_single_mappable_label_returns_none():
    assert counterfactual_enrichment(("untested",)) == (None, None)


def test_synonym_labels_dedupe_to_single_consequence_returns_none():
    # hub + dependency-hub share one consequence fragment, so only one distinct
    # meaningful consequence survives -> not a genuine convergence.
    assert counterfactual_enrichment(("hub", "dependency-hub")) == (None, None)
    assert counterfactual_enrichment(("hub", "symbol-hub", "god-class")) == (None, None)


def test_unmappable_labels_skipped():
    # unknown labels contribute nothing; only the two mappable ones count
    clause, facts = counterfactual_enrichment(
        ("totally-unknown", "untested", "another-unknown", "missing-ci")
    )
    assert clause is not None
    assert "there is no test to catch the regression" in clause
    assert "broken changes merge with no automated gate to stop them" in clause


def test_no_mappable_labels_returns_none():
    assert counterfactual_enrichment(("foo", "bar", "baz")) == (None, None)


def test_empty_and_none_input_returns_none():
    assert counterfactual_enrichment(()) == (None, None)
    assert counterfactual_enrichment([]) == (None, None)
    assert counterfactual_enrichment(None) == (None, None)


def test_list_input_accepted_like_tuple():
    assert counterfactual_enrichment(["hub", "untested"]) == counterfactual_enrichment(
        ("hub", "untested")
    )


def test_consequence_map_fragments_are_nonempty_strings():
    for label, fragment in _SIGNAL_CONSEQUENCE_MAP.items():
        assert isinstance(label, str) and label
        assert isinstance(fragment, str) and fragment
