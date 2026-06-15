"""Edge/branch pins for `app.automation.planner` not asserted by the canonical suite.

The existing tests in ``test_autonomous_planner*.py`` cover line execution; this
file pins the *branch behaviour* the line-coverage tests leave implicit:

  - the agent-step insertion index uses the LAST matching anchor
    (``profile_project``/``run_research``/``decompose_objective``), not the first,
    so injected scans land after the whole research preamble;
  - the ``decompose_objective`` anchor specifically drives the insertion point;
  - report mode strips EVERY skill in ``_PATCH_SKILLS`` (incl. ``git_commit`` /
    ``repair_with_retry``) while keeping every non-patch step in order;
  - the empty/unknown ``plan_type`` paths delegate to ``SmartPlanner`` with a
    deterministic profile;
  - ``build_plan`` defaults ``project_profile``/``policy`` to falsy → safe;
  - ``DynamicPlan.to_dict`` preserves step order and full field set.

Deterministic, stdlib-only, no network / wall-clock. Style follows
``tests/test_autonomous_planner.py`` (class + ``setup_method``).
"""

from __future__ import annotations

from app.automation.planner import AutonomousPlanner, DynamicPlan
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.intent.parser import ParsedIntent


class TestPlannerInsertionEdges:
    def setup_method(self):
        self.planner = AutonomousPlanner()

    def test_injection_lands_after_last_research_anchor_not_first(self):
        # project_scan base = [profile_project, decompose_objective, run_research];
        # all three are insertion anchors, so insert_idx walks to the LAST one
        # (after run_research). Agent scans therefore land at the tail, not the head.
        intent = ParsedIntent(
            goal="dependency scan",
            plan_type="project_scan",
            agents=["dependency_agent"],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        skills = [s.skill_name for s in plan.steps]
        base = [s.skill_name for s in DEFAULT_AUTOMATION_PLANS["project_scan"]]
        # base preamble is intact and in order, then the injected scan trails it.
        assert skills[: len(base)] == base
        assert skills[len(base):] == ["dependency_scan"]

    def test_decompose_objective_is_an_insertion_anchor(self):
        # A synthetic single-step plan whose only anchor is decompose_objective:
        # injection must land right after it (insert_idx = anchor_idx + 1).
        from app.automation.models import AutomationStep

        custom = "edges_only_decompose"
        original = DEFAULT_AUTOMATION_PLANS.get(custom)
        DEFAULT_AUTOMATION_PLANS[custom] = [
            AutomationStep(name="decompose_objective", skill_name="decompose_objective"),
            AutomationStep(name="tail", skill_name="some_tail_step"),
        ]
        try:
            intent = ParsedIntent(
                goal="x",
                plan_type=custom,
                agents=["security_agent"],
                mode="supervised",
            )
            plan = self.planner.build_plan(intent)
            skills = [s.skill_name for s in plan.steps]
            assert skills == ["decompose_objective", "security_scan", "some_tail_step"]
        finally:
            if original is None:
                DEFAULT_AUTOMATION_PLANS.pop(custom, None)
            else:
                DEFAULT_AUTOMATION_PLANS[custom] = original

    def test_no_anchor_inserts_at_head(self):
        # When NO step matches an anchor, insert_idx stays 0 -> scans go first.
        from app.automation.models import AutomationStep

        custom = "edges_no_anchor"
        original = DEFAULT_AUTOMATION_PLANS.get(custom)
        DEFAULT_AUTOMATION_PLANS[custom] = [
            AutomationStep(name="lonely", skill_name="lonely_step"),
        ]
        try:
            intent = ParsedIntent(
                goal="x",
                plan_type=custom,
                agents=["docstring_agent"],
                mode="supervised",
            )
            plan = self.planner.build_plan(intent)
            skills = [s.skill_name for s in plan.steps]
            assert skills == ["docstring_scan", "lonely_step"]
        finally:
            if original is None:
                DEFAULT_AUTOMATION_PLANS.pop(custom, None)
            else:
                DEFAULT_AUTOMATION_PLANS[custom] = original

    def test_multiple_known_agents_inject_in_listed_order(self):
        # Two known agents -> both scans injected, in the order they appear in
        # intent.agents (deterministic, no set iteration).
        intent = ParsedIntent(
            goal="x",
            plan_type="project_scan",
            agents=["security_agent", "docstring_agent"],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        skills = [s.skill_name for s in plan.steps]
        assert skills[-2:] == ["security_scan", "docstring_scan"]


class TestPlannerModeStripping:
    def setup_method(self):
        self.planner = AutonomousPlanner()

    def test_report_mode_strips_every_patch_skill_keeps_order(self):
        # self_directed_loop carries the widest patch surface (git_commit,
        # repair_with_retry, apply_patch, generate_semantic_patch). Report mode
        # must drop ALL of them and keep the remaining steps in original order.
        intent = ParsedIntent(
            goal="x",
            plan_type="self_directed_loop",
            agents=[],
            mode="report",
        )
        plan = self.planner.build_plan(intent)
        kept = [s.skill_name for s in plan.steps]
        base = [s.skill_name for s in DEFAULT_AUTOMATION_PLANS["self_directed_loop"]]
        patch = AutonomousPlanner._PATCH_SKILLS
        assert all(k not in patch for k in kept)
        # Order preserved: kept == base with patch skills filtered out.
        assert kept == [s for s in base if s not in patch]
        assert plan.can_patch is False

    def test_supervised_mode_retains_patch_skills(self):
        intent = ParsedIntent(
            goal="x",
            plan_type="self_directed_loop",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        skills = {s.skill_name for s in plan.steps}
        # At least one patch skill survives in a non-report mode.
        assert skills & AutonomousPlanner._PATCH_SKILLS
        assert plan.can_patch is True

    def test_git_commit_specifically_stripped_in_report_mode(self):
        intent = ParsedIntent(
            goal="x",
            plan_type="full_autonomous_loop",
            agents=[],
            mode="report",
        )
        plan = self.planner.build_plan(intent)
        skills = [s.skill_name for s in plan.steps]
        assert "git_commit" not in skills
        # A non-patch tail step from the same plan survives the filter.
        assert "generate_pr_summary" in skills


class TestPlannerSmartDelegationAndDefaults:
    def setup_method(self):
        self.planner = AutonomousPlanner()

    def test_empty_plan_type_delegates_to_smart_planner(self):
        # plan_type "" is not in DEFAULT_AUTOMATION_PLANS -> SmartPlanner picks.
        # coverage defaults to 0.0 (<0.3) so SmartPlanner returns full_autonomous_loop.
        intent = ParsedIntent(goal="x", plan_type="", agents=[], mode="supervised")
        plan = self.planner.build_plan(intent, project_profile={"total_files": 10})
        assert plan.plan_name == "full_autonomous_loop"

    def test_smart_planner_healthy_profile_selects_verify_project(self):
        # A healthy profile (good coverage, no hubs/untested) -> verify_project,
        # a real plan key whose default steps are carried into the DynamicPlan.
        intent = ParsedIntent(goal="x", plan_type="nope", agents=[], mode="supervised")
        plan = self.planner.build_plan(
            intent,
            project_profile={"test_coverage": 0.95, "total_files": 5},
        )
        assert plan.plan_name == "verify_project"
        assert [s.skill_name for s in plan.steps] == [
            s.skill_name for s in DEFAULT_AUTOMATION_PLANS["verify_project"]
        ]
        # verify_project is not full/self -> fallback ladder hits the default arm.
        assert plan.fallback_plan == "verify_project"

    def test_build_plan_defaults_profile_and_policy_to_safe(self, monkeypatch):
        # No profile and no policy passed: build_plan must not raise and must use
        # ModePolicy.from_env() without touching the network/disk beyond env.
        intent = ParsedIntent(
            goal="x",
            plan_type="project_scan",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        assert isinstance(plan, DynamicPlan)
        assert plan.plan_name == "project_scan"

    def test_known_plan_type_bypasses_smart_planner(self):
        # When plan_type is a real plan key, profile is ignored for selection.
        intent = ParsedIntent(
            goal="x",
            plan_type="semantic_patch_loop",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(
            intent,
            project_profile={"total_files": 9999, "test_coverage": 0.0},
        )
        assert plan.plan_name == "semantic_patch_loop"


class TestPlannerFallbackLadder:
    def setup_method(self):
        self.planner = AutonomousPlanner()

    def test_full_autonomous_loop_fallback_is_semantic_patch_loop(self):
        intent = ParsedIntent(
            goal="x",
            plan_type="full_autonomous_loop",
            agents=[],
            mode="supervised",
        )
        plan = self.planner.build_plan(intent)
        assert plan.fallback_plan == "semantic_patch_loop"

    def test_report_mode_fallback_short_circuits_to_project_scan(self):
        # report mode wins over any plan-specific fallback rule.
        intent = ParsedIntent(
            goal="x",
            plan_type="full_autonomous_loop",
            agents=[],
            mode="report",
        )
        plan = self.planner.build_plan(intent)
        assert plan.fallback_plan == "project_scan"


class TestDynamicPlanToDict:
    def test_to_dict_preserves_step_order_and_fields(self):
        from app.automation.models import AutomationStep

        steps = [
            AutomationStep(name="a", skill_name="alpha"),
            AutomationStep(name="b", skill_name="beta"),
        ]
        plan = DynamicPlan(
            plan_name="p",
            steps=steps,
            agents=["x_agent"],
            mode="supervised",
            can_patch=True,
            fallback_plan="verify_project",
            rationale="because",
        )
        d = plan.to_dict()
        assert d == {
            "plan_name": "p",
            "steps": [
                {"name": "a", "skill_name": "alpha"},
                {"name": "b", "skill_name": "beta"},
            ],
            "agents": ["x_agent"],
            "mode": "supervised",
            "can_patch": True,
            "fallback_plan": "verify_project",
            "rationale": "because",
        }

    def test_to_dict_empty_steps_yields_empty_list(self):
        plan = DynamicPlan(
            plan_name="p",
            steps=[],
            agents=[],
            mode="report",
            can_patch=False,
            fallback_plan="project_scan",
            rationale="",
        )
        d = plan.to_dict()
        assert d["steps"] == []
        assert d["agents"] == []
        assert d["can_patch"] is False
