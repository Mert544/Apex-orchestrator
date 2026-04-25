from __future__ import annotations

import pytest

from app.llm.cost_registry import CostAwareRouter, estimate_cost, select_model_for_budget


def test_estimate_cost():
    cost = estimate_cost("gpt-4o-mini", 1000, 500)
    assert cost > 0


def test_select_model_for_budget():
    result = select_model_for_budget(["gpt-4o-mini", "gpt-4o"], budget_usd=0.001, estimated_input_tokens=1000, estimated_output_tokens=500)
    assert result is not None


def test_select_model_for_budget_none_affordable():
    result = select_model_for_budget(["gpt-4o"], budget_usd=0.00001, estimated_input_tokens=1000000, estimated_output_tokens=500000)
    assert result is None


def test_cost_aware_router_no_op():
    router = CostAwareRouter.from_config({"llm": {"provider": "none", "model": "none"}})
    resp = router.complete("hello")
    assert resp.content == ""
    assert resp.model == "none"


def test_cost_aware_router_snapshot():
    router = CostAwareRouter.from_config({"llm": {"provider": "none", "model": "none"}})
    router.complete("hello")
    snap = router.snapshot()
    assert snap["session_cost_usd"] == 0.0
    assert snap["budget_remaining_usd"] >= 0.0


def test_cost_aware_router_multi_model_config():
    config = {
        "llm": {
            "multi_model": {
                "enabled": True,
                "budget_usd": 0.05,
                "models": [
                    {"model": "gpt-4o-mini", "provider": "openai"},
                    {"model": "local", "provider": "local"},
                ],
            }
        }
    }
    router = CostAwareRouter.from_config(config)
    assert router.budget_usd == 0.05
    assert len(router.fallback_chain) == 2


def test_cost_aware_router_fallback_chain():
    config = {
        "llm": {
            "multi_model": {
                "enabled": True,
                "budget_usd": 0.05,
                "models": [
                    {"model": "none", "provider": "none"},
                ],
            }
        }
    }
    router = CostAwareRouter.from_config(config)
    resp = router.complete("hello")
    assert resp.content == ""
