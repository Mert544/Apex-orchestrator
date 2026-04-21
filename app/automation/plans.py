from __future__ import annotations

from app.automation.models import AutomationStep


DEFAULT_AUTOMATION_PLANS: dict[str, list[AutomationStep]] = {
    "project_scan": [
        AutomationStep(name="profile_project", skill_name="profile_project"),
        AutomationStep(name="decompose_objective", skill_name="decompose_objective"),
        AutomationStep(name="run_research", skill_name="run_research"),
    ],
    "focused_branch": [
        AutomationStep(name="run_research", skill_name="run_research"),
    ],
    "verify_project": [
        AutomationStep(name="profile_project", skill_name="profile_project"),
        AutomationStep(name="run_tests", skill_name="run_tests"),
    ],
}
