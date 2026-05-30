from __future__ import annotations

"""LLM Voter — optional LLM-based voting for agents.

When configured with llm.provider != 'none', agents can query the LLM
for more nuanced evaluations instead of heuristic-based voting.
"""

from typing import Any

from app.agents.consensus import Verdict, Vote


class LLMVoter:
    """Provides LLM-based voting capabilities to agents.

    Falls back to heuristic voting when LLM is unavailable.
    """

    def __init__(self, router: Any | None = None) -> None:
        self.router = router

    def vote(
        self,
        agent_name: str,
        agent_role: str,
        claim: str,
        context: dict[str, Any] | None = None,
        weight: float = 1.0,
    ) -> Vote:
        """Generate a vote, using LLM if available, heuristic otherwise."""
        if self.router and self.router.is_available():
            return self._llm_vote(agent_name, agent_role, claim, context, weight)
        return self._heuristic_vote(agent_name, agent_role, claim, weight)

    def _llm_vote(
        self,
        agent_name: str,
        agent_role: str,
        claim: str,
        context: dict[str, Any] | None,
        weight: float,
    ) -> Vote:
        """Query LLM for a structured vote."""
        role_prompts = {
            "security_auditor": "You are a security auditor. Evaluate this claim for security risks.",
            "documentation_enforcer": "You are a documentation expert. Evaluate this claim for documentation quality.",
            "test_coverage_analyst": "You are a QA engineer. Evaluate this claim for testability.",
            "architecture_analyst": "You are a software architect. Evaluate this claim for architectural soundness.",
        }

        prompt = role_prompts.get(agent_role, "You are a software engineering expert.")
        prompt += f"\n\nClaim: {claim}\n\n"
        if context:
            prompt += f"Context: {context}\n\n"
        prompt += """Respond in this exact JSON format:
{
    "verdict": "APPROVE" | "REJECT" | "ABSTAIN",
    "confidence": 0.0 to 1.0,
    "reasoning": "brief explanation"
}
"""

        try:
            response = self.router.complete(prompt, max_tokens=200, temperature=0.2)
            # Parse JSON from response
            import json
            # Extract JSON block
            text = response.get("text", "")
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                data = json.loads(text[start:end+1])
                return Vote(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    verdict=Verdict[data.get("verdict", "ABSTAIN").upper()],
                    confidence=float(data.get("confidence", 0.5)),
                    reasoning=data.get("reasoning", "LLM evaluation"),
                    weight=weight,
                )
        except Exception:
            pass

        # Fallback to heuristic
        return self._heuristic_vote(agent_name, agent_role, claim, weight)

    def _heuristic_vote(
        self,
        agent_name: str,
        agent_role: str,
        claim: str,
        weight: float,
    ) -> Vote:
        """Fallback heuristic voting (same logic as ClaimEvaluator)."""
        claim_lower = claim.lower()

        if agent_role == "security_auditor":
            risk_keywords = ["eval", "exec", "os.system", "pickle", "secret", "password", "sql"]
            if any(kw in claim_lower for kw in risk_keywords):
                return Vote(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    verdict=Verdict.REJECT,
                    confidence=0.85,
                    reasoning="Security-sensitive keyword detected",
                    weight=weight,
                )
            return Vote(
                agent_name=agent_name,
                agent_role=agent_role,
                verdict=Verdict.APPROVE,
                confidence=0.7,
                reasoning="No obvious security risks",
                weight=weight,
            )

        elif agent_role == "documentation_enforcer":
            if "docstring" in claim_lower or "document" in claim_lower:
                return Vote(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    verdict=Verdict.APPROVE,
                    confidence=0.8,
                    reasoning="Documentation-related claim",
                    weight=weight,
                )
            return Vote(
                agent_name=agent_name,
                agent_role=agent_role,
                verdict=Verdict.ABSTAIN,
                confidence=0.5,
                reasoning="Not documentation-related",
                weight=weight,
            )

        elif agent_role == "test_coverage_analyst":
            if "test" in claim_lower or "coverage" in claim_lower:
                return Vote(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    verdict=Verdict.APPROVE,
                    confidence=0.75,
                    reasoning="Test-related claim",
                    weight=weight,
                )
            return Vote(
                agent_name=agent_name,
                agent_role=agent_role,
                verdict=Verdict.ABSTAIN,
                confidence=0.5,
                reasoning="Not test-related",
                weight=weight,
            )

        elif agent_role == "architecture_analyst":
            arch_keywords = ["dependency", "coupling", "module", "import", "hub", "boundary"]
            if any(kw in claim_lower for kw in arch_keywords):
                return Vote(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    verdict=Verdict.APPROVE,
                    confidence=0.8,
                    reasoning="Architecture-related claim",
                    weight=weight,
                )
            return Vote(
                agent_name=agent_name,
                agent_role=agent_role,
                verdict=Verdict.ABSTAIN,
                confidence=0.5,
                reasoning="Not architecture-related",
                weight=weight,
            )

        return Vote(
            agent_name=agent_name,
            agent_role=agent_role,
            verdict=Verdict.ABSTAIN,
            confidence=0.5,
            reasoning="No specific logic",
            weight=weight,
        )
