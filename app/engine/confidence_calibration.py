from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CalibrationResult:
    original_confidence: float
    adjusted_confidence: float
    reliability: str
    is_calibrated: bool
    has_conflict: bool
    diversity_score: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_confidence": self.original_confidence,
            "adjusted_confidence": self.adjusted_confidence,
            "reliability": self.reliability,
            "is_calibrated": self.is_calibrated,
            "has_conflict": self.has_conflict,
            "diversity_score": self.diversity_score,
            "rationale": self.rationale,
        }


class ConfidenceCalibrator:
    """Statistically calibrate claim confidence based on evidence quality.

    Factors:
    - Evidence count and weights
    - Evidence diversity (different sources = more reliable)
    - Conflicting evidence (reduces confidence)
    - Source reliability (direct observation > heuristic)
    """

    def calibrate(self, claim: dict[str, Any]) -> CalibrationResult:
        original = claim.get("confidence", 0.0)
        evidence = claim.get("evidence", [])

        if not evidence:
            return CalibrationResult(
                original_confidence=original,
                adjusted_confidence=original * 0.5,
                reliability="low",
                is_calibrated=True,
                has_conflict=False,
                diversity_score=0.0,
                rationale="No evidence provided. Confidence halved as a safety measure.",
            )

        total_weight = 0.0
        direct_count = 0
        indirect_count = 0
        conflicting_weight = 0.0
        sources = set()

        for ev in evidence:
            weight = ev.get("weight", 0.5)
            ev_type = ev.get("type", "indirect")
            source = ev.get("source", "unknown")
            contradicts = ev.get("contradicts", False)

            total_weight += weight
            sources.add(source)

            if ev_type == "direct":
                direct_count += 1
            else:
                indirect_count += 1

            if contradicts:
                conflicting_weight += weight

        # Diversity: more unique sources = higher diversity
        diversity = min(1.0, len(sources) / 3.0)

        # Base adjustment from evidence weight
        if total_weight >= 2.5:
            weight_factor = 1.15
        elif total_weight >= 1.5:
            weight_factor = 1.0
        else:
            weight_factor = 0.8

        # Conflict penalty
        if conflicting_weight > 0:
            conflict_penalty = min(0.4, conflicting_weight / total_weight)
        else:
            conflict_penalty = 0.0

        # Direct evidence bonus
        direct_bonus = min(0.1, direct_count * 0.05)

        adjusted = original * weight_factor + direct_bonus - conflict_penalty
        adjusted = max(0.0, min(1.0, adjusted))

        # Reliability classification
        if adjusted >= 0.8 and diversity >= 0.6 and conflict_penalty == 0:
            reliability = "high"
        elif adjusted >= 0.5:
            reliability = "medium"
        else:
            reliability = "low"

        has_conflict = conflict_penalty > 0

        rationale_parts = [
            f"Original confidence: {original:.2f}",
            f"Evidence weight sum: {total_weight:.2f}",
            f"Unique sources: {len(sources)} (diversity: {diversity:.2f})",
        ]
        if has_conflict:
            rationale_parts.append(f"Conflicting evidence penalty: {conflict_penalty:.2f}")
        rationale_parts.append(f"Final calibrated confidence: {adjusted:.2f}")

        return CalibrationResult(
            original_confidence=original,
            adjusted_confidence=round(adjusted, 2),
            reliability=reliability,
            is_calibrated=True,
            has_conflict=has_conflict,
            diversity_score=round(diversity, 2),
            rationale="; ".join(rationale_parts),
        )
