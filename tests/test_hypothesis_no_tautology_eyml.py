"""Honesty guards on "validated discoveries": no definitional tautologies, no
single-digit over-claims.

A red-team caught the hypothesis organ presenting DEFINITIONAL TAUTOLOGIES as
confirmed (1.0) "validated discoveries" — e.g. "every ``critical-untested`` module
is also ``untested``", which is TRUE BY CONSTRUCTION (``TestLinker.analyze`` builds
``critical_untested`` as the untested SUBSET of the critical modules). Framing such
an identity as a falsifiable claim "the codebase decided" over-claims. A second
over-claim: a clean rule backed by only a handful of modules read as a confirmed
project-wide law.

These tests pin the fix:

  - a STRUCTURAL tautology (``critical-untested ⇒ untested``) is NEVER a confirmed
    validated discovery — it is suppressed from ``validate_discoveries`` and
    flagged ``tautology`` (never "confirmed") by ``validate_hypothesis`` directly;
  - a GENUINE empirical association (``security ⇒ untested`` — ``security`` is a
    content detector, no construction-time subset of coverage) with >= 5 support is
    STILL ``confirmed`` (no over-suppression);
  - a low-support (3-module) clean association is ``candidate`` (low support), not
    ``confirmed``;
  - determinism and the [0,1] confidence bound survive.

They consume ``project_profile`` / ``hypothesis_validation`` only — no production
module is touched.
"""

from __future__ import annotations

from app.engine.hypothesis_validation import (
    CONFIRM_ANTECEDENT,
    MIN_ANTECEDENT,
    _is_structural_tautology,
    discovery_to_hypothesis,
    validate_discoveries,
    validate_hypothesis,
)
from app.tools.project_profile import ProjectProfile


def _tautology_profile() -> ProjectProfile:
    """Six modules are both ``critical-untested`` and ``untested``.

    ``critical_untested_modules`` is, by ``TestLinker.analyze``, a SUBSET of
    ``untested_modules`` — so "every critical-untested module is untested" is a
    definitional identity, not a discovery, even though it holds at 1.0 on a
    population well past the confirm floor.
    """
    mods = [f"app/m{i}.py" for i in range(6)]
    return ProjectProfile(
        root=".",
        untested_modules=list(mods),
        critical_untested_modules=list(mods),
    )


def _genuine_profile() -> ProjectProfile:
    """Six modules carry both ``security`` and ``untested`` — a REAL association.

    ``security`` is a content-based detector (eval/os.system/pickle/...), built
    with zero reference to coverage, so ``security ⊆ untested`` is NOT structural:
    this is an empirical law the codebase decided, and at >= 5 support it confirms.
    """
    mods = [f"app/m{i}.py" for i in range(6)]
    return ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
    )


def _low_support_profile() -> ProjectProfile:
    """Three ``security`` modules, all ``untested`` (plus extra untested noise).

    A clean (confidence 1.0) but thinly-supported association: a candidate to
    watch, not a project-wide law.
    """
    three = ["app/s0.py", "app/s1.py", "app/s2.py"]
    return ProjectProfile(
        root=".",
        security_finding_modules=list(three),
        untested_modules=three + ["app/x.py", "app/y.py"],
    )


# ----------------------------------------------------------- tautology detector


def test_structural_tautology_detector_flags_critical_untested():
    h = discovery_to_hypothesis({"key": "assoc:critical-untested>untested"})
    assert _is_structural_tautology(h) is True


def test_non_structural_association_is_not_a_tautology():
    # security ⇒ untested is empirical, not a by-construction subset.
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    assert _is_structural_tautology(h) is False
    # The reverse direction (untested ⇒ critical-untested) is also NOT structural:
    # untested is the SUPERSET, so not every untested module is critical-untested.
    rev = discovery_to_hypothesis({"key": "assoc:untested>critical-untested"})
    assert _is_structural_tautology(rev) is False


