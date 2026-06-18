"""Deep-mutation characterization for the reasoning-enricher seam in
``app/engine/idea_reasoning.py``.

The seam's enrichers and the ``enrich_converging`` combinator are already mostly
killed by the per-lens enrichment suites; this file pins the two residual mutant
survivors that the full mutant universe (enumerated past the 30-cap via
``mutation_tester._collect_sites``) exposed:

* ``_abductive`` returns the two-tuple ``(None, None)`` — never a bare ``None`` —
  on its empty-clause early return (kills ``return None, None`` -> ``return None``
  on L37), so the caller's tuple-unpacking contract holds.
* ``enrich_converging`` only abstains when BOTH ``clauses`` and ``facts`` are
  empty — ``if not clauses and not facts`` — never when only one is (kills the
  ``and`` -> ``or`` flip on L91).

Both survivors live on branches the registered enrichers never drive on their
own, so we reach them by temporarily substituting a probe enricher / a stubbed
``explain_signals``; each substitution is restored in a ``finally`` so the seam's
global registry stays pristine and the suite is deterministic.
"""

from __future__ import annotations

import app.engine.abductive_reasoning as abductive
from app.engine import idea_reasoning as ir


def test_abductive_empty_clause_returns_a_two_tuple_not_bare_none():
    # explain_signals normally yields a result whose root_causes are populated, so
    # explanation_clause is non-empty. Force the empty-clause branch by stubbing
    # explain_signals to return a result with no root causes (clause == "").
    empty = abductive.AbductionResult(root_causes=[], confidence=0.0)
    saved = abductive.explain_signals
    abductive.explain_signals = lambda labels: empty
    try:
        result = ir._abductive(["hub", "symbol-hub"])
    finally:
        abductive.explain_signals = saved
    # The contract is a TWO-tuple of Nones; a ``return None`` mutant would yield a
    # bare ``None`` and break the caller's ``clause, extra = enricher(...)`` unpack.
    assert result == (None, None)
    assert isinstance(result, tuple)
    assert len(result) == 2


def _with_enrichers(enrichers, labels):
    saved = ir.REASONING_ENRICHERS[:]
    ir.REASONING_ENRICHERS[:] = enrichers
    try:
        return ir.enrich_converging(labels)
    finally:
        ir.REASONING_ENRICHERS[:] = saved


def test_clause_only_enricher_does_not_trigger_abstain():
    # An enricher that yields a clause but NO facts: clauses=["c"], facts=[].
    # ``not clauses and not facts`` = False, so the combinator must surface the
    # clause. The ``and`` -> ``or`` mutant would early-return (None, None).
    clause, facts = _with_enrichers(
        [lambda labels: ("only-clause", None)], ["x"]
    )
    assert clause == "only-clause"
    assert facts is None


def test_fact_only_enricher_does_not_trigger_abstain():
    # The symmetric case: facts present, clause absent. ``and`` keeps the facts;
    # ``or`` would wrongly abstain.
    clause, facts = _with_enrichers(
        [lambda labels: (None, ["only-fact"])], ["x"]
    )
    assert clause is None
    assert facts == ["only-fact"]


def test_both_empty_enricher_still_abstains():
    # The genuine abstain case: neither clause nor facts -> (None, None). This
    # pins the TRUE arm so the ``and`` -> ``or`` mutant can only be caught by the
    # one-sided cases above, not masked by a both-empty assertion.
    assert _with_enrichers([lambda labels: (None, None)], ["x"]) == (None, None)
