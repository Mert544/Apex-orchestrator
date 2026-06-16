"""Characterization test for ClaimEvaluator._agent_review refactor.

Proves the refactored _agent_review produces byte-identical Vote output
(across every branch) versus the pre-refactor implementation captured here.
"""
from __future__ import annotations

from app.agents.base import Agent
from app.agents.consensus import Verdict, Vote
from app.agents.evaluator import ClaimEvaluator

ROLE_WEIGHTS = ClaimEvaluator.ROLE_WEIGHTS


def _original_agent_review(agent: Agent, claim: str) -> Vote:
    """Verbatim copy of the original _agent_review heuristic (HEAD snapshot)."""
    claim_lower = claim.lower()
    role = agent.role
    weight = ROLE_WEIGHTS.get(role, 1.0)

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

    return Vote(
        agent_name=agent.name,
        agent_role=role,
        verdict=Verdict.ABSTAIN,
        confidence=0.5,
        reasoning="No specific evaluation logic",
        weight=weight,
    )


class _FakeAgent(Agent):
    pass


def _vote_tuple(v: Vote):
    return (v.agent_name, v.agent_role, v.verdict, v.confidence, v.reasoning, v.weight)


def _agents():
    # one real default-panel agent per role + an unknown-role agent.
    ev = ClaimEvaluator()
    agents = list(ev.agents.values())
    agents.append(_FakeAgent(name="mystery", role="unknown_role"))
    agents.append(_FakeAgent(name="empty", role=""))
    return ev, agents


def _claims():
    base = [
        "",
        "plain claim with nothing special",
        # security branch: each keyword, ordering, casing
        "eval is dangerous",
        "uses exec()",
        "calls os.system to run",
        "pickle load untrusted",
        "stores a secret value",
        "hardcoded password here",
        "raw SQL injection",
        "EVAL EXEC PICKLE",  # multiple hits, casing
        "password and secret and eval",  # first-hit ordering matters
        # docstring branch
        "add a docstring",
        "document the api",
        "missing details",
        "DOCSTRING uppercase",
        # test branch
        "write a test",
        "improve coverage",
        "untested path",
        "TEST CASE",
        # architecture branch
        "reduce dependency",
        "high coupling",
        "split module",
        "import cycle",
        "central hub",
        "crossing boundary",
        # words that overlap across branches
        "documentation about a test module with eval and dependency",
    ]
    return base


def test_agent_review_byte_identical_all_branches():
    ev, agents = _agents()
    mismatches = []
    total = 0
    for agent in agents:
        for claim in _claims():
            total += 1
            got = ev._agent_review(agent, claim, {})
            want = _original_agent_review(agent, claim)
            if _vote_tuple(got) != _vote_tuple(want):
                mismatches.append((agent.role, claim, _vote_tuple(got), _vote_tuple(want)))
    assert not mismatches, f"{len(mismatches)} mismatches: {mismatches[:5]}"
    assert total >= 100  # covers every branch many times
