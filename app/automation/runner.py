from __future__ import annotations

from app.automation.models import AutomationContext, AutomationRunResult, AutomationStepResult
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.automation.registry import SkillAutomationRegistry
from app.plugins.registry import PluginRegistry


class SkillAutomationRunner:
    def __init__(
        self,
        registry: SkillAutomationRegistry,
        plans: dict | None = None,
        plugins: PluginRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.plans = plans or DEFAULT_AUTOMATION_PLANS
        self.plugins = plugins

    def run_plan(self, plan_name: str, context: AutomationContext) -> AutomationRunResult:
        if plan_name not in self.plans:
            raise KeyError(f"Unknown automation plan: {plan_name}")

        result = AutomationRunResult(plan_name=plan_name)
        steps = self.plans[plan_name]

        # Determine step categories for hook firing
        scan_skills = {"profile_project", "decompose_objective", "run_research"}
        patch_skills = {"generate_patch_requests", "generate_semantic_patch", "apply_patch"}
        test_skills = {"run_tests", "verify_changes"}

        before_scan_fired = False
        before_patch_fired = False
        before_test_fired = False

        for idx, step in enumerate(steps):
            skill = self.registry.get(step.skill_name)

            # Fire before-scan hook before first scan step
            if step.skill_name in scan_skills and not before_scan_fired:
                self._run_hook("before_scan", {"context": context, "plan": plan_name})
                before_scan_fired = True

            # Fire before-patch hook before first patch step
            if step.skill_name in patch_skills and not before_patch_fired:
                self._run_hook("before_patch", {"context": context, "plan": plan_name})
                before_patch_fired = True

            # Fire before-test hook before first test step
            if step.skill_name in test_skills and not before_test_fired:
                self._run_hook("before_test", {"context": context, "plan": plan_name})
                before_test_fired = True

            try:
                output = skill(context)
                step_result = AutomationStepResult(
                    step_name=step.name,
                    skill_name=step.skill_name,
                    status="ok",
                    output=output,
                )
                result.final_output = output
            except Exception as exc:
                error_type = _classify_error(exc)
                step_result = AutomationStepResult(
                    step_name=step.name,
                    skill_name=step.skill_name,
                    status="error",
                    error=str(exc),
                    error_type=error_type,
                )
                result.steps.append(step_result)
                break
            result.steps.append(step_result)

            # Fire after-scan hook after last scan step
            if step.skill_name in scan_skills:
                remaining = steps[idx + 1 :]
                if not any(s.skill_name in scan_skills for s in remaining):
                    self._run_hook("after_scan", {"context": context, "plan": plan_name, "output": output})

            # Fire after-patch hook after last patch step
            if step.skill_name in patch_skills:
                remaining = steps[idx + 1 :]
                if not any(s.skill_name in patch_skills for s in remaining):
                    self._run_hook("after_patch", {"context": context, "plan": plan_name, "output": output})

            # Fire after-test hook after last test step
            if step.skill_name in test_skills:
                remaining = steps[idx + 1 :]
                if not any(s.skill_name in test_skills for s in remaining):
                    self._run_hook("after_test", {"context": context, "plan": plan_name, "output": output})

        # Fire on_report at end with final result
        self._run_hook("on_report", {"context": context, "plan": plan_name, "result": result})
        return result

    def _run_hook(self, hook_name: str, context: dict) -> None:
        if self.plugins is not None:
            self.plugins.run_hook(hook_name, context)


def _classify_error(exc: Exception) -> str:
    name = type(exc).__name__
    if name in ("ValueError", "TypeError", "AssertionError", "KeyError"):
        return "validation"
    if name in ("ConnectionError", "TimeoutError", "OSError"):
        return "network"
    if "patch" in name.lower() or " Patch" in str(exc):
        return "patch"
    if "timeout" in str(exc).lower():
        return "timeout"
    return "unknown"
