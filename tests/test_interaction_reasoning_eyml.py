"""Tests for the compounding-interaction reasoning lens."""

from app.engine.interaction_reasoning import interaction_enrichment


def _effect(clause: str) -> str:
    assert clause.startswith("compounding: ")
    return clause[len("compounding: ") :]


def test_untested_hub_pair():
    clause, facts = interaction_enrichment(["untested", "hub"])
    assert (
        _effect(clause)
        == "an untested hub means every dependent inherits the risk with no safety net"
    )
    assert facts == [f"interaction: {clause}"]


def test_untested_complexity_pair():
    clause, facts = interaction_enrichment(["complexity-hotspot", "untested"])
    assert _effect(clause) == "complexity hides bugs the absent tests would have caught"
    assert facts == [f"interaction: {clause}"]


def test_deep_nesting_complexity_pair():
    clause, facts = interaction_enrichment(["deep-nesting", "complexity-hotspot"])
    assert (
        _effect(clause)
        == "nesting multiplies the paths the complexity already makes hard to follow"
    )
    assert facts == [f"interaction: {clause}"]


def test_security_untested_pair():
    clause, facts = interaction_enrichment(["security-finding", "untested"])
    assert (
        _effect(clause)
        == "a dangerous call with no test is an unguarded attack surface"
    )
    assert facts == [f"interaction: {clause}"]


def test_churn_hub_pair():
    clause, facts = interaction_enrichment(["churn-hotspot", "hub"])
    assert (
        _effect(clause)
        == "frequent change in a hub keeps re-broadcasting instability"
    )
    assert facts == [f"interaction: {clause}"]


def test_synonym_normalisation():
    # eval -> security-finding, critical-untested -> untested
    clause, _ = interaction_enrichment(["eval", "critical-untested"])
    assert (
        _effect(clause)
        == "a dangerous call with no test is an unguarded attack surface"
    )
    # dependency-hub -> hub, shallow-coverage -> untested
    clause2, _ = interaction_enrichment(["dependency-hub", "shallow-coverage"])
    assert (
        _effect(clause2)
        == "an untested hub means every dependent inherits the risk with no safety net"
    )


def test_deterministic_tie_break_strongest_pair_wins():
    # security+untested (entry 0) outranks untested+hub (entry 1) when all present.
    labels = ["untested", "hub", "security-finding"]
    clause, facts = interaction_enrichment(labels)
    assert (
        _effect(clause)
        == "a dangerous call with no test is an unguarded attack surface"
    )
    # Order of the input labels must not change the result.
    clause_rev, _ = interaction_enrichment(["hub", "security-finding", "untested"])
    assert clause_rev == clause


def test_no_pair_present_returns_none():
    assert interaction_enrichment(["untested"]) == (None, None)
    assert interaction_enrichment(["hub", "deep-nesting"]) == (None, None)


def test_empty_and_none_inputs():
    assert interaction_enrichment([]) == (None, None)
    assert interaction_enrichment(None) == (None, None)
    assert interaction_enrichment(()) == (None, None)


def test_fact_format_exact():
    clause, facts = interaction_enrichment(["untested", "hub"])
    assert facts == [f"interaction: {clause}"]
    assert len(facts) == 1
