from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CorrectionAction(Enum):
    NONE = "none"
    EXPAND_DEEPER = "expand_deeper"
    SEEK_COUNTER_EVIDENCE = "seek_counter_evidence"
    BUDGET_HALT = "budget_halt"
    FLAG_META = "flag_meta"


@dataclass
class CorrectionResult:
    action: CorrectionAction
    should_expand: bool
    rationale: str
    priority: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "should_expand": self.should_expand,
            "rationale": self.rationale,
            "priority": self.priority,
        }


class SelfCorrectionEngine:
    """Evaluate whether a claim needs deeper scrutiny before accepting it.

    The engine checks:
    1. Is confidence high enough?
    2. Was counter-evidence sought?
    3. Is the claim meta-recursive (claim about claims)?
    4. Do we have budget left to expand?
    """

    def __init__(
        self,
        min_confidence: float = 0.6,
        min_counter_evidence: int = 1,
        max_depth_for_aggressive_expansion: int = 4,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_counter_evidence = min_counter_evidence
        self.max_depth_for_aggressive = max_depth_for_aggressive_expansion

    def evaluate(self, claim: dict[str, Any], budget_remaining: int) -> CorrectionResult:
        confidence = claim.get("confidence", 0.0)
        evidence = claim.get("evidence_count", 0)
        counter = claim.get("counter_evidence_count", 0)
        depth = claim.get("depth", 0)
        text = claim.get("claim", "")

        # Budget check first
        if budget_remaining <= 0:
            return CorrectionResult(
                action=CorrectionAction.BUDGET_HALT,
                should_expand=False,
                rationale="Budget exhausted. Cannot expand further.",
                priority="high" if confidence < self.min_confidence else "normal",
            )

        # Meta-claim detection
        if self._is_meta_claim(text):
            return CorrectionResult(
                action=CorrectionAction.FLAG_META,
                should_expand=False,
                rationale="Meta-claim detected (claim about claims). Halting to avoid infinite recursion.",
                priority="low",
            )

        # Missing counter-evidence
        if counter < self.min_counter_evidence and evidence > 0:
            priority = "high" if depth <= self.max_depth_for_aggressive else "low"
            return CorrectionResult(
                action=CorrectionAction.SEEK_COUNTER_EVIDENCE,
                should_expand=True,
                rationale=f"Confidence {confidence:.2f} but only {counter} counter-evidence item(s). Need to seek contradicting evidence before accepting.",
                priority=priority,
            )

        # Low confidence
        if confidence < self.min_confidence:
            priority = "high" if depth <= self.max_depth_for_aggressive else "low"
            return CorrectionResult(
                action=CorrectionAction.EXPAND_DEEPER,
                should_expand=True,
                rationale=f"Confidence {confidence:.2f} below threshold {self.min_confidence}. Expanding branch for more evidence.",
                priority=priority,
            )

        # All checks passed
        return CorrectionResult(
            action=CorrectionAction.NONE,
            should_expand=False,
            rationale=f"Claim passes scrutiny: confidence={confidence:.2f}, evidence={evidence}, counter={counter}.",
            priority="normal",
        )

    @staticmethod
    def _is_meta_claim(text: str) -> bool:
        meta_keywords = ["claim about", "previous claim", "claim that", "meta-claim", "recursive claim"]
        lower = text.lower()
        return any(kw in lower for kw in meta_keywords)
