from __future__ import annotations

from app.automation.models import AutomationContext, AutomationRunResult, AutomationStepResult
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.automation.registry import SkillAutomationRegistry


class SkillAutomationRunner:
    def __init__(self, registry: SkillAutomationRegistry, plans: dict | None = None) -> None:
        self.registry = registry
        self.plans = plans or DEFAULT_AUTOMATION_PLANS

    def run_plan(self, plan_name: str, context: AutomationContext) -> AutomationRunResult:
        if plan_name not in self.plans:
            raise KeyError(f"Unknown automation plan: {plan_name}")

        result = AutomationRunResult(plan_name=plan_name)
        for step in self.plans[plan_name]:
            skill = self.registry.get(step.skill_name)
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
                step_result = AutomationStepResult(
                    step_name=step.name,
                    skill_name=step.skill_name,
                    status="error",
                    error=str(exc),
                )
                result.steps.append(step_result)
                break
            result.steps.append(step_result)
        return result
