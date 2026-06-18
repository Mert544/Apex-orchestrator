"""Tests for the remediation-sequencing enricher.

Covers: correct phase-ordering for mixed-phase label sets, that only present
concerns are named, determinism, the exact fact shape, and the ``(None, None)``
contract for single-phase / single-label / empty inputs.
"""

from app.engine.remediation_reasoning import remediation_enrichment


def test_orders_phases_stabilise_secure_structural_cosmetic():
    # Labels given DELIBERATELY out of ladder order to prove we re-order them.
    labels = ("doc-drift", "deep-nesting", "eval", "untested")
    clause, facts = remediation_enrichment(labels)
    assert clause is not None
    # stabilise < secure < structural < cosmetic
    i_stab = clause.index("safety-net test")
    i_sec = clause.index("close the risky construct")
    i_struct = clause.index("decouple the structure")
    i_cos = clause.index("tidy up")
    assert i_stab < i_sec < i_struct < i_cos
    assert clause.startswith("fix order: ")
    assert clause.endswith("stabilise before you change risky code")
    assert facts == [f"sequence: {clause}"]


def test_only_present_concerns_named():
    clause, _ = remediation_enrichment(("untested", "hub"))
    assert "untested" in clause
    assert "hub" in clause
    # nothing from absent phases / labels should be named
    assert "eval" not in clause
    assert "doc-drift" not in clause
    assert "deep-nesting" not in clause


def test_fact_is_exactly_sequence_clause():
    clause, facts = remediation_enrichment(("untested", "eval"))
    assert facts == [f"sequence: {clause}"]
    assert len(facts) == 1


def test_deterministic():
    labels = ("hub", "symbol-hub", "untested", "doc-drift")
    first = remediation_enrichment(labels)
    for _ in range(5):
        assert remediation_enrichment(labels) == first


def test_aliased_labels_collapse_to_one_name():
    # hub / symbol-hub / dependency-hub all display as "hub", listed once.
    clause, _ = remediation_enrichment(("untested", "hub", "symbol-hub", "dependency-hub"))
    assert clause.count("hub") == 1


def test_single_phase_returns_none():
    # both labels are STRUCTURAL → one phase → no ordering.
    assert remediation_enrichment(("hub", "deep-nesting")) == (None, None)


def test_single_phase_stabilise_returns_none():
    assert remediation_enrichment(("untested", "shallow-coverage")) == (None, None)


def test_single_label_returns_none():
    assert remediation_enrichment(("untested",)) == (None, None)


def test_empty_and_none_return_none():
    assert remediation_enrichment(()) == (None, None)
    assert remediation_enrichment(None) == (None, None)
    assert remediation_enrichment([]) == (None, None)


def test_unknown_labels_ignored():
    # one known phase + only-unknown others → still single phase → None.
    assert remediation_enrichment(("untested", "totally-unknown")) == (None, None)


def test_two_distinct_phases_minimal():
    clause, facts = remediation_enrichment(("untested", "doc-drift"))
    assert clause is not None
    i_stab = clause.index("safety-net test")
    i_cos = clause.index("tidy up")
    assert i_stab < i_cos
    assert facts == [f"sequence: {clause}"]


def test_phases_joined_with_then():
    clause, _ = remediation_enrichment(("untested", "hub", "doc-drift"))
    assert ", then " in clause
    # three present phases → two separators
    assert clause.count(", then ") == 2
