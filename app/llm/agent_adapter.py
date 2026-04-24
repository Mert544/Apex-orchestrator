from __future__ import annotations

from typing import Any

from app.llm.router import LLMRouter, LLMResponse


class AgentLLMAdapter:
    """Adapter that lets agents use LLM for reasoning when configured.

    Falls back to deterministic logic if LLM is disabled or fails.
    """

    def __init__(self, router: LLMRouter | None = None) -> None:
        self.router = router

    def is_available(self) -> bool:
        return self.router is not None and self.router.is_enabled

    def analyze_claim(self, claim: str, context: dict[str, Any]) -> dict[str, Any]:
        """Ask LLM to analyze a code claim and return structured verdict."""
        if not self.is_available():
            return {"verdict": "ABSTAIN", "confidence": 0.0, "reasoning": "LLM not configured"}

        system = (
            "You are a senior code reviewer. Analyze the claim and respond ONLY with JSON: "
            '{"verdict": "APPROVE|REJECT|ABSTAIN", "confidence": 0.0-1.0, "reasoning": "..."}'
        )
        prompt = f"Claim: {claim}\nContext: {json.dumps(context)}\nRespond with JSON only."
        try:
            resp = self.router.complete(prompt, system=system)
            return self._parse_json_response(resp.content)
        except Exception as exc:
            return {"verdict": "ABSTAIN", "confidence": 0.0, "reasoning": f"LLM error: {exc}"}

    def generate_patch(self, issue: str, code_snippet: str) -> str:
        """Ask LLM to generate a fix for an issue."""
        if not self.is_available():
            return ""

        system = (
            "You are an expert Python developer. Given an issue and code snippet, "
            "return ONLY the fixed code block. No explanations."
        )
        prompt = f"Issue: {issue}\nCode:\n{code_snippet}\n\nFixed code:"
        try:
            resp = self.router.complete(prompt, system=system)
            return resp.content.strip()
        except Exception:
            return ""

    def summarize_results(self, results: list[dict[str, Any]]) -> str:
        """Ask LLM to summarize agent findings."""
        if not self.is_available():
            return ""

        system = "Summarize the following security/code findings in 3 bullet points."
        prompt = "Findings:\n" + "\n".join(f"- {r}" for r in results)
        try:
            resp = self.router.complete(prompt, system=system)
            return resp.content.strip()
        except Exception:
            return ""

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        import json
        import re
        # Extract JSON from markdown code block if present
        match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if match:
            content = match.group(1)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"verdict": "ABSTAIN", "confidence": 0.0, "reasoning": "Failed to parse LLM response"}
