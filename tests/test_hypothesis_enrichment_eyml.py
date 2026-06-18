"""Tests for the testable-hypothesis enricher over converging signal labels.

Contract (mirrors the reasoning-enricher seam in app.engine.idea_reasoning):
``hypothesis_enrichment(labels) -> (clause, ["hypothesis: " + clause])`` when
>= 2 labels are mappable, else ``(None, None)`` so an un-reasoned idea stays
byte-identical. Deterministic; the fact is exactly ``[f"hypothesis: {clause}"]``.
"""

from app.engine.hypothesis_mapper import (
    _HYPOTHESIS_PROBES,
    _hypothesis_probes,
    hypothesis_enrichment,
)


def test_converging_complexity_and_untested_fires():
    clause, facts = hypothesis_enrichment(
        ("complexity-hotspot", "untested")
    )
    assert clause is not None
    assert clause.startswith("hypothesis: ")
    # grounded: names the converging risk and a concrete test
    assert "concentrates branching complexity" in clause
    assert "characterization test" in clause
    # falsifiable framing
    assert "falsified if" in clause
    assert facts == [f"hypothesis: {clause}"]


def test_falsifier_comes_from_second_converging_probe():
    # untested's own falsifier is "branch coverage is already complete"; the
    # hub partner supplies a DIFFERENT falsifier, proving the hypothesis is
    # grounded in the confluence rather than a single signal.
    clause, _ = hypothesis_enrichment(("hub", "god-class"))
    assert clause is not None
    assert "concentrates fan-in" in clause
    assert "falsified if each responsibility is already independently constructible" in clause


def test_hub_untested_pair_is_grounded_and_falsifiable():
    clause, facts = hypothesis_enrichment(("hub-untested", "shallow-coverage"))
    assert clause is not None
    assert "chokepoint" in clause
    assert "regression test" in clause
    assert clause.endswith("falsified if every branch is already exercised")
    assert facts == [f"hypothesis: {clause}"]


def test_fewer_than_two_mappable_labels_returns_none():
    # one mappable label
    assert hypothesis_enrichment(("untested",)) == (None, None)
    # one mappable + one unknown
    assert hypothesis_enrichment(("untested", "totally-unknown")) == (None, None)
    # zero mappable
    assert hypothesis_enrichment(("totally-unknown", "also-unknown")) == (None, None)


def test_empty_and_none_inputs_return_none():
    assert hypothesis_enrichment(()) == (None, None)
    assert hypothesis_enrichment([]) == (None, None)
    assert hypothesis_enrichment(None) == (None, None)


def test_unmapped_labels_are_skipped_but_two_mappable_still_fire():
    clause, facts = hypothesis_enrichment(
        ("noise", "complexity-hotspot", "junk", "untested")
    )
    assert clause is not None
    assert facts == [f"hypothesis: {clause}"]


def test_non_string_labels_are_ignored():
    # a tuple containing non-strings + only one real mappable label -> no fire
    assert hypothesis_enrichment((123, None, "untested")) == (None, None)
    # two real mappable labels around the junk still fire
    clause, _ = hypothesis_enrichment((123, "untested", "complexity-hotspot"))
    assert clause is not None


def test_deterministic_same_input_same_output():
    labels = ("complexity-hotspot", "deep-nesting", "untested")
    first = hypothesis_enrichment(labels)
    second = hypothesis_enrichment(labels)
    assert first == second
    assert first[0] is not None


def test_fact_is_exactly_hypothesis_prefix_plus_clause():
    clause, facts = hypothesis_enrichment(("churn-hotspot", "cochange-testgap"))
    assert facts == [f"hypothesis: {clause}"]
    assert len(facts) == 1


def test_probes_helper_is_order_preserving():
    probes = _hypothesis_probes(("untested", "hub", "unknown", "deep-nesting"))
    assert [p for p in probes] == [
        _HYPOTHESIS_PROBES["untested"],
        _HYPOTHESIS_PROBES["hub"],
        _HYPOTHESIS_PROBES["deep-nesting"],
    ]


def test_every_probe_triple_is_well_formed():
    for risk, method, falsifier in _HYPOTHESIS_PROBES.values():
        assert risk and isinstance(risk, str)
        assert method and isinstance(method, str)
        assert falsifier and isinstance(falsifier, str)


def test_synonym_labels_yield_same_clause():
    # hub / dependency-hub / symbol-hub share a probe
    a, _ = hypothesis_enrichment(("hub", "untested"))
    b, _ = hypothesis_enrichment(("symbol-hub", "untested"))
    assert a == b
