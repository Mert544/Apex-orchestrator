"""Honesty guard: the ``critical-untested ⇒ hub`` definitional tautology (and its
derived triple forms) must be SUPPRESSED, never rendered as a confirmed law.

A red-team caught a residual structural tautology slipping through. By
construction the critical-untested list is built as
``[m for m in critical_modules if m in untested]`` (``test_linker.analyze``), and
that ``critical_modules`` argument is fed ``profile.dependency_hubs``
(``project_profile`` ~line 1251). So EVERY critical-untested module is BOTH a
``hub`` AND ``untested`` by definition. The superset map registered only the
``untested`` superset, so ``critical-untested ⇒ hub`` — and the triples that lean
on it (``critical-untested ∧ hub ⇒ untested``, ``critical-untested ∧ untested ⇒
hub``) — were validated as ``confirmed`` (1.0): a definitional identity dressed up
as an empirical finding, contradicting the never-overclaim moat.

These tests pin the correction:

  - the three definitional forms are ``tautology`` and dropped from
    ``validate_discoveries`` (exactly like the pre-existing
    ``critical-untested ⇒ untested`` suppression);
  - a GENUINE empirical association (``security ⇒ untested`` — ``security`` is a
    content detector with no construction-time tie to hubs/coverage) STILL surfaces
    as ``confirmed`` on a well-supported population, proving no over-suppression;
  - the intelligence report's discovery bullets carry none of the suppressed forms;
  - the guard is byte-deterministic across repeated runs.

Consumes ``project_profile`` / ``hypothesis_validation`` / ``intelligence_report``
only — no production module is touched.
"""

from __future__ import annotations

from app.engine.hypothesis_validation import (
    CONFIRM_ANTECEDENT,
    _is_structural_tautology,
    discovery_to_hypothesis,
    validate_discoveries,
    validate_hypothesis,
)
from app.engine.intelligence_report import _discovery_bullets
from app.tools.project_profile import ProjectProfile

# The three forms the red-team showed slipping through as "confirmed".
_DEFINITIONAL_KEYS = [
    "assoc:critical-untested>hub",
    "triple:critical-untested&hub>untested",
    "triple:critical-untested&untested>hub",
]


def _construction_profile() -> ProjectProfile:
    """Six modules that are critical-untested ⊆ hub ⊆ untested, as built for real.

    ``critical_untested = [m for m in dependency_hubs if m in untested]`` — the same
    six modules carry ``critical-untested``, ``hub`` and ``untested``, so each of the
    three definitional implications holds at 1.0 on a population well past the
    confirm floor, yet every one of them is true BY CONSTRUCTION.
    """
    mods = [f"app/m{i}.py" for i in range(6)]
    return ProjectProfile(
        root=".",
        critical_untested_modules=list(mods),
        dependency_hubs=list(mods),
        untested_modules=list(mods),
    )


def _genuine_profile() -> ProjectProfile:
    """Six modules carry both ``security`` and ``untested`` — a REAL association.

    ``security`` is a content detector (eval/os.system/pickle/...) with zero
    construction-time tie to hubs or coverage, so ``security ⇒ untested`` is an
    empirical law the codebase decided, not a definitional subset.
    """
    mods = [f"app/m{i}.py" for i in range(6)]
    return ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
    )


# -------------------------------------------------- detector: definitional forms


def test_critical_untested_implies_hub_is_a_tautology():
    h = discovery_to_hypothesis({"key": "assoc:critical-untested>hub"})
    assert _is_structural_tautology(h) is True


def test_triple_critical_untested_and_hub_implies_untested_is_a_tautology():
    h = discovery_to_hypothesis({"key": "triple:critical-untested&hub>untested"})
    assert _is_structural_tautology(h) is True


def test_triple_critical_untested_and_untested_implies_hub_is_a_tautology():
    h = discovery_to_hypothesis({"key": "triple:critical-untested&untested>hub"})
    assert _is_structural_tautology(h) is True


