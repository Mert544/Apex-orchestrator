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
