from __future__ import annotations

from app.automation.planner import AutonomousPlanner
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.intent.parser import ParsedIntent


class TestAutonomousPlannerMoreEdges:
    def setup_method(self):
        self.planner = AutonomousPlanner()

    def test_unknown_agent_does_not_inject_steps(self):
        # Agents present but none map to _AGENT_STEPS -> no injection (line 119).
        base_steps = list(DEFAULT_AUTOMATION_PLANS["project_scan"])
        intent = ParsedIntent(
            goal="scan with mystery helper",
            plan_type="project_scan",
            agents=["unknown_agent"],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        scan_skills = {"security_scan", "docstring_scan", "coverage_scan", "dependency_scan"}
        step_skills = {s.skill_name for s in plan.steps}
        assert scan_skills.isdisjoint(step_skills)
        # Steps are unchanged from the base plan (no injection happened).
        assert [s.skill_name for s in plan.steps] == [s.skill_name for s in base_steps]
        assert plan.agents == ["unknown_agent"]

    def test_self_directed_loop_fallback_in_supervised(self):
        # self_directed_loop + non-report mode -> fallback full_autonomous_loop (line 127).
        intent = ParsedIntent(
            goal="apex on apex",
            plan_type="self_directed_loop",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        assert plan.plan_name == "self_directed_loop"
        assert plan.fallback_plan == "full_autonomous_loop"

    def test_self_directed_loop_report_mode_fallback_is_project_scan(self):
        # report mode short-circuits the fallback ladder regardless of plan name.
        intent = ParsedIntent(
            goal="apex on apex",
            plan_type="self_directed_loop",
            agents=[],
            mode="report",
        )
        plan = self.planner.build_plan(intent)
        assert plan.plan_name == "self_directed_loop"
        assert plan.fallback_plan == "project_scan"
        assert plan.can_patch is False

    def test_known_plan_non_special_fallback_is_verify_project(self):
        intent = ParsedIntent(
            goal="patch things",
            plan_type="semantic_patch_loop",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        assert plan.fallback_plan == "verify_project"

    def test_empty_agents_returns_base_steps_unchanged(self):
        base_steps = list(DEFAULT_AUTOMATION_PLANS["project_scan"])
        intent = ParsedIntent(
            goal="scan",
            plan_type="project_scan",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        assert [s.skill_name for s in plan.steps] == [s.skill_name for s in base_steps]
