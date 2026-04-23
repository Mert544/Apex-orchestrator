from __future__ import annotations

"""Consensus Engine — multi-agent voting and decision making."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class Verdict(Enum):
    APPROVE = auto()
    REJECT = auto()
    ABSTAIN = auto()


@dataclass
class Vote:
    agent_name: str
    agent_role: str
    verdict: Verdict
    confidence: float  # 0.0 - 1.0
    reasoning: str
    weight: float = 1.0  # Role-based weight


@dataclass
class ConsensusResult:
    claim: str
    final_verdict: Verdict
    confidence: float
    votes: list[Vote] = field(default_factory=list)
    dissent: list[Vote] = field(default_factory=list)
    strategy: str = ""
    quorum_reached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "verdict": self.final_verdict.name,
            "confidence": round(self.confidence, 2),
            "quorum_reached": self.quorum_reached,
            "strategy": self.strategy,
            "total_votes": len(self.votes),
            "dissent_count": len(self.dissent),
            "votes": [
                {
                    "agent": v.agent_name,
                    "role": v.agent_role,
                    "verdict": v.verdict.name,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "weight": v.weight,
                }
                for v in self.votes
            ],
            "dissent": [
                {
                    "agent": v.agent_name,
                    "role": v.agent_role,
                    "verdict": v.verdict.name,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                }
                for v in self.dissent
            ],
        }


class ConsensusEngine:
    """Aggregate agent votes into a collective decision.

    Strategies:
    - unanimous: All non-abstain votes must be APPROVE
    - majority: >50% of weighted votes are APPROVE
    - supermajority: >=2/3 of weighted votes are APPROVE
    - weighted: Weighted average confidence determines outcome
    - threshold: Any single APPROVE with confidence >= threshold
    """

    STRATEGIES: dict[str, Callable[[list[Vote]], tuple[Verdict, float, bool]]] = {}

    def __init__(self, strategy: str = "majority", quorum: int = 2, min_confidence: float = 0.5) -> None:
        self.strategy = strategy
        self.quorum = quorum
        self.min_confidence = min_confidence
        self._register_strategies()

    def _register_strategies(self) -> None:
        self.STRATEGIES = {
            "unanimous": self._unanimous,
            "majority": self._majority,
            "supermajority": self._supermajority,
            "weighted": self._weighted,
            "threshold": self._threshold,
        }

    def evaluate(self, claim: str, votes: list[Vote]) -> ConsensusResult:
        if len(votes) < self.quorum:
            return ConsensusResult(
                claim=claim,
                final_verdict=Verdict.ABSTAIN,
                confidence=0.0,
                votes=votes,
                strategy=self.strategy,
                quorum_reached=False,
            )

        strategy_fn = self.STRATEGIES.get(self.strategy, self._majority)
        verdict, confidence, quorum = strategy_fn(votes)

        # Dissent = votes that disagree with final verdict
        dissent = [v for v in votes if v.verdict not in (verdict, Verdict.ABSTAIN)]

        return ConsensusResult(
            claim=claim,
            final_verdict=verdict,
            confidence=confidence,
            votes=votes,
            dissent=dissent,
            strategy=self.strategy,
            quorum_reached=quorum,
        )

    def _unanimous(self, votes: list[Vote]) -> tuple[Verdict, float, bool]:
        non_abstain = [v for v in votes if v.verdict != Verdict.ABSTAIN]
        if not non_abstain:
            return Verdict.ABSTAIN, 0.0, False
        if all(v.verdict == Verdict.APPROVE for v in non_abstain):
            conf = min(v.confidence for v in non_abstain)
            return Verdict.APPROVE, conf, True
        return Verdict.REJECT, 1.0 - max(v.confidence for v in non_abstain if v.verdict == Verdict.REJECT), True

    def _majority(self, votes: list[Vote]) -> tuple[Verdict, float, bool]:
        approve_weight = sum(v.weight for v in votes if v.verdict == Verdict.APPROVE)
        reject_weight = sum(v.weight for v in votes if v.verdict == Verdict.REJECT)
        total = approve_weight + reject_weight
        if total == 0:
            return Verdict.ABSTAIN, 0.0, False
        if approve_weight / total > 0.5:
            conf = sum(v.confidence * v.weight for v in votes if v.verdict == Verdict.APPROVE) / approve_weight
            return Verdict.APPROVE, conf, True
        else:
            conf = sum(v.confidence * v.weight for v in votes if v.verdict == Verdict.REJECT) / reject_weight
            return Verdict.REJECT, conf, True

    def _supermajority(self, votes: list[Vote]) -> tuple[Verdict, float, bool]:
        approve_weight = sum(v.weight for v in votes if v.verdict == Verdict.APPROVE)
        reject_weight = sum(v.weight for v in votes if v.verdict == Verdict.REJECT)
        total = approve_weight + reject_weight
        if total == 0:
            return Verdict.ABSTAIN, 0.0, False
        if approve_weight / total >= 2 / 3:
            conf = sum(v.confidence * v.weight for v in votes if v.verdict == Verdict.APPROVE) / approve_weight
            return Verdict.APPROVE, conf, True
        elif reject_weight / total >= 2 / 3:
            conf = sum(v.confidence * v.weight for v in votes if v.verdict == Verdict.REJECT) / reject_weight
            return Verdict.REJECT, conf, True
        return Verdict.ABSTAIN, 0.0, True

    def _weighted(self, votes: list[Vote]) -> tuple[Verdict, float, bool]:
        total_weight = sum(v.weight for v in votes if v.verdict != Verdict.ABSTAIN)
        if total_weight == 0:
            return Verdict.ABSTAIN, 0.0, False
        weighted_score = sum(
            (v.confidence if v.verdict == Verdict.APPROVE else -v.confidence) * v.weight
            for v in votes if v.verdict != Verdict.ABSTAIN
        ) / total_weight
        if weighted_score > 0:
            return Verdict.APPROVE, abs(weighted_score), True
        elif weighted_score < 0:
            return Verdict.REJECT, abs(weighted_score), True
        return Verdict.ABSTAIN, 0.0, True

    def _threshold(self, votes: list[Vote]) -> tuple[Verdict, float, bool]:
        approves = [v for v in votes if v.verdict == Verdict.APPROVE and v.confidence >= self.min_confidence]
        if approves:
            return Verdict.APPROVE, max(v.confidence for v in approves), True
        rejects = [v for v in votes if v.verdict == Verdict.REJECT and v.confidence >= self.min_confidence]
        if rejects:
            return Verdict.REJECT, max(v.confidence for v in rejects), True
        return Verdict.ABSTAIN, 0.0, True

    @staticmethod
    def create_vote(agent_name: str, agent_role: str, verdict: str, confidence: float, reasoning: str, weight: float = 1.0) -> Vote:
        return Vote(
            agent_name=agent_name,
            agent_role=agent_role,
            verdict=Verdict[verdict.upper()],
            confidence=confidence,
            reasoning=reasoning,
            weight=weight,
        )
