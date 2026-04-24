from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.automation.adaptive_runner import AdaptiveRunner
from app.automation.models import AutomationContext, AutomationStep
from app.automation.planner import DynamicPlan
from app.automation.registry import SkillAutomationRegistry
from app.automation.plans import DEFAULT_AUTOMATION_PLANS


class TestAdaptiveRunner:
    def setup_method(self):
        self.registry = SkillAutomationRegistry()
        self.registry.register("ok_skill", lambda ctx: {"status": "ok"})
        self.registry.register("fail_skill", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        self.registry.register("risky_skill", lambda ctx: {"risks": [{"severity": "high"}]})
        self.registry.register("patch_skill", lambda ctx: {"patched": True})
        self.registry.register("security_scan", lambda ctx: {"scanned": True})

        self.runner = AdaptiveRunner(self.registry, max_retries=2, base_delay=0.01)
        self.ctx = AutomationContext(
            project_root=MagicMock(),
            objective="test",
            config={},
        )

    def test_successful_run(self):
        plan = DynamicPlan(
            plan_name="test",
            steps=[AutomationStep(name="s1", skill_name="ok_skill")],
            agents=[],
            mode="autonomous",
            can_patch=True,
            fallback_plan="verify_project",
            rationale="test",
        )
        result = self.runner.run_plan(plan, self.ctx)
        assert len(result.steps) == 1
        assert result.steps[0].status == "ok"

    def test_retry_then_fail(self):
        call_count = [0]
        def flaky(ctx):
            call_count[0] += 1
            if call_count[0] < 2:  # fail on 1st, succeed on 2nd
                raise RuntimeError("flaky")
            return {"status": "ok"}

        self.registry.register("flaky_skill", flaky)
        plan = DynamicPlan(
            plan_name="test",
            steps=[AutomationStep(name="s1", skill_name="flaky_skill")],
            agents=[],
            mode="autonomous",
            can_patch=True,
            fallback_plan="verify_project",
            rationale="test",
        )
        result = self.runner.run_plan(plan, self.ctx)
        assert result.steps[0].status == "ok"
        assert call_count[0] == 2  # 1 retry + final success

    def test_retry_then_fallback(self):
        # Provide fallback plan steps that exist in test registry
        custom_plans = {
            "test_fallback": [AutomationStep(name="fb1", skill_name="ok_skill")],
        }
        runner = AdaptiveRunner(self.registry, plans=custom_plans, max_retries=2, base_delay=0.01)
        plan = DynamicPlan(
            plan_name="test",
            steps=[AutomationStep(name="s1", skill_name="fail_skill")],
            agents=[],
            mode="autonomous",
            can_patch=True,
            fallback_plan="test_fallback",
            rationale="test",
        )
        result = runner.run_plan(plan, self.ctx)
        # Should attempt fail_skill 2 times, then fallback to test_fallback
        step_names = [s.step_name for s in result.steps]
        assert "s1" in step_names
        assert "fallback_transition" in step_names
        assert "fb1" in step_names

    def test_adaptation_injects_security_scan(self):
        plan = DynamicPlan(
            plan_name="test",
            steps=[AutomationStep(name="s1", skill_name="risky_skill")],
            agents=[],
            mode="autonomous",
            can_patch=True,
            fallback_plan="verify_project",
            rationale="test",
        )
        result = self.runner.run_plan(plan, self.ctx)
        step_names = [s.step_name for s in result.steps]
        assert "adapted_security_scan" in step_names

    def test_supervised_mode_skips_patch(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        self.registry.register("mod_skill", lambda ctx: {"done": True})
        plan = DynamicPlan(
            plan_name="test",
            steps=[AutomationStep(name="s1", skill_name="patch_skill")],
            agents=[],
            mode="supervised",
            can_patch=False,
            fallback_plan="verify_project",
            rationale="test",
        )
        result = self.runner.run_plan(plan, self.ctx)
        assert result.steps[0].status == "skipped"

    def test_supervised_mode_accepts_patch(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        plan = DynamicPlan(
            plan_name="test",
            steps=[AutomationStep(name="s1", skill_name="patch_skill")],
            agents=[],
            mode="supervised",
            can_patch=True,
            fallback_plan="verify_project",
            rationale="test",
        )
        result = self.runner.run_plan(plan, self.ctx)
        assert result.steps[0].status == "ok"

    def test_backoff_delay_range(self):
        # Delay should be within [0, base_delay * 2^(attempt-1)]
        d1 = self.runner._backoff_delay(1)
        assert 0 <= d1 <= 0.01
        d2 = self.runner._backoff_delay(2)
        assert 0 <= d2 <= 0.02
        d3 = self.runner._backoff_delay(3)
        assert 0 <= d3 <= 0.04

    def test_is_patch_skill(self):
        assert self.runner._is_patch_skill("apply_patch")
        assert self.runner._is_patch_skill("generate_semantic_patch")
        assert not self.runner._is_patch_skill("run_tests")
        assert not self.runner._is_patch_skill("profile_project")
