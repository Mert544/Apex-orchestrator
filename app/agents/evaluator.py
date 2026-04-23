from __future__ import annotations

"""Claim Evaluator — routes claims to relevant agents for peer review."""

from typing import Any

from app.agents.base import Agent
from app.agents.consensus import ConsensusEngine, ConsensusResult, Verdict, Vote
from app.agents.skills import SecurityAgent, DocstringAgent, TestStubAgent, DependencyAgent


class ClaimEvaluator:
    """Evaluates claims using a panel of specialist agents.

    Each agent reviews the claim from its own perspective:
    - SecurityAgent: "Does this claim introduce security risks?"
    - DocstringAgent: "Is this claim well-documented?"
    - TestStubAgent: "Can this claim be tested?"
    - DependencyAgent: "Is this claim architecturally sound?"
    """

    ROLE_WEIGHTS = {
        "security_auditor": 1.5,
        "documentation_enforcer": 0.8,
        "test_coverage_analyst": 1.0,
        "architecture_analyst": 1.2,
    }

    def __init__(self, consensus_strategy: str = "majority", quorum: int = 2) -> None:
        self.consensus = ConsensusEngine(strategy=consensus_strategy, quorum=quorum)
        self.agents: dict[str, Agent] = {}
        self._init_default_panel()

    def _init_default_panel(self) -> None:
        self.agents["security"] = SecurityAgent(name="security")
        self.agents["docstring"] = DocstringAgent(name="docstring")
        self.agents["test_stub"] = TestStubAgent(name="test_stub")
        self.agents["dependency"] = DependencyAgent(name="dependency")

    def evaluate(self, claim: str, context: dict[str, Any] | None = None) -> ConsensusResult:
        """Run all agents as reviewers on a single claim."""
        votes: list[Vote] = []
        ctx = context or {}

        for name, agent in self.agents.items():
            vote = self._agent_review(agent, claim, ctx)
            votes.append(vote)

        return self.consensus.evaluate(claim, votes)

    def evaluate_batch(self, claims: list[str], context: dict[str, Any] | None = None) -> list[ConsensusResult]:
        return [self.evaluate(claim, context) for claim in claims]

    def _agent_review(self, agent: Agent, claim: str, context: dict[str, Any]) -> Vote:
        """Ask a single agent to review a claim. Returns a Vote."""
        # Simple heuristic-based evaluation (no LLM needed)
        claim_lower = claim.lower()
        role = agent.role
        weight = self.ROLE_WEIGHTS.get(role, 1.0)

        # Security agent logic
        if role == "security_auditor":
            risk_keywords = ["eval", "exec", "os.system", "pickle", "secret", "password", "sql"]
            if any(kw in claim_lower for kw in risk_keywords):
                return Vote(
                    agent_name=agent.name,
                    agent_role=role,
                    verdict=Verdict.REJECT,
                    confidence=0.85,
                    reasoning=f"Claim contains security-sensitive keyword: {[kw for kw in risk_keywords if kw in claim_lower][0]}",
                    weight=weight,
                )
            return Vote(
                agent_name=agent.name,
                agent_role=role,
                verdict=Verdict.APPROVE,
                confidence=0.7,
                reasoning="No obvious security risks detected",
                weight=weight,
            )

        # Docstring agent logic
        if role == "documentation_enforcer":
            if "docstring" in claim_lower or "document" in claim_lower or "missing" in claim_lower:
                return Vote(
                    agent_name=agent.name,
                    agent_role=role,
                    verdict=Verdict.APPROVE,
                    confidence=0.8,
                    reasoning="Claim relates to documentation improvement",
                    weight=weight,
                )
            return Vote(
                agent_name=agent.name,
                agent_role=role,
                verdict=Verdict.ABSTAIN,
                confidence=0.5,
                reasoning="Claim not documentation-related",
                weight=weight,
            )

        # Test stub agent logic
        if role == "test_coverage_analyst":
            if "test" in claim_lower or "coverage" in claim_lower or "untested" in claim_lower:
                return Vote(
                    agent_name=agent.name,
                    agent_role=role,
                    verdict=Verdict.APPROVE,
                    confidence=0.75,
                    reasoning="Claim relates to test coverage",
                    weight=weight,
                )
            return Vote(
                agent_name=agent.name,
                agent_role=role,
                verdict=Verdict.ABSTAIN,
                confidence=0.5,
                reasoning="Claim not test-related",
                weight=weight,
            )

        # Dependency agent logic
        if role == "architecture_analyst":
            arch_keywords = ["dependency", "coupling", "module", "import", "hub", "boundary"]
            if any(kw in claim_lower for kw in arch_keywords):
                return Vote(
                    agent_name=agent.name,
                    agent_role=role,
                    verdict=Verdict.APPROVE,
                    confidence=0.8,
                    reasoning="Claim relates to architecture",
                    weight=weight,
                )
            return Vote(
                agent_name=agent.name,
                agent_role=role,
                verdict=Verdict.ABSTAIN,
                confidence=0.5,
                reasoning="Claim not architecture-related",
                weight=weight,
            )

        # Default
        return Vote(
            agent_name=agent.name,
            agent_role=role,
            verdict=Verdict.ABSTAIN,
            confidence=0.5,
            reasoning="No specific evaluation logic",
            weight=weight,
        )

    def filter_approved(self, claims: list[str], context: dict[str, Any] | None = None, min_confidence: float = 0.5) -> list[tuple[str, ConsensusResult]]:
        """Evaluate batch and return only approved claims."""
        results = self.evaluate_batch(claims, context)
        return [
            (claim, result)
            for claim, result in zip(claims, results)
            if result.final_verdict == Verdict.APPROVE and result.confidence >= min_confidence
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.consensus.strategy,
            "quorum": self.consensus.quorum,
            "panel_size": len(self.agents),
            "agents": [a.name for a in self.agents.values()],
        }
