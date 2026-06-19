"""Deep mutation-hardening for the autonomous unverified-Tier1 no-commit gate.

Autonomous mode (the only mode with a ``committer``) must NEVER auto-commit an
unverified behaviour change. The gate is
``_MaintenancePass._unverified_behaviour_change(r, tier)``, True only when BOTH
hold:

    (a) ``tier >= 1``  — the action is behaviour-adjacent (Tier-0 fixes are
        semantics-preserving / additive and commit freely);
    (b) the change is NOT truly verified — ``r["verified"]`` is not True AND
        ``r["coverage"]`` is in {None, "none", "module"} (a smoke-import shield
        covers the module but not the changed function).

So a Tier-1 step with coverage in {none, module} is withheld; a Tier-1 with
``function`` coverage (verified) commits; a Tier-0 step commits even at coverage
``none``. Flipping the tier threshold (``>= 1`` -> ``> 1`` / ``>= 0``) or the
coverage membership flips at least one cell below, killing the mutant.

Determinism: all assertions are exact booleans / integer tiers; no time / order.
"""
from __future__ import annotations

from app.engine.idea_action_bridge import _MaintenancePass
from app.execution.risk_tiers import tier_for

_GATE = _MaintenancePass._unverified_behaviour_change


def _r(*, verified=None, coverage="none") -> dict:
    return {"verified": verified, "coverage": coverage}


# ---------------------------------------------------------------------------
# Tier threshold (a): the gate only ever fires at tier >= 1.
# ---------------------------------------------------------------------------
def test_tier0_never_withheld_even_with_no_coverage():
    # Tier-0 (additive / semantics-preserving) commits freely, coverage notwiths.
    assert _GATE(_r(verified=False, coverage="none"), 0) is False
    assert _GATE(_r(verified=False, coverage="module"), 0) is False


def test_negative_tier_never_withheld():
    assert _GATE(_r(verified=False, coverage="none"), -1) is False


def test_tier1_is_the_boundary_that_can_be_withheld():
    # The exact threshold pin: tier 0 commits, tier 1 with weak coverage is held.
    # A mutant turning ``tier >= 1`` into ``tier > 1`` would let tier 1 through.
    assert _GATE(_r(verified=False, coverage="none"), 0) is False
    assert _GATE(_r(verified=False, coverage="none"), 1) is True


def test_high_tier_with_weak_coverage_is_withheld():
    assert _GATE(_r(verified=False, coverage="none"), 2) is True
    assert _GATE(_r(verified=False, coverage="module"), 5) is True


# ---------------------------------------------------------------------------
# Coverage / verified (b): Tier-1 with function-level (verified) coverage commits.
# ---------------------------------------------------------------------------
def test_tier1_with_none_coverage_is_withheld():
    assert _GATE(_r(verified=False, coverage="none"), 1) is True


def test_tier1_with_module_coverage_is_withheld():
    # A smoke-import shield covers the module but not the changed behaviour.
    assert _GATE(_r(verified=False, coverage="module"), 1) is True


def test_tier1_with_missing_coverage_key_is_withheld():
    # coverage absent -> r.get("coverage") is None -> in the weak set -> withheld.
    assert _GATE({"verified": False}, 1) is True


def test_tier1_with_function_coverage_commits():
    # function-level coverage is NOT in {None, none, module} -> not withheld.
    assert _GATE(_r(verified=True, coverage="function"), 1) is False


def test_tier1_verified_true_short_circuits_commit():
    # verified True commits regardless of the coverage field value.
    assert _GATE(_r(verified=True, coverage="module"), 1) is False
    assert _GATE(_r(verified=True, coverage="none"), 1) is False


def test_tier1_test_change_coverage_commits():
    # ``test-change`` is not in the weak set, so it commits (not withheld).
    assert _GATE(_r(verified=True, coverage="test-change"), 1) is False
    # Even if verified were somehow not True, test-change is outside the weak set.
    assert _GATE(_r(verified=False, coverage="test-change"), 1) is False


def test_verified_must_be_exactly_true_not_truthy():
    # The guard is ``r.get("verified") is True`` — a truthy-but-not-True value
    # (e.g. 1) does NOT short-circuit, so a weak-coverage step stays withheld.
    assert _GATE({"verified": 1, "coverage": "module"}, 1) is True


# ---------------------------------------------------------------------------
# Integration with tier_for — the real tiers behind the gate.
# ---------------------------------------------------------------------------
def test_mutable_default_fix_is_tier1_and_gateable():
    tier = tier_for("fix_mutable_defaults")
    assert tier == 1
    # A mutable-default fix with only module coverage is withheld in autonomous.
    assert _GATE(_r(verified=False, coverage="module"), tier) is True


def test_harden_security_is_tier1_and_gateable():
    tier = tier_for("harden_security")
    assert tier == 1
    assert _GATE(_r(verified=False, coverage="none"), tier) is True


def test_create_test_stub_is_tier0_and_commits():
    tier = tier_for("create_test_stub")
    assert tier == 0
    assert _GATE(_r(verified=False, coverage="none"), tier) is False


def test_add_docstring_is_tier0_and_commits():
    tier = tier_for("add_docstring")
    assert tier == 0
    assert _GATE(_r(verified=False, coverage="none"), tier) is False
