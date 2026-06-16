from __future__ import annotations

"""Claim Evaluator — routes claims to relevant agents for peer review."""

from typing import Any

from app.agents.base import Agent
from app.agents.consensus import ConsensusEngine, ConsensusResult, Verdict, Vote
from app.agents.memory import AgentMemory
from app.agents.skills import SecurityAgent, DocstringAgent, TestStubAgent, DependencyAgent


class ClaimEvaluator:
    """Evaluates claims using a panel of specialist agents.

    Each agent reviews the claim from its own perspective:
    - SecurityAgent: "Does this claim introduce security risks?"
    - DocstringAgent: "Is this claim well-documented?"
    - TestStubAgent: "Can this claim be tested?"
    - DependencyAgent: "Is this claim architecturally sound?"

    Supports memory: remembers past evaluations and fast-paths similar claims.
    """

    ROLE_WEIGHTS = {
        "security_auditor": 1.5,
        "documentation_enforcer": 0.8,
        "test_coverage_analyst": 1.0,
        "architecture_analyst": 1.2,
    }

    def __init__(self, consensus_strategy: str = "majority", quorum: int = 2, memory_dir: str | None = None) -> None:
        self.consensus = ConsensusEngine(strategy=consensus_strategy, quorum=quorum)
        self.memory = AgentMemory(memory_dir=memory_dir)
        self.agents: dict[str, Agent] = {}
        self._init_default_panel()

    def _init_default_panel(self) -> None:
        self.agents["security"] = SecurityAgent(name="security")
        self.agents["docstring"] = DocstringAgent(name="docstring")
        self.agents["test_stub"] = TestStubAgent(name="test_stub")
        self.agents["dependency"] = DependencyAgent(name="dependency")

    def evaluate(self, claim: str, context: dict[str, Any] | None = None) -> ConsensusResult:
        """Run all agents as reviewers on a single claim.

        Uses memory cache if this claim (or a very similar one) was evaluated before.
        """
        # Check memory first
        cached_votes = self.memory.recall(claim)
        if cached_votes is not None:
            result = self.consensus.evaluate(claim, cached_votes)
            result.metadata["cached"] = True
            return result

        votes: list[Vote] = []
        ctx = context or {}

        for _name, agent in self.agents.items():
            vote = self._agent_review(agent, claim, ctx)
            # Apply learned confidence boost if available
            learned = self.memory.get_learned_confidence(vote.agent_role, claim)
            if learned is not None:
                vote.confidence = (vote.confidence + learned) / 2
            votes.append(vote)

        result = self.consensus.evaluate(claim, votes)
        # Store in memory
        self.memory.remember(claim, votes, result.final_verdict.name)
        return result

    def evaluate_batch(self, claims: list[str], context: dict[str, Any] | None = None) -> list[ConsensusResult]:
        return [self.evaluate(claim, context) for claim in claims]

    @staticmethod
    def _review_security(claim_lower: str) -> tuple[Verdict, float, str]:
        risk_keywords = ["eval", "exec", "os.system", "pickle", "secret", "password", "sql"]
        hits = [kw for kw in risk_keywords if kw in claim_lower]
        if hits:
            return (Verdict.REJECT, 0.85, f"Claim contains security-sensitive keyword: {hits[0]}")
        return (Verdict.APPROVE, 0.7, "No obvious security risks detected")

    @staticmethod
    def _review_keyword(claim_lower: str, keywords: list[str], confidence: float, hit_reason: str, miss_reason: str) -> tuple[Verdict, float, str]:
        if any(kw in claim_lower for kw in keywords):
            return (Verdict.APPROVE, confidence, hit_reason)
        return (Verdict.ABSTAIN, 0.5, miss_reason)

    @classmethod
    def _review_outcome(cls, role: str, claim_lower: str) -> tuple[Verdict, float, str]:
        """Pure heuristic dispatch: maps (role, claim) to a verdict tuple."""
        if role == "security_auditor":
            return cls._review_security(claim_lower)
        if role == "documentation_enforcer":
            return cls._review_keyword(
                claim_lower, ["docstring", "document", "missing"], 0.8,
                "Claim relates to documentation improvement", "Claim not documentation-related",
            )
        if role == "test_coverage_analyst":
            return cls._review_keyword(
                claim_lower, ["test", "coverage", "untested"], 0.75,
                "Claim relates to test coverage", "Claim not test-related",
            )
        if role == "architecture_analyst":
            return cls._review_keyword(
                claim_lower, ["dependency", "coupling", "module", "import", "hub", "boundary"], 0.8,
                "Claim relates to architecture", "Claim not architecture-related",
            )
        return (Verdict.ABSTAIN, 0.5, "No specific evaluation logic")

    def _agent_review(self, agent: Agent, claim: str, context: dict[str, Any]) -> Vote:
        """Ask a single agent to review a claim. Returns a Vote."""
        # Simple heuristic-based evaluation (no LLM needed)
        role = agent.role
        verdict, confidence, reasoning = self._review_outcome(role, claim.lower())
        return Vote(
            agent_name=agent.name,
            agent_role=role,
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning,
            weight=self.ROLE_WEIGHTS.get(role, 1.0),
        )

    def filter_approved(self, claims: list[str], context: dict[str, Any] | None = None, min_confidence: float = 0.5) -> list[tuple[str, ConsensusResult]]:
        """Evaluate batch and return only approved claims."""
        results = self.evaluate_batch(claims, context)
        return [
            (claim, result)
            for claim, result in zip(claims, results, strict=False)
            if result.final_verdict == Verdict.APPROVE and result.confidence >= min_confidence
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.consensus.strategy,
            "quorum": self.consensus.quorum,
            "panel_size": len(self.agents),
            "agents": [a.name for a in self.agents.values()],
        }
