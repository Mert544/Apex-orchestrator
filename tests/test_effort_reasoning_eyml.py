"""Tests for the effort/ROI reasoning enricher (app/engine/effort_reasoning.py).

Cover: correct effort/payoff banding for representative label sets, that only
present concerns are named, determinism, the ``< 2`` mappable → ``(None, None)``
byte-identical guard, and that the emitted fact is exactly ``[f"effort: {clause}"]``.
"""

from __future__ import annotations

from app.engine.effort_reasoning import effort_enrichment


def test_cheap_high_payoff_two_tests():
    # Two coverage labels: cheapest effort, highest payoff, one de-duped kind.
    clause, facts = effort_enrichment(("untested", "shallow-coverage"))
    assert clause is not None
    assert "a small change" in clause
    assert "high payoff" in clause
    assert "a cheap safety-net test" in clause
    # synonymous coverage labels share one kind — named once.
    assert clause.count("a cheap safety-net test") == 1


def test_structural_plus_test_moderate_large_high():
    # A hub (effort 3) dominates the effort band; payoff stays high.
    clause, facts = effort_enrichment(("hub", "untested"))
    assert clause is not None
    assert "a large change" in clause
    assert "high payoff" in clause
    assert "a larger decoupling" in clause
    assert "a cheap safety-net test" in clause


def test_security_plus_test_moderate_effort_high_payoff():
    clause, _ = effort_enrichment(("eval", "untested"))
    assert clause is not None
    # eval=2 dominates over test=1 → moderate band.
    assert "a moderate change" in clause
    assert "high payoff" in clause
    assert "a moderate hardening" in clause


def test_cosmetic_only_low_payoff_small_effort():
    clause, _ = effort_enrichment(("doc-drift", "unused-import"))
    assert clause is not None
    assert "a small change" in clause
    assert "low payoff" in clause
    assert "a quick tidy" in clause


def test_only_present_concerns_named():
    # god-class present, but no test/security concern → those phrases absent.
    clause, _ = effort_enrichment(("god-class", "deep-nesting"))
    assert clause is not None
    assert "a larger decoupling" in clause
    assert "safety-net" not in clause
    assert "hardening" not in clause
    assert "tidy" not in clause


def test_fact_is_exactly_effort_prefixed_clause():
    clause, facts = effort_enrichment(("hub", "untested"))
    assert facts == [f"effort: {clause}"]


def test_fewer_than_two_mappable_returns_none():
    # one mappable label
    assert effort_enrichment(("untested",)) == (None, None)
    # one mappable + one unknown
    assert effort_enrichment(("untested", "totally-unknown")) == (None, None)
    # all unknown
    assert effort_enrichment(("foo", "bar", "baz")) == (None, None)


def test_empty_and_none_inputs():
    assert effort_enrichment(()) == (None, None)
    assert effort_enrichment([]) == (None, None)
    assert effort_enrichment(None) == (None, None)


def test_synonym_labels_dedupe_kind():
    # hub and symbol-hub both map to "a larger decoupling".
    clause, _ = effort_enrichment(("hub", "symbol-hub"))
    assert clause is not None
    assert clause.count("a larger decoupling") == 1


def test_deterministic():
    labels = ("hub", "symbol-hub", "untested", "eval", "doc-drift")
    first = effort_enrichment(labels)
    for _ in range(5):
        assert effort_enrichment(labels) == first


def test_none_entries_skipped():
    clause, _ = effort_enrichment(("untested", None, "shallow-coverage"))
    assert clause is not None
    assert "high payoff" in clause


def test_ordering_follows_label_order():
    # test label first, then structural → kinds appear in label order.
    clause, _ = effort_enrichment(("untested", "hub"))
    assert clause is not None
    assert clause.index("a cheap safety-net test") < clause.index("a larger decoupling")
