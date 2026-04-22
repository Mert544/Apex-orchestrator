from __future__ import annotations

import pytest

from app.llm.cost_registry import (
    COST_REGISTRY,
    CostAwareRouter,
    estimate_cost,
    select_model_for_budget,
)


def test_cost_registry_has_known_models():
    assert "gpt-4o-mini" in COST_REGISTRY
    assert "gpt-4o" in COST_REGISTRY
    assert "local" in COST_REGISTRY
    assert "none" in COST_REGISTRY


def test_estimate_cost_openai():
    cost = estimate_cost("gpt-4o-mini", input_tokens=2000, output_tokens=1000)
    # (2 * 0.00015) + (1 * 0.0006) = 0.0003 + 0.0006 = 0.0009
    assert pytest.approx(cost, rel=1e-6) == 0.0009


def test_estimate_cost_local_is_free():
    cost = estimate_cost("local", input_tokens=10000, output_tokens=5000)
    assert cost == 0.0


def test_estimate_cost_unknown_defaults_to_none():
    cost = estimate_cost("unknown-model", input_tokens=1000, output_tokens=500)
    assert cost == 0.0


def test_select_model_for_budget_returns_cheapest():
    candidates = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]
    result = select_model_for_budget(
        candidates, budget_usd=0.01, estimated_input_tokens=1000, estimated_output_tokens=500
    )
    assert result == "gpt-4o-mini"


def test_select_model_for_budget_none_affordable():
    candidates = ["gpt-4-turbo"]
    result = select_model_for_budget(
        candidates, budget_usd=0.0001, estimated_input_tokens=1000, estimated_output_tokens=500
    )
    assert result is None


def test_cost_aware_router_from_single_model_config():
    router = CostAwareRouter.from_config({
        "llm": {"provider": "none", "model": "none"}
    })
    response = router.complete("hello")
    assert response.content == ""
    assert response.model == "none"
    snap = router.snapshot()
    assert snap["session_cost_usd"] == 0.0
    assert snap["budget_remaining_usd"] == float("inf")


def test_cost_aware_router_from_multi_model_config():
    router = CostAwareRouter.from_config({
        "llm": {
            "provider": "none",
            "model": "none",
            "multi_model": {
                "enabled": True,
                "budget_usd": 1.0,
                "models": [
                    {"model": "gpt-4o-mini", "provider": "openai", "api_key": "fake"},
                    {"model": "local", "provider": "local"},
                ],
            },
        }
    })
    snap = router.snapshot()
    assert snap["budget_usd"] == 1.0
    assert router.fallback_chain == ["gpt-4o-mini", "local"]


def test_cost_aware_router_tracks_session_cost():
    router = CostAwareRouter.from_config({
        "llm": {"provider": "none", "model": "none"}
    })
    router.complete("test prompt")
    snap = router.snapshot()
    assert snap["session_tokens_in"] == 0
    assert snap["session_tokens_out"] == 0
    assert snap["session_cost_usd"] == 0.0


def test_cost_aware_router_fallback_on_failure(monkeypatch):
    call_count = {"primary": 0, "secondary": 0}

    class FakePrimary:
        def complete(self, prompt, system=None):
            call_count["primary"] += 1
            raise RuntimeError("primary down")

    class FakeSecondary:
        def complete(self, prompt, system=None):
            call_count["secondary"] += 1
            from app.llm.router import LLMResponse
            return LLMResponse(content="fallback ok", input_tokens=10, output_tokens=5, model="secondary")

    router = CostAwareRouter(
        models=[
            {"model": "primary", "provider": "fake"},
            {"model": "secondary", "provider": "fake"},
        ],
        fallback_chain=["primary", "secondary"],
    )
    router._providers["primary"] = FakePrimary()
    router._providers["secondary"] = FakeSecondary()

    response = router.complete("hello")
    assert response.content == "fallback ok"
    assert call_count["primary"] == 1
    assert call_count["secondary"] == 1
    # Cost is zero because fake model names are not in cost registry; fallback tracking works.
    assert router.snapshot()["session_tokens_in"] == 10
    assert router.snapshot()["session_tokens_out"] == 5
