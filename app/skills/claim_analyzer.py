from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import ClaimType
from app.policies.scoring import score_claim_priority


@dataclass
class ClaimAnalysis:
    claim_type: ClaimType
    priority: float
    signals: list[str]


class ClaimAnalyzer:
    KEYWORDS: dict[ClaimType, set[str]] = {
        ClaimType.ARCHITECTURE: {"architecture", "module", "boundary", "entrypoint", "control flow", "subsystem"},
        ClaimType.VALIDATION: {"test", "validation", "coverage", "assert", "quality"},
        ClaimType.SECURITY: {"security", "auth", "token", "secret", "credential", "payment", "billing"},
        ClaimType.CONFIGURATION: {"config", "configuration", "environment", "env", "setting", "dependency"},
        ClaimType.AUTOMATION: {"ci", "workflow", "pipeline", "automation", "build", "deploy"},
        ClaimType.FEATURE_GAP: {"gap", "missing", "should", "lack", "not detected", "under-specified"},
        ClaimType.OPERATIONS: {"runtime", "operations", "monitoring", "logging", "service", "server"},
    }

    WEIGHTS: dict[ClaimType, tuple[float, float]] = {
        ClaimType.SECURITY: (0.95, 0.95),
        ClaimType.VALIDATION: (0.85, 0.75),
        ClaimType.ARCHITECTURE: (0.80, 0.65),
        ClaimType.AUTOMATION: (0.75, 0.60),
        ClaimType.CONFIGURATION: (0.78, 0.70),
        ClaimType.FEATURE_GAP: (0.72, 0.72),
        ClaimType.OPERATIONS: (0.70, 0.68),
        ClaimType.GENERAL: (0.55, 0.45),
    }

    def analyze(self, claim: str) -> ClaimAnalysis:
        lowered = claim.lower()
        best_type = ClaimType.GENERAL
        best_hits = 0
        signals: list[str] = []

        for claim_type, keywords in self.KEYWORDS.items():
            hits = [kw for kw in keywords if kw in lowered]
            if len(hits) > best_hits:
                best_hits = len(hits)
                best_type = claim_type
                signals = hits

        impact, risk = self.WEIGHTS[best_type]
        novelty = 0.80 if len(claim) > 40 else 0.65
        evidence_gap = 0.75 if best_type in {ClaimType.SECURITY, ClaimType.FEATURE_GAP, ClaimType.VALIDATION} else 0.50
        priority = score_claim_priority(
            impact=impact,
            risk=risk,
            novelty=novelty,
            evidence_gap=evidence_gap,
        )

        return ClaimAnalysis(claim_type=best_type, priority=priority, signals=signals)
