from __future__ import annotations

import random
import time
from typing import Any

from app.automation.models import AutomationContext, AutomationRunResult, AutomationStepResult
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.automation.planner import DynamicPlan
from app.automation.registry import SkillAutomationRegistry
from app.automation.runner import SkillAutomationRunner
from app.plugins.registry import PluginRegistry


class AdaptiveRunner:
    """Self-monitoring, self-healing automation runner.

    - Retries failed steps with exponential backoff + jitter
    - Falls back to alternative plan on persistent failure
    - Adapts plan when new issues/claims are discovered mid-run
    - Respects supervised mode (asks before patching)
    """

    def __init__(
        self,
        registry: SkillAutomationRegistry,
        plans: dict | None = None,
        plugins: PluginRegistry | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        self.base_runner = SkillAutomationRunner(registry, plans=plans, plugins=plugins)
        self.registry = registry
        self.plans = plans or DEFAULT_AUTOMATION_PLANS
        self.plugins = plugins
        self.max_retries = max_retries
        self.base_delay = base_delay

    def run_plan(self, plan: DynamicPlan, context: AutomationContext) -> AutomationRunResult:
        result = AutomationRunResult(plan_name=plan.plan_name)
        steps = list(plan.steps)
        fallback_used = False

        idx = 0
        while idx < len(steps):
            step = steps[idx]

            # Supervised mode gate before patch skills
            if plan.mode == "supervised" and self._is_patch_skill(step.skill_name):
                if not self._confirm_step(step):
                    step_result = AutomationStepResult(
                        step_name=step.name,
                        skill_name=step.skill_name,
                        status="skipped",
                        output="User declined patch step in supervised mode",
                    )
                    result.steps.append(step_result)
                    idx += 1
                    continue

            # Execute with retry
            step_result = self._execute_with_retry(step, context)
            result.steps.append(step_result)
            result.final_output = step_result.output

            if step_result.status == "ok":
                # Adaptation: discover new issues from output
                new_steps = self._adapt_plan(step_result.output, steps[idx + 1 :])
                if new_steps:
                    steps = steps[: idx + 1] + new_steps + steps[idx + 1 :]
                idx += 1
            else:
                # Failure handling
                if not fallback_used and plan.fallback_plan in self.plans:
                    fallback_steps = self.plans[plan.fallback_plan]
                    steps = steps[:idx] + list(fallback_steps)
                    fallback_used = True
                    # Record fallback transition
                    result.steps.append(
                        AutomationStepResult(
                            step_name="fallback_transition",
                            skill_name="_meta",
                            status="ok",
                            output=f"Falling back to plan '{plan.fallback_plan}'",
                        )
                    )
                    # Continue with fallback steps without incrementing idx
                    continue
                else:
                    # Persistent failure — halt
                    break

        return result

    def _execute_with_retry(self, step: Any, context: AutomationContext) -> AutomationStepResult:
        skill = self.registry.get(step.skill_name)
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                output = skill(context)
                return AutomationStepResult(
                    step_name=step.name,
                    skill_name=step.skill_name,
                    status="ok",
                    output=output,
                )
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt)
                    time.sleep(delay)

        error_type = _classify_error(last_error)
        return AutomationStepResult(
            step_name=step.name,
            skill_name=step.skill_name,
            status="error",
            error=str(last_error),
            error_type=error_type,
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter."""
        exp = self.base_delay * (2 ** (attempt - 1))
        return random.uniform(0, exp)

    def _is_patch_skill(self, skill_name: str) -> bool:
        return skill_name in {
            "generate_patch_requests",
            "generate_semantic_patch",
            "apply_patch",
            "repair_from_verification",
            "repair_with_retry",
            "patch_skill",
        }

    def _confirm_step(self, step: Any) -> bool:
        """Ask user for confirmation in supervised mode."""
        prompt = f"[supervised] Step '{step.name}' ({step.skill_name}) will modify files. Proceed? [y/N]: "
        try:
            answer = input(prompt).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def _adapt_plan(self, output: Any, remaining_steps: list[Any]) -> list[Any]:
        """Inspect step output for new issues and inject follow-up steps."""
        if not isinstance(output, dict):
            return []

        new_steps: list[Any] = []

        # If security issues found and no security_scan in remaining steps
        risks = output.get("risks", [])
        if risks and not any(s.skill_name == "security_scan" for s in remaining_steps):
            from app.automation.models import AutomationStep
            new_steps.append(AutomationStep(name="adapted_security_scan", skill_name="security_scan"))

        # If missing docstrings found and no docstring_scan in remaining steps
        gaps = output.get("gaps_found", 0)
        if gaps and not any(s.skill_name == "docstring_scan" for s in remaining_steps):
            from app.automation.models import AutomationStep
            new_steps.append(AutomationStep(name="adapted_docstring_scan", skill_name="docstring_scan"))

        # If coverage gaps found and no coverage_scan in remaining steps
        coverage = output.get("coverage_ratio", 1.0)
        if coverage < 0.5 and not any(s.skill_name == "coverage_scan" for s in remaining_steps):
            from app.automation.models import AutomationStep
            new_steps.append(AutomationStep(name="adapted_coverage_scan", skill_name="coverage_scan"))

        return new_steps


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
