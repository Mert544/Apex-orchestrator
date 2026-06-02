from __future__ import annotations

import pytest

from app.llm.agent_adapter import AgentLLMAdapter
from app.llm.router import LLMRouter, NoOpProvider


class TestAgentLLMAdapter:
    def test_not_available_when_no_router(self):
        adapter = AgentLLMAdapter()
        assert adapter.is_available() is False

    def test_not_available_when_noop(self):
        router = LLMRouter(NoOpProvider({}))
        adapter = AgentLLMAdapter(router)
        assert adapter.is_available() is False

    def test_analyze_claim_fallback(self):
        adapter = AgentLLMAdapter()
        result = adapter.analyze_claim("eval() is bad", {})
        assert result["verdict"] == "ABSTAIN"
        assert "LLM not configured" in result["reasoning"]

    def test_generate_patch_fallback(self):
        adapter = AgentLLMAdapter()
        assert adapter.generate_patch("fix eval", "eval(x)") == ""

    def test_summarize_results_fallback(self):
        adapter = AgentLLMAdapter()
        assert adapter.summarize_results([{"a": 1}]) == ""

    def test_parse_json_plain(self):
        router = LLMRouter(NoOpProvider({}))
        adapter = AgentLLMAdapter(router)
        parsed = adapter._parse_json_response('{"verdict": "REJECT", "confidence": 0.9}')
        assert parsed["verdict"] == "REJECT"

    def test_parse_json_markdown(self):
        router = LLMRouter(NoOpProvider({}))
        adapter = AgentLLMAdapter(router)
        parsed = adapter._parse_json_response('```json\n{"verdict": "APPROVE"}\n```')
        assert parsed["verdict"] == "APPROVE"

    def test_parse_json_invalid(self):
        router = LLMRouter(NoOpProvider({}))
        adapter = AgentLLMAdapter(router)
        parsed = adapter._parse_json_response('not json')
        assert parsed["verdict"] == "ABSTAIN"


class _Resp:
    def __init__(self, content):
        self.content = content


class _Router:
    is_enabled = True

    def __init__(self, content):
        self._content = content

    def complete(self, prompt, system=None):
        return _Resp(self._content)


def test_analyze_claim_with_llm_json():
    from app.llm.agent_adapter import AgentLLMAdapter
    adapter = AgentLLMAdapter(router=_Router('{"verdict": "APPROVE", "confidence": 0.8, "reasoning": "ok"}'))
    result = adapter.analyze_claim("claim", {"k": "v"})
    assert result["verdict"] == "APPROVE"
    assert result["confidence"] == 0.8


def test_analyze_claim_bad_json_abstains():
    from app.llm.agent_adapter import AgentLLMAdapter
    adapter = AgentLLMAdapter(router=_Router("not json"))
    result = adapter.analyze_claim("claim", {})
    assert result["verdict"] == "ABSTAIN"


def test_analyze_claim_no_router_abstains():
    from app.llm.agent_adapter import AgentLLMAdapter
    result = AgentLLMAdapter(router=None).analyze_claim("claim", {})
    assert result["verdict"] == "ABSTAIN"
    assert "not configured" in result["reasoning"]


def test_generate_patch_returns_content():
    from app.llm.agent_adapter import AgentLLMAdapter
    adapter = AgentLLMAdapter(router=_Router("  fixed code  "))
    assert adapter.generate_patch("eval risk", "eval(x)") == "fixed code"


def test_generate_patch_no_router_empty():
    from app.llm.agent_adapter import AgentLLMAdapter
    assert AgentLLMAdapter(router=None).generate_patch("i", "c") == ""


def test_summarize_results():
    from app.llm.agent_adapter import AgentLLMAdapter
    adapter = AgentLLMAdapter(router=_Router("summary text"))
    out = adapter.summarize_results([{"finding": "x"}])
    assert out == "summary text"


def test_analyze_claim_router_raises_abstains():
    from app.llm.agent_adapter import AgentLLMAdapter

    class _Boom:
        is_enabled = True
        def complete(self, prompt, system=None):
            raise RuntimeError("net down")

    result = AgentLLMAdapter(router=_Boom()).analyze_claim("c", {})
    assert result["verdict"] == "ABSTAIN"
    assert "error" in result["reasoning"].lower()
