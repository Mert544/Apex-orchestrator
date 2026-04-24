from __future__ import annotations

import pytest

from app.intent.parser import IntentParser, ParsedIntent


class TestIntentParser:
    def setup_method(self):
        self.parser = IntentParser()

    def test_security_intent(self):
        result = self.parser.parse("Do a security audit of this project")
        assert result.plan_type == "full_autonomous_loop"
        assert "security_agent" in result.agents
        assert result.mode == "supervised"
        assert "security" in result.rationale.lower()

    def test_docstring_intent(self):
        result = self.parser.parse("Add missing docstrings")
        assert result.plan_type == "semantic_patch_loop"
        assert "docstring_agent" in result.agents
        assert result.mode == "supervised"

    def test_test_coverage_intent(self):
        result = self.parser.parse("Improve test coverage")
        assert result.plan_type == "semantic_patch_loop"
        assert "test_stub_agent" in result.agents

    def test_dependency_intent(self):
        result = self.parser.parse("Analyze dependency coupling")
        assert result.plan_type == "project_scan"
        assert "dependency_agent" in result.agents

    def test_general_scan_fallback(self):
        result = self.parser.parse("Just look at this project")
        assert result.plan_type == "project_scan"
        assert result.agents == []
        assert "general project scan" in result.rationale.lower()

    def test_autonomous_mode_keyword(self):
        result = self.parser.parse("Fix everything autonomously")
        assert result.mode == "autonomous"
        # "autonomous" maps to full_autonomous_loop (higher priority than "fix")
        assert result.plan_type == "full_autonomous_loop"

    def test_report_mode_keyword(self):
        result = self.parser.parse("Security audit only, report mode")
        assert result.mode == "report"
        assert result.plan_type == "full_autonomous_loop"

    def test_explicit_mode_overrides(self):
        result = self.parser.parse("Fix everything autonomously", explicit_mode="report")
        assert result.mode == "report"

    def test_self_improve_intent(self):
        result = self.parser.parse("Run self-improvement on Apex")
        assert result.plan_type == "self_directed_loop"

    def test_turkish_keywords(self):
        result = self.parser.parse("güvenlik denetimi yap")
        assert result.plan_type == "full_autonomous_loop"
        assert "security_agent" in result.agents

    def test_combined_agents(self):
        result = self.parser.parse("Fix security and add docstrings")
        # "fix" + "docstring" → semantic_patch_loop (2 matches) beats "security" → full_autonomous_loop (1 match)
        assert result.plan_type == "semantic_patch_loop"
        assert "security_agent" in result.agents
        assert "docstring_agent" in result.agents

    def test_full_autonomous_intent(self):
        result = self.parser.parse("Run full end-to-end improvement")
        assert result.plan_type == "full_autonomous_loop"
