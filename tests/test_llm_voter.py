from app.agents.llm_voter import LLMVoter
from app.agents.consensus import Verdict


def test_llm_voter_heuristic_security_reject():
    voter = LLMVoter(router=None)  # No LLM, use heuristic
    vote = voter.vote(
        agent_name="sec",
        agent_role="security_auditor",
        claim="Use eval() for configuration",
        weight=1.5,
    )
    assert vote.verdict == Verdict.REJECT
    assert vote.confidence > 0.5
    assert vote.weight == 1.5


def test_llm_voter_heuristic_docstring_approve():
    voter = LLMVoter(router=None)
    vote = voter.vote(
        agent_name="doc",
        agent_role="documentation_enforcer",
        claim="Add docstrings to all functions",
        weight=0.8,
    )
    assert vote.verdict == Verdict.APPROVE
    assert vote.confidence > 0.5


def test_llm_voter_heuristic_test_abstain():
    voter = LLMVoter(router=None)
    vote = voter.vote(
        agent_name="test",
        agent_role="test_coverage_analyst",
        claim="Refactor database layer",
        weight=1.0,
    )
    assert vote.verdict == Verdict.ABSTAIN


def test_llm_voter_architecture_approve():
    voter = LLMVoter(router=None)
    vote = voter.vote(
        agent_name="arch",
        agent_role="architecture_analyst",
        claim="Reduce dependency coupling",
        weight=1.2,
    )
    assert vote.verdict == Verdict.APPROVE


def test_llm_voter_unknown_role_defaults():
    voter = LLMVoter(router=None)
    vote = voter.vote(
        agent_name="unknown",
        agent_role="some_random_role",
        claim="Anything",
    )
    assert vote.verdict == Verdict.ABSTAIN


class _Router:
    """Minimal fake LLM router for exercising the _llm_vote path."""

    def __init__(self, text, available=True):
        self._text = text
        self._available = available

    def is_available(self):
        return self._available

    def complete(self, prompt, **kwargs):
        return {"text": self._text}


def test_llm_vote_parses_json_verdict():
    router = _Router('prefix {"verdict": "APPROVE", "confidence": 0.9, "reasoning": "ok"} suffix')
    vote = LLMVoter(router=router).vote("sec", "security_auditor", "a claim")
    assert vote.verdict == Verdict.APPROVE
    assert vote.confidence == 0.9
    assert vote.reasoning == "ok"


def test_llm_vote_reject_verdict():
    router = _Router('{"verdict": "reject", "confidence": 0.8, "reasoning": "risky"}')
    vote = LLMVoter(router=router).vote("sec", "security_auditor", "claim")
    assert vote.verdict == Verdict.REJECT


def test_llm_vote_bad_json_falls_back_to_heuristic():
    router = _Router("totally not json")
    # Falls back: a pickle claim under security heuristic -> REJECT.
    vote = LLMVoter(router=router).vote("sec", "security_auditor", "uses pickle.loads")
    assert vote.verdict == Verdict.REJECT


def test_llm_vote_unknown_role_prompt_still_parses():
    router = _Router('{"verdict": "ABSTAIN", "confidence": 0.3, "reasoning": "n/a"}')
    vote = LLMVoter(router=router).vote("x", "mystery", "claim")
    assert vote.verdict == Verdict.ABSTAIN
    assert vote.confidence == 0.3
