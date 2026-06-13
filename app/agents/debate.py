from __future__ import annotations

"""Debate Engine — multi-round dissent resolution between agents.

When consensus has dissent (agents disagree), the debate engine:
1. Identifies dissenting agents
2. Asks them to present counter-arguments
3. Allows other agents to respond
4. Re-votes after each round
5. Continues until unanimity, max rounds, or stalemate
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.consensus import ConsensusEngine, ConsensusResult, Verdict, Vote


@dataclass
class DebateRound:
    round_number: int
    claim: str
    votes_before: list[Vote]
    votes_after: list[Vote] = field(default_factory=list)
    arguments: list[dict[str, Any]] = field(default_factory=list)
    consensus_before: ConsensusResult | None = None
    consensus_after: ConsensusResult | None = None


@dataclass
class DebateResult:
    claim: str
    final_consensus: ConsensusResult
    rounds: list[DebateRound] = field(default_factory=list)
    resolved: bool = False
    max_rounds_reached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "resolved": self.resolved,
            "max_rounds_reached": self.max_rounds_reached,
            "total_rounds": len(self.rounds),
            "final_verdict": self.final_consensus.final_verdict.name,
            "final_confidence": round(self.final_consensus.confidence, 2),
            "rounds": [
                {
                    "round": r.round_number,
                    "arguments": r.arguments,
                    "verdict_before": r.consensus_before.final_verdict.name if r.consensus_before else None,
                    "verdict_after": r.consensus_after.final_verdict.name if r.consensus_after else None,
                }
                for r in self.rounds
            ],
        }


class DebateEngine:
    """Facilitates structured debate between agents to resolve dissent."""

    def __init__(
        self,
        consensus_engine: ConsensusEngine,
        max_rounds: int = 3,
        min_confidence_delta: float = 0.1,
        argument_generator: Callable[[str, Vote, list[Vote]], str] | None = None,
    ) -> None:
        self.consensus = consensus_engine
        self.max_rounds = max_rounds
        self.min_confidence_delta = min_confidence_delta
        self.argument_generator = argument_generator or self._default_argument

    def resolve(self, claim: str, initial_votes: list[Vote]) -> DebateResult:
        """Run a debate to resolve dissent on a claim."""
        result = DebateResult(claim=claim, final_consensus=ConsensusResult(claim=claim, final_verdict=Verdict.ABSTAIN, confidence=0.0))
        current_votes = list(initial_votes)

        for round_num in range(1, self.max_rounds + 1):
            consensus = self.consensus.evaluate(claim, current_votes)

            # No dissent = resolved
            if not consensus.dissent:
                result.final_consensus = consensus
                result.resolved = True
                break

            # Record round state
            debate_round = DebateRound(
                round_number=round_num,
                claim=claim,
                votes_before=list(current_votes),
                consensus_before=consensus,
            )

            # Generate arguments from dissenters
            for dissenter in consensus.dissent:
                argument = self.argument_generator(claim, dissenter, current_votes)
                debate_round.arguments.append(
                    {
                        "agent": dissenter.agent_name,
                        "role": dissenter.agent_role,
                        "stance": dissenter.verdict.name,
                        "argument": argument,
                    }
                )

            # Re-evaluate: dissenters might soften their stance
            current_votes = self._reconsider_votes(current_votes, debate_round.arguments)
            new_consensus = self.consensus.evaluate(claim, current_votes)

            debate_round.votes_after = list(current_votes)
            debate_round.consensus_after = new_consensus
            result.rounds.append(debate_round)

            # Check if consensus changed meaningfully
            if new_consensus.final_verdict != consensus.final_verdict:
                result.final_consensus = new_consensus
                if not new_consensus.dissent:
                    result.resolved = True
                    break

            # Check stalemate (no meaningful change)
            if abs(new_consensus.confidence - consensus.confidence) < self.min_confidence_delta:
                result.final_consensus = new_consensus
                result.max_rounds_reached = round_num == self.max_rounds
                break

            result.final_consensus = new_consensus
            result.max_rounds_reached = round_num == self.max_rounds

        return result

    def _reconsider_votes(
        self,
        votes: list[Vote],
        arguments: list[dict[str, Any]],
    ) -> list[Vote]:
        """Simulate agents reconsidering after hearing arguments.

        In a real implementation, this would query each agent with the
        arguments presented. Here we use a simple heuristic:
        - If an agent dissented and sees strong counter-arguments from
          higher-weight agents, they may soften their stance (reduce confidence)
          or flip if the argument is overwhelming.
        """
        new_votes: list[Vote] = []
        arg_text = " ".join(a["argument"].lower() for a in arguments)

        for vote in votes:
            # If agent dissented and arguments are persuasive, reconsider
            if ((vote.verdict != Verdict.ABSTAIN) and ("security" in arg_text and vote.agent_role != "security_auditor")) and (vote.verdict == Verdict.APPROVE and any(a["role"] == "security_auditor" for a in arguments)):
                new_confidence = max(0.1, vote.confidence - 0.3)
                if new_confidence < 0.4:
                    new_votes.append(
                        Vote(
                            agent_name=vote.agent_name,
                            agent_role=vote.agent_role,
                            verdict=Verdict.ABSTAIN,
                            confidence=0.3,
                            reasoning="Softened stance after security concerns raised",
                            weight=vote.weight,
                        )
                    )
                    continue

            new_votes.append(vote)

        return new_votes

    def _default_argument(self, claim: str, dissenter: Vote, all_votes: list[Vote]) -> str:
        """Generate a default argument for a dissenter."""
        if dissenter.verdict == Verdict.REJECT:
            return f"I reject this claim because: {dissenter.reasoning}. The risks outweigh the benefits."
        elif dissenter.verdict == Verdict.APPROVE:
            return f"I support this claim because: {dissenter.reasoning}. The benefits are clear."
        return f"I abstain because: {dissenter.reasoning}. More information is needed."
