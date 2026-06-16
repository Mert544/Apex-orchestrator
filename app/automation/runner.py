from __future__ import annotations

from app.automation.models import (
    AutomationContext,
    AutomationRunResult,
    AutomationStepResult,
)
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.automation.registry import SkillAutomationRegistry
from app.plugins.registry import PluginRegistry

# (skill-category set, before-hook, after-hook) — drives the per-phase hooks.
_HOOK_PHASES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"profile_project", "decompose_objective", "run_research"}),
        "before_scan",
        "after_scan",
    ),
    (
        frozenset({
            "generate_patch_requests",
            "generate_semantic_patch",
            "apply_patch",
        }),
        "before_patch",
        "after_patch",
    ),
    (
        frozenset({"run_tests", "verify_changes"}),
        "before_test",
        "after_test",
    ),
)


def _is_last_of_category(steps: list, idx: int, category: frozenset[str]) -> bool:
    """True if no later step shares ``category`` — so its after-hook fires now."""
    return not any(s.skill_name in category for s in steps[idx + 1 :])


def _ok_step_result(step, output) -> AutomationStepResult:
    """The ``status="ok"`` step record for ``step`` carrying ``output``."""
    return AutomationStepResult(
        step_name=step.name,
        skill_name=step.skill_name,
        status="ok",
        output=output,
    )


def _error_step_result(step, exc: Exception) -> AutomationStepResult:
    """The ``status="error"`` step record classifying ``exc``."""
    return AutomationStepResult(
        step_name=step.name,
        skill_name=step.skill_name,
        status="error",
        error=str(exc),
        error_type=_classify_error(exc),
    )


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
        before_fired: set[str] = set()

        for idx, step in enumerate(steps):
            skill = self.registry.get(step.skill_name)
            self._fire_before_hooks(step, plan_name, context, before_fired)

            if step.skill_name == "enhanced_safety_check":
                output = skill(context)
                result.steps.append(_ok_step_result(step, output))
                if not self._evaluate_safety_output(output):
                    result.final_output = {
                        "blocked": True,
                        "reason": "safety_gate_failed",
                        "details": output,
                    }
                    return result
                continue

            try:
                output = skill(context)
                step_result = _ok_step_result(step, output)
                result.final_output = output
            except Exception as exc:
                result.steps.append(_error_step_result(step, exc))
                break
            result.steps.append(step_result)
            self._fire_after_hooks(step, idx, steps, plan_name, context, output)

        self._run_hook(
            "on_report", {"context": context, "plan": plan_name, "result": result}
        )
        return result

    def _fire_before_hooks(
        self, step, plan_name: str, context, fired: set[str]
    ) -> None:
        """Fire each phase's before-hook once, the first time its category runs."""
        for category, before, _ in _HOOK_PHASES:
            if step.skill_name in category and before not in fired:
                self._run_hook(before, {"context": context, "plan": plan_name})
                fired.add(before)

    def _fire_after_hooks(
        self, step, idx: int, steps: list, plan_name: str, context, output
    ) -> None:
        """Fire a phase's after-hook when ``step`` is the last of its category."""
        for category, _, after in _HOOK_PHASES:
            if step.skill_name in category and _is_last_of_category(
                steps, idx, category
            ):
                self._run_hook(
                    after,
                    {"context": context, "plan": plan_name, "output": output},
                )

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
        if self.plugins is None:
            return
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
