"""The planner's value lens over the frozen ``move_value`` buyer model.

A single, deterministic, stdlib-only accessor that turns the SHIPPED buyer-value
model (:func:`app.engine.move_value.objective_value`) into a priority weight the
planner can multiply into ``GoalRanking.priority``. It is NOT a registered
develop objective — it only READS ``move_value`` (which already carries every
operator/objective entry and is drift-tested) — so it triggers no Facet /
``move_value`` operator / north-star / soundness parity wiring.

Deterministic and zero-cost: a frozen-table lookup with no IO, no clock, no
randomness. The weight is the NEUTRAL ``1.0`` only for an objective with no
classification at all — :func:`objective_value` itself returns the move_value
DEFAULT (0.30) for an unknown objective, so an uncategorised/brand-new ability is
never penalised or starved (mirroring move_value's no-starvation clause).
"""

from __future__ import annotations

# move_value is a pure leaf (no ``app.*`` imports), so this top-level import is
# cycle-free; chosen over a function-local import for clarity.
from app.engine.move_value import objective_value

__all__ = ["objective_value_weight", "NEUTRAL_WEIGHT"]

NEUTRAL_WEIGHT = 1.0


def objective_value_weight(objective: str) -> float:
    """Buyer-value weight of an objective for priority ranking, in (0,1]. Sourced
    from the shipped move_value model (objective_value) — Tier-1 CONCRETE (implement-stub
    1.00, cover-gaps 0.90, strengthen-tests 0.88, wire-exports 0.90 ...) outweighs
    Tier-3 idiom tidies (sort-imports 0.18, modernize 0.25). A pure frozen-table
    lookup: deterministic, no clock/random/IO. An unknown objective returns the
    move_value DEFAULT (0.30), still finite and >0, so a brand-new ability is never
    starved (mirrors move_value's no-starvation clause)."""
    # Single source of truth: move_value. CONCRETE range is 0.32-1.00 and TIDY is
    # 0.15-0.60, so the tiers OVERLAP at the edges (e.g. add-from-future-annotations
    # 0.32 < dedup 0.60) — "concrete LEADS" holds for the FLAGSHIP Tier-1 concretes
    # (implement-stub/cover-gaps/strengthen-tests/wire-exports, all >=0.88) which
    # dominate every tidy, not as a strict partition. No second hand-curated table:
    # move_value stays the only classifier, so no drift is re-introduced.
    return objective_value(objective)
