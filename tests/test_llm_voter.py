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


def test_heuristic_security_auditor_approves_without_risk_keyword():
    # Line 109: security role, no risk keyword -> APPROVE with default confidence.
    voter = LLMVoter(router=None)
    vote = voter.vote("sec", "security_auditor", "Improve the README layout")
    assert vote.verdict == Verdict.APPROVE
    assert vote.confidence == 0.7
    assert vote.reasoning == "No obvious security risks"


def test_heuristic_documentation_enforcer_abstains_when_unrelated():
    # Line 128: doc role, claim has no doc keywords -> ABSTAIN.
    voter = LLMVoter(router=None)
    vote = voter.vote("doc", "documentation_enforcer", "Optimize the SQL query plan")
    assert vote.verdict == Verdict.ABSTAIN
    assert vote.reasoning == "Not documentation-related"


def test_heuristic_test_analyst_approves_test_related_claim():
    # Line 139: test role, claim mentions coverage -> APPROVE.
    voter = LLMVoter(router=None)
    vote = voter.vote("qa", "test_coverage_analyst", "Increase coverage of the parser")
    assert vote.verdict == Verdict.APPROVE
    assert vote.confidence == 0.75
    assert vote.reasoning == "Test-related claim"


def test_heuristic_architecture_analyst_abstains_when_unrelated():
    # Line 167: arch role, no architecture keywords -> ABSTAIN.
    voter = LLMVoter(router=None)
    vote = voter.vote("arch", "architecture_analyst", "Rename a variable for clarity")
    assert vote.verdict == Verdict.ABSTAIN
    assert vote.reasoning == "Not architecture-related"


class _RecordingRouter:
    """Captures the prompt sent so we can assert the context branch ran."""

    def __init__(self, text):
        self._text = text
        self.last_prompt = None

    def is_available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.last_prompt = prompt
        return {"text": self._text}


def test_llm_vote_includes_context_in_prompt():
    # Line 54-55: when context is provided, it is appended to the prompt.
    router = _RecordingRouter('{"verdict": "APPROVE", "confidence": 0.9, "reasoning": "ok"}')
    vote = LLMVoter(router=router).vote(
        "sec",
        "security_auditor",
        "a claim",
        context={"file": "auth.py", "line": 42},
    )
    assert vote.verdict == Verdict.APPROVE
    assert "Context:" in router.last_prompt
    assert "auth.py" in router.last_prompt


class _RaisingRouter:
    """Available router whose complete() raises, forcing the heuristic fallback."""

    def is_available(self):
        return True

    def complete(self, prompt, **kwargs):
        raise RuntimeError("LLM backend down")


def test_llm_vote_complete_exception_falls_back_to_heuristic():
    # Lines 82-83: router.complete raises -> swallowed, heuristic used instead.
    voter = LLMVoter(router=_RaisingRouter())
    vote = voter.vote("sec", "security_auditor", "Run eval() on user input")
    assert vote.verdict == Verdict.REJECT
    assert vote.reasoning == "Security-sensitive keyword detected"


def test_llm_vote_unavailable_router_uses_heuristic():
    # Line 32-34: router present but not available -> heuristic path.
    router = _Router('{"verdict": "APPROVE"}', available=False)
    vote = LLMVoter(router=router).vote("sec", "security_auditor", "uses pickle")
    assert vote.verdict == Verdict.REJECT


def test_llm_vote_no_json_braces_falls_back():
    # start/end == -1 path (lines 72-73 skipped) -> heuristic fallback.
    router = _Router("no braces at all here")
    vote = LLMVoter(router=router).vote("doc", "documentation_enforcer", "add docstrings")
    assert vote.verdict == Verdict.APPROVE
    assert vote.reasoning == "Documentation-related claim"
