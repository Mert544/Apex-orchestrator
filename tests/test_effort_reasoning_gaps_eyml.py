"""Regression/characterization tests for the effort/ROI enricher edges.

app/engine/effort_reasoning.py is already fully line-covered; this wave locks a
few behaviours the existing suite does not pin explicitly:

  * the exact ``moderate``-effort band boundary (worst effort == 2);
  * ``best_payoff`` takes the MAX payoff across a mix (a high-payoff concern lifts
    the band even beside a low-payoff one);
  * non-string labels are ``str()``-coerced before lookup (an int label simply does
    not map, so it is ignored rather than raising);
  * sensitive-path / base-exception map to the moderate-hardening basis.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

from app.engine.effort_reasoning import effort_enrichment


def test_moderate_effort_band_boundary():
    # Two moderate-hardening labels: worst effort == 2 -> "a moderate change".
    clause, _ = effort_enrichment(("eval", "base-exception"))
    assert clause is not None
    assert "a moderate change" in clause
    assert "a moderate hardening" in clause


def test_best_payoff_takes_the_maximum():
    # A low-payoff tidy beside a high-payoff test: the band reports the BEST payoff.
    clause, _ = effort_enrichment(("doc-drift", "untested"))
    assert clause is not None
    assert "high payoff" in clause
    assert "low payoff" not in clause


def test_worst_effort_dominates_over_cheap():
    # A cheap tidy beside an expensive decoupling: the effort band reports the WORST.
    clause, _ = effort_enrichment(("unused-import", "hub"))
    assert clause is not None
    assert "a large change" in clause


def test_integer_labels_are_coerced_and_ignored():
    # A non-string label is str()-coerced; "1" is not in the basis, so only the two
    # real labels drive the reasoning (no crash on the int).
    clause, _ = effort_enrichment(("untested", 1, "shallow-coverage"))
    assert clause is not None
    assert "high payoff" in clause


def test_sensitive_path_maps_to_hardening():
    clause, _ = effort_enrichment(("sensitive-path", "security-finding"))
    assert clause is not None
    assert "a moderate hardening" in clause
    assert "a moderate change" in clause


def test_single_mappable_beside_unknown_is_none():
    # Exactly one mappable label (the other is unmapped) -> byte-identical guard.
    assert effort_enrichment(("hub", "not-a-real-label")) == (None, None)


def test_clause_and_fact_agree():
    clause, facts = effort_enrichment(("eval", "sensitive-path"))
    assert clause is not None
    assert facts == [f"effort: {clause}"]
