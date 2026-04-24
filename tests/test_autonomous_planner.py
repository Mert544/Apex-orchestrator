from __future__ import annotations

import pytest

from app.automation.planner import AutonomousPlanner, DynamicPlan
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.intent.parser import IntentParser, ParsedIntent


class TestAutonomousPlanner:
    def setup_method(self):
        self.planner = AutonomousPlanner()
        self.intent_parser = IntentParser()

    def test_security_intent_plan(self):
        intent = self.intent_parser.parse("security audit")
        plan = self.planner.build_plan(intent)
        assert plan.plan_name == "full_autonomous_loop"
        assert "security_scan" in [s.skill_name for s in plan.steps]
        assert plan.can_patch is True
        assert plan.fallback_plan == "semantic_patch_loop"

    def test_report_mode_strips_patches(self):
        intent = self.intent_parser.parse("security audit", explicit_mode="report")
        plan = self.planner.build_plan(intent)
        assert plan.mode == "report"
        assert plan.can_patch is False
        patch_skills = {"generate_patch_requests", "generate_semantic_patch", "apply_patch"}
        step_skills = {s.skill_name for s in plan.steps}
        assert patch_skills.isdisjoint(step_skills), f"Patch skills found: {patch_skills & step_skills}"
        assert plan.fallback_plan == "project_scan"

    def test_docstring_intent_injects_scan(self):
        intent = self.intent_parser.parse("add docstrings")
        plan = self.planner.build_plan(intent)
        assert plan.plan_name == "semantic_patch_loop"
        assert "docstring_scan" in [s.skill_name for s in plan.steps]
        assert "docstring_agent" in plan.agents

    def test_test_stub_intent_injects_scan(self):
        intent = self.intent_parser.parse("improve test coverage")
        plan = self.planner.build_plan(intent)
        assert plan.plan_name == "semantic_patch_loop"
        assert "coverage_scan" in [s.skill_name for s in plan.steps]
        assert "test_stub_agent" in plan.agents

    def test_dependency_intent_plan(self):
        intent = self.intent_parser.parse("analyze dependency coupling")
        plan = self.planner.build_plan(intent)
        assert plan.plan_name == "project_scan"
        assert "dependency_scan" in [s.skill_name for s in plan.steps]

    def test_no_agents_no_injection(self):
        intent = self.intent_parser.parse("scan project")
        plan = self.planner.build_plan(intent)
        assert plan.agents == []
        scan_skills = {"security_scan", "docstring_scan", "coverage_scan", "dependency_scan"}
        step_skills = {s.skill_name for s in plan.steps}
        assert scan_skills.isdisjoint(step_skills)

    def test_dynamic_plan_to_dict(self):
        intent = self.intent_parser.parse("security audit")
        plan = self.planner.build_plan(intent)
        d = plan.to_dict()
        assert d["plan_name"] == "full_autonomous_loop"
        assert "steps" in d
        assert d["mode"] == "supervised"
        assert d["can_patch"] is True

    def test_smart_planner_fallback(self):
        intent = ParsedIntent(goal="unknown", plan_type="unknown_plan", agents=[], mode="supervised")
        # When plan_type is unknown, SmartPlanner kicks in
        plan = self.planner.build_plan(intent, project_profile={"total_files": 50, "dependency_hubs": ["a", "b", "c"]})
        # SmartPlanner sees coverage=0.0 (<0.3) → full_autonomous_loop
        assert plan.plan_name == "full_autonomous_loop"

    def test_autonomous_mode_keeps_patches(self):
        intent = self.intent_parser.parse("fix everything", explicit_mode="autonomous")
        plan = self.planner.build_plan(intent)
        assert plan.mode == "autonomous"
        assert plan.can_patch is True
        assert "apply_patch" in [s.skill_name for s in plan.steps]

    def test_multiple_agents_injected(self):
        intent = self.intent_parser.parse("fix security and add docstrings")
        plan = self.planner.build_plan(intent)
        assert "security_scan" in [s.skill_name for s in plan.steps]
        assert "docstring_scan" in [s.skill_name for s in plan.steps]
