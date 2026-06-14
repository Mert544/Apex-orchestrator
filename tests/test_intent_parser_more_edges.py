from __future__ import annotations

from app.intent.parser import IntentParser


class TestIntentParserMoreEdges:
    def setup_method(self):
        self.parser = IntentParser()

    def test_empty_goal_falls_back_to_project_scan(self):
        r = self.parser.parse("")
        assert r.plan_type == "project_scan"
        assert r.agents == []
        assert r.mode == "supervised"
        assert "No specific intent detected" in r.rationale

    def test_no_keyword_match_falls_back(self):
        r = self.parser.parse("xyzzy plugh frobnicate")
        assert r.plan_type == "project_scan"
        assert "general project scan" in r.rationale

    def test_explicit_mode_overrides_detection(self):
        r = self.parser.parse("security audit", explicit_mode="report")
        assert r.mode == "report"

    def test_detect_report_mode_from_phrase(self):
        r = self.parser.parse("scan project dry-run")
        assert r.mode == "report"

    def test_detect_autonomous_mode_from_keyword(self):
        r = self.parser.parse("fix everything otomatik")
        assert r.mode == "autonomous"

    def test_tie_break_prefers_more_comprehensive_plan(self):
        # "fix" -> semantic_patch_loop (score 2), "scan" -> project_scan (score 1);
        # equal counts, comprehensiveness tie-break picks semantic_patch_loop.
        r = self.parser.parse("fix and scan")
        assert r.plan_type == "semantic_patch_loop"

    def test_multiword_phrase_keyword_matches_substring(self):
        r = self.parser.parse("please run apex on apex now")
        assert r.plan_type == "self_directed_loop"

    def test_security_intent_collects_agent_and_rationale(self):
        r = self.parser.parse("check for vulnerability")
        assert r.plan_type == "full_autonomous_loop"
        assert r.agents == ["security_agent"]
        assert "security_agent" in r.rationale
        assert "supervised mode" in r.rationale

    def test_turkish_keyword_match(self):
        r = self.parser.parse("güvenlik taraması yap")
        assert r.plan_type == "full_autonomous_loop"
        assert "security_agent" in r.agents

    def test_agents_are_sorted_and_deduplicated(self):
        r = self.parser.parse("add docstrings and improve documentation and docs")
        assert r.agents == ["docstring_agent"]

    def test_supervised_is_default_mode(self):
        r = self.parser.parse("refactor module")
        assert r.mode == "supervised"
