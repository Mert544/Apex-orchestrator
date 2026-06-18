"""Deep-mutation hardening for the opt-in avoid-guard (the closed learning loop).

This file is ADD-ONLY characterization armour for the avoid-guard added in commit
``ef135d5`` — the opt-in pre-apply guard that skips a fix the proof-of-fix history
predicts will fail. Its correctness is load-bearing: a mutant that makes it skip
the WRONG step, or NOT skip a doomed one, or break the byte-identical-when-off
property, is a serious defect.

Each test below pins a SPECIFIC mutant that the pre-existing suite let SURVIVE
(found by splicing every mutation site inside the avoid-guard functions and
running the covering tests), plus the three high-value guard invariants the brief
calls out (off short-circuit, ``should_avoid`` polarity, skipped-excluded-tally)
so a regression in any of them fails loudly.

Survivors killed here (all in ``app/engine/counterfactual_learning.py`` — the
guard's "brain"):

* ``module_traits`` L98 ``or`` -> ``and`` — a ``/tests/`` directory path whose
  basename does NOT start with ``test_`` must still carry the ``test`` trait.
* ``module_traits`` L102 deep boundary ``>= 3`` -> ``> 3`` and ``3`` -> ``4`` —
  the ``deep`` trait fires at EXACTLY three path separators (boundary), not four.
* ``_tally`` L133 ``or`` -> ``and`` — an UNKNOWN (non-landing, non-skip) outcome
  must count as a failure, exactly like an explicit rollback.
* ``failure_signatures`` L154 ``round(.., 4)`` -> ``round(.., 5)`` — a 2/3 rate
  rounds to ``0.6667`` (four places), pinning the rounding precision.
* ``failure_signatures`` L159 avoid rate boundary ``>= 0.6`` -> ``> 0.6`` — a
  signature whose rate is EXACTLY the threshold (0.6) is still avoided.

EQUIVALENT mutants (documented, not killed — no test can distinguish them):

* ``module_traits`` L97 ``rsplit("/", 1)`` -> ``rsplit("/", 2)``: the basename is
  taken as ``[-1]``, which is the final segment regardless of ``maxsplit >= 1``,
  so the result is identical for every input.
* ``failure_signatures`` L154 ``else 0.0`` -> ``else 1.0``: the ``else`` branch
  fires only when ``attempts == 0``, but ``_bump`` always increments attempts to
  at least 1 before a key exists, so the branch is unreachable — the constant it
  yields can never be observed.

Determinism only — no time/random/order assertions.
"""

from __future__ import annotations

from app.engine.counterfactual_learning import (
    failure_signatures,
    module_traits,
    should_avoid,
)


def _proof(fixes: list[dict]) -> dict:
    return {"fixes": fixes}


def _fix(action: str, outcome: str, target: str = "app/m.py") -> dict:
    return {"finding": {"action": action, "target": target}, "outcome": outcome,
            "changed_files": [target]}


# --- module_traits L98: the second `or` (`name.startswith("tests/")`) ---------


def test_tests_dir_path_with_nontest_basename_is_test_trait():
    """A module living UNDER a ``tests/`` directory whose filename does NOT start
    with ``test_`` still carries the ``test`` trait. Kills ``module_traits`` L98
    ``"/tests/" in name or name.startswith("tests/")`` flipped to ``and``: under
    ``and`` this path (``/tests/`` present, but not a leading ``tests/``) would
    lose its ``test`` trait and mis-route the avoid signature."""
    assert "test" in module_traits("app/tests/helpers.py")
    # Sibling forms the flip would also break, pinned for good measure.
    assert "test" in module_traits("pkg/tests/conftest.py")


# --- module_traits L102: the `deep` boundary (`>= 3` and the literal `3`) ------


def test_deep_trait_fires_at_exactly_three_separators():
    """``deep`` is true at EXACTLY three path separators — the boundary value.
    Kills both ``module_traits`` L102 mutants: ``name.count("/") >= 3`` slid to
    ``> 3`` (boundary off-by-one) and the literal ``3`` bumped to ``4`` (both
    would demand a fourth separator and drop ``deep`` here)."""
    # Exactly 3 separators -> deep.
    assert "deep" in module_traits("a/b/c/d.py")
    # Just below the boundary (2 separators) -> NOT deep, so the boundary is
    # genuinely AT 3 (a `> 2` style mutant would wrongly include this).
    assert "deep" not in module_traits("a/b/c.py")


# --- _tally L133: `in failures or != applied` -- unknown outcomes count failed -