def test_all_three_definitional_forms_flagged_via_direct_validation():
    p = _construction_profile()
    for key in _DEFINITIONAL_KEYS:
        h = discovery_to_hypothesis({"key": key})
        result = validate_hypothesis(h, p)
        # It holds at full confidence on a well-supported population...
        assert result["confidence"] == 1.0
        assert result["support"] >= CONFIRM_ANTECEDENT
        # ...yet it is a tautology, NOT confirmed.
        assert result["tautology"] is True
        assert result["verdict"] == "tautology"
        assert result["verdict"] != "confirmed"


# ------------------------------------------------- GATE: suppressed end-to-end


def test_definitional_forms_suppressed_from_validated_discoveries():
    results = validate_discoveries(_construction_profile(), top=50)
    keys = {r["key"] for r in results}
    for key in _DEFINITIONAL_KEYS:
        assert key not in keys
    # And nothing emitted is a confirmed reading of any definitional identity.
    for r in results:
        if r["key"] in _DEFINITIONAL_KEYS:
            assert r["verdict"] != "confirmed"


def test_definitional_forms_absent_from_intelligence_bullets():
    bullets = _discovery_bullets(_construction_profile())
    text = "\n".join(bullets)
    # The bullets render the claim, e.g. "carries `hub`" off the definitional rules.
    assert "critical-untested` also carries `hub`" not in text
    assert "and `hub` also carries `untested`" not in text
    assert "and `untested` also carries `hub`" not in text


# ----------------------------------------------- GATE: no over-suppression


def test_genuine_security_untested_still_confirms():
    """``security ⇒ untested`` is empirical, not definitional — must still confirm."""
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    assert _is_structural_tautology(h) is False
    result = validate_hypothesis(h, _genuine_profile())
    assert result["tautology"] is False
    assert result["confidence"] == 1.0
    assert result["support"] >= CONFIRM_ANTECEDENT
    assert result["verdict"] == "confirmed"


def test_genuine_security_untested_surfaces_in_discoveries():
    results = validate_discoveries(_genuine_profile(), top=50)
    by_key = {r["key"]: r for r in results}
    assert "assoc:security>untested" in by_key
    assert by_key["assoc:security>untested"]["verdict"] == "confirmed"


def test_hub_untested_not_definitional_when_hub_is_not_critical():
    """``hub ⇒ untested`` is NOT by construction — a hub may be tested.

    Suppressing only ``critical-untested ⇒ hub``/``untested`` must not bleed into
    the plain ``hub ⇒ untested`` association (no antecedent tag is a structural
    subset of ``untested`` here).
    """
    h = discovery_to_hypothesis({"key": "assoc:hub>untested"})
    assert _is_structural_tautology(h) is False
    # A triple that mixes security with the definitional pair stays empirical too,
    # because no SINGLE antecedent tag forces the consequent by construction.
    triple = discovery_to_hypothesis({"key": "triple:security&hub>untested"})
    assert _is_structural_tautology(triple) is False


def test_reverse_direction_is_not_a_tautology():
    # untested is the SUPERSET, so untested ⇒ critical-untested / ⇒ hub are NOT
    # structural (not every untested module is critical-untested or a hub).
    for key in ("assoc:untested>critical-untested", "assoc:untested>hub"):
        h = discovery_to_hypothesis({"key": key})
        assert _is_structural_tautology(h) is False


# --------------------------------------------------------------- determinism


def test_suppression_is_byte_deterministic():
    p = _construction_profile()
    first = validate_discoveries(p, top=50)
    for _ in range(3):
        assert validate_discoveries(p, top=50) == first
    first_bullets = _discovery_bullets(p)
    for _ in range(3):
        assert _discovery_bullets(p) == first_bullets
    for r in first:
        assert 0.0 <= r["confidence"] <= 1.0
