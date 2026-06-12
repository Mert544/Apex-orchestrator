"""Risk tiers — how much evidence an autonomous fix must earn before applying.

The transform catalog can only grow into riskier territory if the risk is
priced explicitly. Three tiers:

  - **Tier 0** — semantics-preserving or additive-only (docstrings, import
    tidying, ``== None`` → ``is None``, new test files): auto-apply under the
    normal verify/rollback loop.
  - **Tier 1** — behavior-adjacent (security rewrites like ``eval`` →
    ``literal_eval``, mutable-default fixes): auto-apply **only when the test
    suite actually covers the target** — either it already references the
    module, or the test-first shield just created a characterization test.
    No coverage and no shield → the fix is *blocked*, not gambled.
  - **Tier 2** — design-level work (``design_task``, ``add_ci``): never
    auto-applied; surfaced as proposals for a human or a drafting agent.

The tier is part of every apply record, so the proof-of-fix artifact shows
not just what was done but what class of risk it carried.
"""

from __future__ import annotations

TIER_BY_ACTION: dict[str, int] = {
    # Tier 0 — semantics-preserving / additive-only
    "create_test_stub": 0,
    "add_docstring": 0,
    "organize_imports": 0,
    "modernize_comparisons": 0,
    # Tier 1 — behavior-adjacent rewrites
    "harden_security": 1,
    "fix_mutable_defaults": 1,
    # Tier 2 — design-level (not auto-applied anyway; recorded for honesty)
    "design_task": 2,
    "add_ci": 2,
}

# An action type we've never classified is treated as behavior-adjacent:
# new transforms must *earn* Tier 0, not default into it.
_UNKNOWN_TIER = 1


def tier_for(action_type: str) -> int:
    """The risk tier of an action type (unknown actions are cautious Tier 1)."""
    return TIER_BY_ACTION.get(action_type, _UNKNOWN_TIER)