def test_unknown_outcome_counts_as_failure():
    """An outcome that is NEITHER ``applied`` NOR an explicit failure word still
    counts as a failure (anything that didn't land failed). Kills ``_tally`` L133
    ``outcome in _FAILURE_OUTCOMES or outcome != _LANDING_OUTCOME`` flipped to
    ``and``: under ``and`` an unknown outcome (not in the failure tuple) would be
    scored as a NON-failure and the doomed action would never be avoided."""
    history = [_proof([_fix("act", "weird_unknown") for _ in range(3)])]
    entry = failure_signatures(history)["act | generic"]
    assert entry["attempts"] == 3
    assert entry["failures"] == 3
    assert entry["failure_rate"] == 1.0
    assert entry["avoid"] is True


def test_applied_outcome_is_not_a_failure_under_the_same_clause():
    """The dual of the above: a landing (``applied``) outcome is NOT a failure, so
    the same L133 clause must still exclude it. This pins the clause's polarity
    from the other side so the ``or``->``and`` flip can't hide behind a one-sided
    assertion."""
    entry = failure_signatures([_proof([_fix("act", "applied")
                                        for _ in range(3)])])["act | generic"]
    assert entry["failures"] == 0
    assert entry["avoid"] is False


# --- failure_signatures L154: the rounding precision (round(.., 4)) -----------


def test_failure_rate_rounded_to_four_places():
    """A non-terminating ratio (2 failures of 3 attempts) is rounded to FOUR
    decimal places: ``0.6667``. Kills ``failure_signatures`` L154
    ``round(failures / attempts, 4)`` with the literal ``4`` bumped to ``5``
    (which would yield ``0.66667``)."""
    history = [_proof([_fix("act", "rolled_back"), _fix("act", "rolled_back"),
                       _fix("act", "applied")])]
    assert failure_signatures(history)["act | generic"]["failure_rate"] == 0.6667


# --- failure_signatures L159: the avoid rate boundary (rate >= 0.6) -----------


def test_avoid_fires_at_exactly_the_threshold_rate():
    """A signature whose failure rate is EXACTLY the threshold (0.6 == 3/5) and
    which clears the minimum attempts IS avoided. Kills ``failure_signatures``
    L159 ``rate >= _AVOID_FAILURE_RATE`` slid to ``rate > _AVOID_FAILURE_RATE``
    (the boundary flip), which would spare a fix sitting right on the threshold."""
    outcomes = ["rolled_back", "rolled_back", "rolled_back", "applied", "applied"]
    history = [_proof([_fix("act", o) for o in outcomes])]
    entry = failure_signatures(history)["act | generic"]
    assert entry["failure_rate"] == 0.6  # exactly the threshold
    assert entry["attempts"] == 5
    assert entry["avoid"] is True
    # And the guard consuming it agrees: a fix on this signature is skipped.
    assert should_avoid(failure_signatures(history), "act", {"generic"}) is True


# --- the three brief-mandated guard invariants (already killed, pinned here) ---


def test_should_avoid_polarity_is_not_inverted():
    """``should_avoid`` returns True ONLY for an avoid-flagged signature and False
    otherwise — pinning its polarity so any inversion (the ``return True`` /
    ``return False`` swaps, or the ``and`` in the avoid check flipped) fails."""
    flagged = failure_signatures([_proof([_fix("harden_security", "rolled_back",
                                               "tests/test_a.py")
                                          for _ in range(3)])])
    # Flagged action+trait -> True.
    assert should_avoid(flagged, "harden_security", {"test"}) is True
    # Unflagged action -> False (NOT inverted to True).
    assert should_avoid(flagged, "modernize", {"test"}) is False
    # Empty signature map -> the off short-circuit returns False, never True.
    assert should_avoid({}, "harden_security", {"test"}) is False


def test_skipped_learned_outcome_is_excluded_from_the_tally():
    """A persisted ``skipped_learned`` fix contributes NO evidence — neither a
    failure nor a landing. Kills the ``_tally`` L131 skip guard being dropped or
    its equality flipped: a run of pure skips must yield an EMPTY map (no
    self-confirming avoidance), and a single non-skip alongside skips must tally
    only that one."""
    # Pure skips -> no signature at all.
    skips = [_proof([_fix("act", "skipped_learned") for _ in range(4)])]
    assert failure_signatures(skips) == {}

    # One real rollback among skips -> only the rollback is counted.
    mixed = [_proof([
        _fix("act", "skipped_learned"),
        _fix("act", "skipped_learned"),
        _fix("act", "rolled_back"),
    ])]
    entry = failure_signatures(mixed)["act | generic"]
    assert entry["attempts"] == 1  # the two skips contributed nothing
    assert entry["failures"] == 1


def test_off_short_circuit_avoid_nothing_on_empty_signatures():
    """The OFF short-circuit: an empty/falsy signature map makes ``should_avoid``
    return False without consulting any trait. Pins the ``if not signatures``
    early-return so a flip (loading/consulting history when off) is caught."""
    assert should_avoid({}, "anything", {"test"}) is False
    assert should_avoid(None, "anything", {"test"}) is False
