from __future__ import annotations

from app.skills.assumption_extractor import AssumptionExtractor
from app.skills.evidence_mapper import EvidenceMapper


class Validator:
    def __init__(
        self,
        evidence_mapper: EvidenceMapper | None = None,
        assumption_extractor: AssumptionExtractor | None = None,
    ) -> None:
        self.evidence_mapper = evidence_mapper or EvidenceMapper()
        self.assumption_extractor = assumption_extractor or AssumptionExtractor()

    def validate(self, claim: str) -> dict:
        evidence_map = self.evidence_mapper.map(claim)
        evidence_for = evidence_map.get("evidence_for", [])
        evidence_against = evidence_map.get("evidence_against", [])
        assumptions = self.assumption_extractor.extract(claim)

        if not evidence_for:
            evidence_for = [f"No live supporting evidence collected yet for: {claim}"]
        if not evidence_against:
            evidence_against = [f"No live counter-evidence collected yet for: {claim}"]

        risk = self._score_risk(
            claim=claim,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
        )

        return {
            "evidence_for": evidence_for,
            "evidence_against": evidence_against,
            "assumptions": assumptions,
            "risk": risk,
            "raw_sources_for": evidence_map.get("sources_for", []),
            "raw_sources_against": evidence_map.get("sources_against", []),
        }

    def _score_risk(self, claim: str, evidence_for: list[str], evidence_against: list[str]) -> float:
        lowered = claim.lower()
        base = 0.35

        if any(keyword in lowered for keyword in {"security", "finance", "medical", "health", "market"}):
            base += 0.20
        if evidence_against and not evidence_against[0].startswith("No live counter-evidence"):
            base += 0.10
        if evidence_for and evidence_for[0].startswith("No live supporting evidence"):
            base += 0.20

        return min(base, 0.95)
