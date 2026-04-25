from __future__ import annotations

from app.automation.models import (
    AutomationContext,
    AutomationRunResult,
    AutomationStepResult,
)
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

    def run_plan(
        self, plan_name: str, context: AutomationContext
    ) -> AutomationRunResult:
        if plan_name not in self.plans:
            raise KeyError(f"Unknown automation plan: {plan_name}")

        result = AutomationRunResult(plan_name=plan_name)
        steps = self.plans[plan_name]

        scan_skills = {"profile_project", "decompose_objective", "run_research"}
        patch_skills = {
            "generate_patch_requests",
            "generate_semantic_patch",
            "apply_patch",
        }
        test_skills = {"run_tests", "verify_changes"}

        before_scan_fired = False
        before_patch_fired = False
        before_test_fired = False

        for idx, step in enumerate(steps):
            skill = self.registry.get(step.skill_name)

            if step.skill_name in scan_skills and not before_scan_fired:
                self._run_hook("before_scan", {"context": context, "plan": plan_name})
                before_scan_fired = True

            if step.skill_name in patch_skills and not before_patch_fired:
                self._run_hook("before_patch", {"context": context, "plan": plan_name})
                before_patch_fired = True

            if step.skill_name in test_skills and not before_test_fired:
                self._run_hook("before_test", {"context": context, "plan": plan_name})
                before_test_fired = True

            if step.skill_name == "enhanced_safety_check":
                output = skill(context)
                step_result = AutomationStepResult(
                    step_name=step.name,
                    skill_name=step.skill_name,
                    status="ok",
                    output=output,
                )
                result.steps.append(step_result)
                safety_passed = self._evaluate_safety_output(output)
                if not safety_passed:
                    result.final_output = {
                        "blocked": True,
                        "reason": "safety_gate_failed",
                        "details": output,
                    }
                    return result
                continue

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

            if step.skill_name in scan_skills:
                remaining = steps[idx + 1 :]
                if not any(s.skill_name in scan_skills for s in remaining):
                    self._run_hook(
                        "after_scan",
                        {"context": context, "plan": plan_name, "output": output},
                    )

            if step.skill_name in patch_skills:
                remaining = steps[idx + 1 :]
                if not any(s.skill_name in patch_skills for s in remaining):
                    self._run_hook(
                        "after_patch",
                        {"context": context, "plan": plan_name, "output": output},
                    )

            if step.skill_name in test_skills:
                remaining = steps[idx + 1 :]
                if not any(s.skill_name in test_skills for s in remaining):
                    self._run_hook(
                        "after_test",
                        {"context": context, "plan": plan_name, "output": output},
                    )

        self._run_hook(
            "on_report", {"context": context, "plan": plan_name, "result": result}
        )
        return result

    def _evaluate_safety_output(self, output: dict | None) -> bool:
        if output is None:
            return True
        if isinstance(output, dict):
            return (
                output.get("ok") is True
                or output.get("passed") is True
                or output.get("blocked") is False
            )
        return True

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
