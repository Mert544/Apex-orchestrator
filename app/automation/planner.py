from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.automation.models import AutomationStep
from app.automation.plans import DEFAULT_AUTOMATION_PLANS
from app.automation.smart_planner import SmartPlanner
from app.intent.parser import ParsedIntent
from app.policy.mode import ModePolicy


class AutonomousPlanner:
    """Dynamically build automation plans from user intent + project profile.

    Usage:
        planner = AutonomousPlanner()
        policy = ModePolicy.from_env()
        plan = planner.build_plan(intent, project_profile={"total_files": 42}, policy=policy)
        # plan.steps: list of AutomationStep
        # plan.fallback_plan: str
        # plan.can_patch: bool
    """

    # Agent-specific steps to inject into plans
    _AGENT_STEPS: dict[str, list[AutomationStep]] = {
        "security_agent": [
            AutomationStep(name="security_scan", skill_name="security_scan"),
        ],
        "docstring_agent": [
            AutomationStep(name="docstring_scan", skill_name="docstring_scan"),
        ],
        "test_stub_agent": [
            AutomationStep(name="coverage_scan", skill_name="coverage_scan"),
        ],
        "dependency_agent": [
            AutomationStep(name="dependency_scan", skill_name="dependency_scan"),
        ],
    }

    # Skills that modify files (should be stripped in report mode)
    _PATCH_SKILLS: set[str] = {
        "generate_patch_requests",
        "generate_semantic_patch",
        "apply_patch",
        "repair_from_verification",
        "repair_with_retry",
        "git_commit",
    }

    def __init__(self) -> None:
        self.smart_planner = SmartPlanner()

    def build_plan(
        self,
        intent: ParsedIntent,
        project_profile: dict[str, Any] | None = None,
        policy: ModePolicy | None = None,
    ) -> "DynamicPlan":
        profile = project_profile or {}
        policy = policy or ModePolicy.from_env()

        # 1. Select base plan from intent (or SmartPlanner if no explicit plan)
        base_plan_name = self._select_base_plan(intent, profile)
        steps = list(DEFAULT_AUTOMATION_PLANS.get(base_plan_name, []))

        # 2. Inject agent-specific steps
        steps = self._inject_agent_steps(steps, intent.agents)

        # 3. Filter based on mode — report mode strips all patching skills;
        # supervised/autonomous include patching skills but actual application
        # is controlled by policy.permissions.can_auto_patch at execution time
        can_patch = intent.mode != "report"
        if intent.mode == "report":
            steps = [s for s in steps if s.skill_name not in self._PATCH_SKILLS]

        # 4. Determine fallback
        fallback = self._determine_fallback(base_plan_name, intent.mode)

        return DynamicPlan(
            plan_name=base_plan_name,
            steps=steps,
            agents=intent.agents,
            mode=intent.mode,
            can_patch=can_patch,
            fallback_plan=fallback,
            rationale=intent.rationale,
        )

    def _select_base_plan(self, intent: ParsedIntent, profile: dict[str, Any]) -> str:
        # If intent already has a strong plan type, use it
        if intent.plan_type in DEFAULT_AUTOMATION_PLANS:
            return intent.plan_type
        # Otherwise let SmartPlanner decide from profile
        return self.smart_planner.select_plan(profile)

    def _inject_agent_steps(
        self,
        steps: list[AutomationStep],
        agents: list[str],
    ) -> list[AutomationStep]:
        """Insert agent-specific scan steps right after profile_project / run_research."""
        if not agents:
            return steps

        # Find insertion point: after first scan/research step
        insert_idx = 0
        for idx, step in enumerate(steps):
            if step.skill_name in ("profile_project", "run_research", "decompose_objective"):
                insert_idx = idx + 1

        injected: list[AutomationStep] = []
        for agent in agents:
            if agent in self._AGENT_STEPS:
                injected.extend(self._AGENT_STEPS[agent])

        if injected:
            return steps[:insert_idx] + injected + steps[insert_idx:]
        return steps

    def _determine_fallback(self, plan_name: str, mode: str) -> str:
        if mode == "report":
            return "project_scan"
        if plan_name == "full_autonomous_loop":
            return "semantic_patch_loop"
        if plan_name == "self_directed_loop":
            return "full_autonomous_loop"
        return "verify_project"


@dataclass
class DynamicPlan:
    plan_name: str
    steps: list[AutomationStep]
    agents: list[str]
    mode: str
    can_patch: bool
    fallback_plan: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_name": self.plan_name,
            "steps": [{"name": s.name, "skill_name": s.skill_name} for s in self.steps],
            "agents": self.agents,
            "mode": self.mode,
            "can_patch": self.can_patch,
            "fallback_plan": self.fallback_plan,
            "rationale": self.rationale,
        }
