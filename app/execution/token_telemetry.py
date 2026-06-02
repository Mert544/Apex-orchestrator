from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TokenBudgetSnapshot:
    analysis_tokens: int = 0
    response_tokens: int = 0
    memory_tokens: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    limit: int = 0
    exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TokenTelemetry:
    """Runtime token accounting with optional budget enforcement.

    Tracks:
      - analysis_tokens: repo scan, claim extraction, fractal expansion
      - response_tokens: generated reports, patch plans, suggestions
      - memory_tokens: context persistence, graph store
      - llm_input/output_tokens: external LLM calls (if enabled)

    Cost model (approximate):
      - analysis/response/memory: 1 token ≈ 4 chars (heuristic)
      - LLM: actual token counts from provider
      - USD: model-specific rates configured in config
    """

    DEFAULT_RATES: dict[str, tuple[float, float]] = {
        "gpt-4o-mini": (0.000_000_15, 0.000_000_60),  # per input/output token
        "gpt-4o": (0.000_002_50, 0.000_010_00),
        "local": (0.0, 0.0),
        "none": (0.0, 0.0),
    }

    def __init__(self, budget_limit: int = 0, model: str = "none") -> None:
        self.budget_limit = budget_limit
        self.model = model
        self._analysis_chars = 0
        self._response_chars = 0
        self._memory_chars = 0
        self._llm_input_tokens = 0
        self._llm_output_tokens = 0
        self._skill_calls: list[dict[str, Any]] = []

    def record_analysis(self, text: str | None = None, char_count: int = 0) -> None:
        self._analysis_chars += char_count or (len(text) if text else 0)

    def record_response(self, text: str | None = None, char_count: int = 0) -> None:
        self._response_chars += char_count or (len(text) if text else 0)

    def record_memory(self, text: str | None = None, char_count: int = 0) -> None:
        self._memory_chars += char_count or (len(text) if text else 0)

    def record_llm_call(self, input_tokens: int, output_tokens: int, model: str | None = None) -> None:
        self._llm_input_tokens += input_tokens
        self._llm_output_tokens += output_tokens
        if model:
            self.model = model

    def record_skill_call(self, skill_name: str, input_text: str = "", output_text: str = "") -> None:
        self._skill_calls.append({
            "skill": skill_name,
            "input_chars": len(input_text),
            "output_chars": len(output_text),
        })
        self.record_analysis(input_text)
        self.record_response(output_text)

    def snapshot(self) -> TokenBudgetSnapshot:
        analysis_tokens = self._analysis_chars // 4
        response_tokens = self._response_chars // 4
        memory_tokens = self._memory_chars // 4
        total = (
            analysis_tokens
            + response_tokens
            + memory_tokens
            + self._llm_input_tokens
            + self._llm_output_tokens
        )
        cost = self._estimate_cost()
        return TokenBudgetSnapshot(
            analysis_tokens=analysis_tokens,
            response_tokens=response_tokens,
            memory_tokens=memory_tokens,
            llm_input_tokens=self._llm_input_tokens,
            llm_output_tokens=self._llm_output_tokens,
            total_tokens=total,
            cost_usd=round(cost, 6),
            limit=self.budget_limit,
            exceeded=self.budget_limit > 0 and total > self.budget_limit,
        )

    def check_budget(self) -> bool:
        """Return True if within budget (or no limit)."""
        if self.budget_limit <= 0:
            return True
        snap = self.snapshot()
        return not snap.exceeded

    def cost_per_outcome(self, outcome_count: int = 1) -> float:
        if outcome_count <= 0:
            return 0.0
        return round(self.snapshot().cost_usd / outcome_count, 6)

    def export_run_report(self, run_id: str = "") -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "run_id": run_id,
            "budget": snap.to_dict(),
            "skill_calls": list(self._skill_calls),
            "model": self.model,
        }

    def _estimate_cost(self) -> float:
        input_rate, output_rate = self.DEFAULT_RATES.get(self.model, (0.0, 0.0))
        return (
            self._llm_input_tokens * input_rate
            + self._llm_output_tokens * output_rate
        )
