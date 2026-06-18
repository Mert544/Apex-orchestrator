"""Deep-mutation characterization for the two reasoning lenses.

The production mutation tester (``app/engine/mutation_tester.py``) caps each
module at 30 seeded mutants (``max_mutants=30``) in document order. Enumerating
the FULL universe with ``_collect_sites``/``_splice`` and running each splice
against ONLY the dedicated covering test file surfaces survivors the 30-cap and
the existing focused tests never reach.

For ``app/engine/effort_reasoning.py`` (58 sites) those survivors were every
number-literal in the ``_EFFORT_BASIS`` rows for labels the existing test file
never exercises (``critical-untested``, ``dependency-hub``,
``complexity-hotspot``, ``modernization``, ``modernization-imports``,
``security-eval``, ``security-finding``, ``base-exception``, ``sensitive-path``)
plus two genuinely EQUIVALENT mutants on the ``max()`` accumulator seeds in
``_aggregate`` (documented below). The tests here pin every previously-uncovered
basis row by driving the effort/payoff band from that row alone, so a one-off
flip of either weight changes the band text (or overflows the band tuple) and is
caught.

For ``app/engine/interaction_reasoning.py`` (7 sites) the dedicated test already
kills every mutant; the regression tests below lock that in.

Deterministic: no time, no randomness, fixed label inputs.
"""

from __future__ import annotations

from app.engine.effort_reasoning import effort_enrichment
from app.engine.interaction_reasoning import interaction_enrichment


# ---------------------------------------------------------------------------
# effort_reasoning — pin each previously-uncovered _EFFORT_BASIS row.
#
# Each test passes the SAME label twice so ``count >= 2`` (the byte-identical
# guard is cleared) and BOTH the effort and payoff bands are driven solely by
# that row's (effort_weight, payoff_weight). Asserting the exact band text means
# any flip of either weight in that row (n -> n+1) either shifts the band string
# or overflows ``_EFFORT_BANDS``/``_PAYOFF_BANDS`` (IndexError), killing the
# mutant. Synonymous labels collapse to one ``kind`` phrase, so the clause names
# the work shape exactly once.
# ---------------------------------------------------------------------------


def test_critical_untested_basis_row():
    # row (1, 3): small effort, high payoff, cheap safety-net test.
    clause, _ = effort_enrichment(("critical-untested", "critical-untested"))
    assert clause == (
        "effort: a small change for high payoff — a cheap safety-net test"
    )


def test_dependency_hub_basis_row():
    # row (3, 3): large effort, high payoff, larger decoupling.
    clause, _ = effort_enrichment(("dependency-hub", "dependency-hub"))
    assert clause == (
        "effort: a large change for high payoff — a larger decoupling"
    )


def test_complexity_hotspot_basis_row():
    # row (3, 3): large effort, high payoff, larger decoupling.
    clause, _ = effort_enrichment(("complexity-hotspot", "complexity-hotspot"))
    assert clause == (
        "effort: a large change for high payoff — a larger decoupling"
    )


def test_modernization_basis_row():
    # row (1, 1): small effort, low payoff, quick tidy.
    clause, _ = effort_enrichment(("modernization", "modernization"))
    assert clause == "effort: a small change for low payoff — a quick tidy"


def test_modernization_imports_basis_row():
    # row (1, 1): small effort, low payoff, quick tidy.
    clause, _ = effort_enrichment(("modernization-imports", "modernization-imports"))
    assert clause == "effort: a small change for low payoff — a quick tidy"


def test_security_eval_basis_row():
    # row (2, 3): moderate effort, high payoff, moderate hardening.
    clause, _ = effort_enrichment(("security-eval", "security-eval"))
    assert clause == (
        "effort: a moderate change for high payoff — a moderate hardening"
    )


def test_security_finding_basis_row():
    # row (2, 3): moderate effort, high payoff, moderate hardening.
    clause, _ = effort_enrichment(("security-finding", "security-finding"))
    assert clause == (
        "effort: a moderate change for high payoff — a moderate hardening"
    )


def test_base_exception_basis_row():
    # row (2, 3): moderate effort, high payoff, moderate hardening.
    clause, _ = effort_enrichment(("base-exception", "base-exception"))
    assert clause == (
        "effort: a moderate change for high payoff — a moderate hardening"
    )


def test_sensitive_path_basis_row():
    # row (2, 3): moderate effort, high payoff, moderate hardening.
    clause, _ = effort_enrichment(("sensitive-path", "sensitive-path"))
    assert clause == (
        "effort: a moderate change for high payoff — a moderate hardening"
    )


def test_moderate_effort_distinct_from_small_and_large():
    # A (2, _) row must land on the MIDDLE effort band — distinguishes the
    # boundary between the 1-weight tidy/test rows and the 3-weight decoupling
    # rows, so a 2 -> 3 (or implicit 2 -> 1) drift on any moderate row is caught.
    clause, _ = effort_enrichment(("base-exception", "base-exception"))
    assert "a moderate change" in clause
    assert "a small change" not in clause
    assert "a large change" not in clause


# ---------------------------------------------------------------------------
# EQUIVALENT MUTANTS (documented, unkillable through the public function).
#
# ``_aggregate`` seeds ``worst_effort = 0`` and ``best_payoff = 0`` and then
# folds in each mappable row via ``max(...)``. Mutating either seed 0 -> 1 is an
# EQUIVALENT mutant: every row in ``_EFFORT_BASIS`` has effort_weight >= 1 and
# payoff_weight >= 1, and ``effort_enrichment`` only emits a clause once at least
# TWO mappable rows are present (``count >= 2``). Whenever a clause is produced
# at least one row contributes a weight >= 1, so ``max(0, w) == max(1, w) == w``
# for every reachable input. The seed therefore never affects the band lookup
# and no behavioural test can distinguish the two seeds. The assertion below
# documents the boundary that makes them equivalent: the smallest weight any
# mappable row can contribute is exactly 1.
# ---------------------------------------------------------------------------


def test_aggregate_seed_is_equivalent_smallest_row_weight_is_one():
    # The lowest-weight rows still produce non-empty bands (weight 1), proving a
    # 0 -> 1 seed flip in _aggregate cannot change any reachable output.
    clause, _ = effort_enrichment(("doc-drift", "modernization"))
    # both are (1, 1) rows -> first non-empty band index in each tuple.
    assert clause == "effort: a small change for low payoff — a quick tidy"


# ---------------------------------------------------------------------------
# interaction_reasoning — the dedicated test already kills all 7 sites; lock in
# the two characterizations most load-bearing for those mutants:
#   * L90 ``pair <= present`` (subset boundary)  — a strict-subset vs equal flip.
#   * L72 ``_SYNONYMS.get(label, label)`` default — the OR-shaped default branch.
# ---------------------------------------------------------------------------


def test_pair_equal_to_present_still_matches():
    # present == pair (no extra labels): the <= subset check must still fire, so
    # a <= -> < boundary flip would wrongly reject this exact-match case.
    clause, _ = interaction_enrichment(["security-finding", "untested"])
    assert clause == (
        "compounding: a dangerous call with no test is an unguarded attack surface"
    )


def test_unknown_label_passes_through_synonyms_default():
    # A label absent from _SYNONYMS must pass through unchanged (the ``, label``
    # default of .get); paired with a synonym it still forms a known pair.
    # "deep-nesting" is not a synonym key; "complex-function" -> complexity-hotspot.
    clause, _ = interaction_enrichment(["deep-nesting", "complex-function"])
    assert clause == (
        "compounding: nesting multiplies the paths the complexity already makes "
        "hard to follow"
    )