def test_clique_bundle_is_never_a_structural_tautology():
    # A clique's any⇒all bundle claim is bidirectional, never a one-way subset.
    h = discovery_to_hypothesis({"key": "clique:critical-untested&untested&fragile"})
    assert _is_structural_tautology(h) is False


# ------------------------------------------------------------- GATE: tautology


def test_tautology_suppressed_from_validated_discoveries():
    """The definitional ``critical-untested ⇒ untested`` is never EMITTED."""
    results = validate_discoveries(_tautology_profile(), top=20)
    keys = [r["key"] for r in results]
    assert "assoc:critical-untested>untested" not in keys
    # And nothing it did emit is a confirmed reading of that identity.
    for r in results:
        assert not (r["key"] == "assoc:critical-untested>untested"
                    and r["verdict"] == "confirmed")


def test_tautology_direct_validation_is_flagged_never_confirmed():
    """Even a DIRECT caller cannot read the identity as a confirmed discovery."""
    h = discovery_to_hypothesis({"key": "assoc:critical-untested>untested"})
    result = validate_hypothesis(h, _tautology_profile())
    # It holds at full confidence on a well-supported population...
    assert result["confidence"] == 1.0
    assert result["support"] >= CONFIRM_ANTECEDENT
    # ...yet it is labelled a tautology, NOT confirmed.
    assert result["tautology"] is True
    assert result["verdict"] == "tautology"
    assert result["verdict"] != "confirmed"


# --------------------------------------------------- GATE: no over-suppression


def test_genuine_well_supported_association_is_still_confirmed():
    """An empirical, non-structural rule with >= 5 support keeps confirming."""
    results = validate_discoveries(_genuine_profile(), top=20)
    by_key = {r["key"]: r for r in results}
    assert "assoc:security>untested" in by_key
    confirmed = by_key["assoc:security>untested"]
    assert confirmed["verdict"] == "confirmed"
    assert confirmed["tautology"] is False
    assert confirmed["support"] >= CONFIRM_ANTECEDENT


def test_genuine_association_confirmed_via_direct_validation():
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    result = validate_hypothesis(h, _genuine_profile())
    assert result["verdict"] == "confirmed"
    assert result["confidence"] == 1.0


# ------------------------------------------------------- GATE: low-support label


def test_low_support_clean_association_is_candidate_not_confirmed():
    """A clean rule on only three modules is a candidate, not a confirmation."""
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    result = validate_hypothesis(h, _low_support_profile())
    assert result["confidence"] == 1.0           # it holds perfectly...
    assert MIN_ANTECEDENT <= result["support"] < CONFIRM_ANTECEDENT
    assert result["verdict"] == "candidate"      # ...but support is thin
    assert result["verdict"] != "confirmed"


def test_low_support_surfaces_as_candidate_in_discoveries():
    results = validate_discoveries(_low_support_profile(), top=20)
    by_key = {r["key"]: r for r in results}
    assert by_key.get("assoc:security>untested", {}).get("verdict") == "candidate"


# --------------------------------------------------------------- invariants


def test_thresholds_are_ordered_and_floor_raised():
    # The confirm floor must sit strictly above the read floor (a candidate band
    # exists) and require single-digit-plus support to confirm.
    assert MIN_ANTECEDENT < CONFIRM_ANTECEDENT
    assert CONFIRM_ANTECEDENT >= 5


def test_guards_are_deterministic_and_confidence_bounded():
    for profile in (_tautology_profile(), _genuine_profile(), _low_support_profile()):
        first = validate_discoveries(profile, top=20)
        for _ in range(3):
            assert validate_discoveries(profile, top=20) == first
        for r in first:
            assert 0.0 <= r["confidence"] <= 1.0


def test_empty_and_partial_hypotheses_are_not_tautologies():
    # Empty antecedent/consequent never count as structural tautologies.
    assert _is_structural_tautology({"antecedent": [], "consequent": ["untested"]}) is False
    assert _is_structural_tautology({"antecedent": ["untested"], "consequent": []}) is False
    assert _is_structural_tautology({}) is False
