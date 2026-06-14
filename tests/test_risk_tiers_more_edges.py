"""Standalone risk-tier classification contract.

Locks the tier mapping independent of the verification_strength suite so the
``risk_tiers`` module stays fully covered on its own.
"""

from __future__ import annotations

from app.execution.risk_tiers import TIER_BY_ACTION, tier_for


def test_tier0_actions_are_semantics_preserving():
    for action in ("create_test_stub", "add_docstring", "organize_imports", "modernize_comparisons"):
        assert tier_for(action) == 0


def test_tier1_actions_are_behavior_adjacent():
    assert tier_for("harden_security") == 1
    assert tier_for("fix_mutable_defaults") == 1


def test_tier2_actions_are_design_level():
    assert tier_for("design_task") == 2
    assert tier_for("add_ci") == 2


def test_unknown_action_defaults_to_cautious_tier1():
    # New transforms must EARN tier 0; an unclassified action is treated as
    # behavior-adjacent rather than silently auto-applied.
    assert tier_for("some_brand_new_transform") == 1
    assert tier_for("") == 1


def test_every_catalog_entry_matches_tier_for():
    for action, tier in TIER_BY_ACTION.items():
        assert tier_for(action) == tier
