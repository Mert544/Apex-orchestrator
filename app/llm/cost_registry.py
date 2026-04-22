from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelCost:
    name: str
    provider: str
    input_cost_per_1k: float  # USD per 1K input tokens
    output_cost_per_1k: float  # USD per 1K output tokens
    context_window: int = 128000


# Cost registry as of 2025-04 — update as pricing changes.
COST_REGISTRY: dict[str, ModelCost] = {
    "gpt-4o-mini": ModelCost(
        name="gpt-4o-mini", provider="openai",
        input_cost_per_1k=0.00015, output_cost_per_1k=0.0006,
        context_window=128000,
    ),
    "gpt-4o": ModelCost(
        name="gpt-4o", provider="openai",
        input_cost_per_1k=0.0025, output_cost_per_1k=0.01,
        context_window=128000,
    ),
    "gpt-4-turbo": ModelCost(
        name="gpt-4-turbo", provider="openai",
        input_cost_per_1k=0.01, output_cost_per_1k=0.03,
        context_window=128000,
    ),
    "local": ModelCost(
        name="local", provider="local",
        input_cost_per_1k=0.0, output_cost_per_1k=0.0,
        context_window=8192,
    ),
    "none": ModelCost(
        name="none", provider="none",
        input_cost_per_1k=0.0, output_cost_per_1k=0.0,
        context_window=0,
    ),
}


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    cost = COST_REGISTRY.get(model_name, COST_REGISTRY["none"])
    return (
        (input_tokens / 1000) * cost.input_cost_per_1k
        + (output_tokens / 1000) * cost.output_cost_per_1k
    )


def select_model_for_budget(
    candidates: list[str],
    budget_usd: float,
    estimated_input_tokens: int = 1000,
    estimated_output_tokens: int = 500,
) -> str | None:
    """Return the cheapest model that fits within budget, or None if none do."""
    affordable = []
    for name in candidates:
        cost = estimate_cost(name, estimated_input_tokens, estimated_output_tokens)
        if cost <= budget_usd:
            affordable.append((cost, name))
    if not affordable:
        return None
    affordable.sort(key=lambda x: x[0])
    return affordable[0][1]


class CostAwareRouter:
    """Wraps LLMRouter with multi-model fallback and cost-aware selection."""

    def __init__(
        self,
        models: list[dict[str, Any]],
        budget_usd: float = float("inf"),
        fallback_chain: list[str] | None = None,
    ) -> None:
        self.models = models
        self.budget_usd = budget_usd
        self.fallback_chain = fallback_chain or []
        self._providers: dict[str, Any] = {}
        self._session_cost: float = 0.0
        self._session_tokens_in: int = 0
        self._session_tokens_out: int = 0

    def _get_or_create_provider(self, model_name: str) -> Any:
        from app.llm.router import LLMRouter, NoOpProvider, OpenAICompatibleProvider, LocalProvider

        if model_name in self._providers:
            return self._providers[model_name]

        model_cfg = next((m for m in self.models if m.get("model") == model_name), None)
        if model_cfg is None:
            raise ValueError(f"Model '{model_name}' not found in config")

        provider_name = model_cfg.get("provider", "none")
        if provider_name == "none":
            provider = NoOpProvider(model_cfg)
        elif provider_name == "local":
            provider = LocalProvider(model_cfg)
        else:
            provider = OpenAICompatibleProvider(model_cfg)

        self._providers[model_name] = provider
        return provider

    def complete(self, prompt: str, system: str | None = None, preferred_model: str | None = None) -> Any:
        from app.llm.router import LLMResponse

        candidates = [preferred_model] if preferred_model else self.fallback_chain
        if not candidates:
            candidates = [m.get("model", "none") for m in self.models]

        last_error: Exception | None = None
        for model_name in candidates:
            if model_name is None:
                continue
            try:
                provider = self._get_or_create_provider(model_name)
                response = provider.complete(prompt, system)
                cost = estimate_cost(model_name, response.input_tokens, response.output_tokens)
                self._session_cost += cost
                self._session_tokens_in += response.input_tokens
                self._session_tokens_out += response.output_tokens
                return response
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        return LLMResponse(content="", input_tokens=0, output_tokens=0, model="none")

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_cost_usd": round(self._session_cost, 6),
            "session_tokens_in": self._session_tokens_in,
            "session_tokens_out": self._session_tokens_out,
            "budget_usd": self.budget_usd,
            "budget_remaining_usd": round(max(0.0, self.budget_usd - self._session_cost), 6),
        }

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "CostAwareRouter":
        llm_config = config.get("llm", {})
        multi = llm_config.get("multi_model")
        if multi and multi.get("enabled"):
            models = multi.get("models", [])
            budget = float(multi.get("budget_usd", float("inf")))
            fallback = [m.get("model") for m in models if m.get("model")]
            return cls(models=models, budget_usd=budget, fallback_chain=fallback)
        # Fallback to single-model router wrapped in cost-aware shell
        single_model = llm_config.get("model", "none")
        single_provider = llm_config.get("provider", "none")
        return cls(
            models=[{"model": single_model, "provider": single_provider, **llm_config}],
            budget_usd=float("inf"),
            fallback_chain=[single_model],
        )
