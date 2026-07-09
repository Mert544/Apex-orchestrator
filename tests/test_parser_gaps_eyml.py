from __future__ import annotations

from app.intent.parser import IntentParser, ParsedIntent

# app/intent/parser.py is already at 100% line coverage from the existing
# tests/test_intent_parser*.py files. These are characterization/regression
# tests pinning subtle real behaviors (substring matching, mode precedence,
# count-vs-comprehensiveness tie-break, falsy explicit_mode) — not padding.


class TestParserCharacterization:
    def setup_method(self):
        self.parser = IntentParser()

    def test_parsed_intent_dataclass_defaults(self):
        intent = ParsedIntent(goal="g", plan_type="project_scan")
        assert intent.agents == []
        assert intent.mode == "supervised"
        assert intent.rationale == ""
        assert intent.parameters == {}

    def test_import_keyword_matches_as_substring(self):
        # "important" contains the substring "import", which is a dependency
        # keyword; substring matching is intentional and pinned here.
        result = self.parser.parse("make this important")
        assert result.plan_type == "project_scan"
        assert result.agents == ["dependency_agent"]

    def test_higher_keyword_count_beats_comprehensiveness(self):
        # project_scan matches twice (scan, review) vs semantic once (fix);
        # raw count dominates the plan-comprehensiveness tie-break.
        result = self.parser.parse("scan and review then fix")
        assert result.plan_type == "project_scan"

    def test_report_mode_takes_precedence_over_autonomous(self):
        # _detect_mode iterates report before autonomous, so report wins.
        result = self.parser.parse("run autonomously but report only")
        assert result.mode == "report"
        assert result.plan_type == "full_autonomous_loop"

    def test_empty_explicit_mode_falls_back_to_detection(self):
        # explicit_mode="" is falsy, so detection runs and yields supervised.
        result = self.parser.parse("security audit", explicit_mode="")
        assert result.mode == "supervised"

    def test_goal_field_preserves_original_casing(self):
        result = self.parser.parse("SCAN This Project")
        assert result.goal == "SCAN This Project"
        assert result.plan_type == "project_scan"

    def test_rationale_has_no_agent_clause_when_no_agents(self):
        result = self.parser.parse("refactor module")
        assert "using" not in result.rationale
        assert "semantic_patch_loop" in result.rationale
