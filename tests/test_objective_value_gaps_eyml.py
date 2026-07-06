"""Regression/characterization tests for the planner's objective-value lens.

app/engine/objective_value.py is already fully line-covered; this wave locks the
contract it promises (a thin, deterministic pass-through to the frozen move_value
buyer model):

  * a flagship Tier-1 CONCRETE objective (implement-stub) outweighs a Tier-3 idiom
    tidy (sort-imports);
  * an unknown objective returns the move_value DEFAULT (0.30) — finite, > 0, never
    starved;
  * ``NEUTRAL_WEIGHT`` is the documented 1.0;
  * the weight is exactly ``move_value.objective_value`` (single source of truth);
  * every weight is in (0, 1] and fully deterministic.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

from app.engine.move_value import objective_value
from app.engine.objective_value import NEUTRAL_WEIGHT, objective_value_weight


def test_concrete_flagship_outweighs_idiom_tidy():
    assert objective_value_weight("implement-stub") > objective_value_weight("sort-imports")


def test_unknown_objective_returns_default_never_starved():
    weight = objective_value_weight("brand-new-ability-xyz")
    assert weight == 0.30
    assert 0.0 < weight <= 1.0


def test_neutral_weight_constant():
    assert NEUTRAL_WEIGHT == 1.0


def test_weight_is_exactly_move_value_objective_value():
    for obj in ("implement-stub", "cover-gaps", "sort-imports", "unknown-xyz"):
        assert objective_value_weight(obj) == objective_value(obj)


def test_all_weights_in_unit_interval():
    for obj in ("implement-stub", "cover-gaps", "strengthen-tests",
                "wire-exports", "sort-imports", "modernize", "unknown-xyz"):
        weight = objective_value_weight(obj)
        assert 0.0 < weight <= 1.0


def test_deterministic():
    for obj in ("implement-stub", "sort-imports"):
        first = objective_value_weight(obj)
        for _ in range(5):
            assert objective_value_weight(obj) == first
