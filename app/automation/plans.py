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
    "prepare_repo": [
        AutomationStep(name="prepare_workspace", skill_name="prepare_workspace"),
        AutomationStep(name="profile_project", skill_name="profile_project"),
        AutomationStep(name="run_tests", skill_name="run_tests"),
    ],
    "supervised_patch_loop": [
        AutomationStep(name="run_research", skill_name="run_research"),
        AutomationStep(name="plan_tasks", skill_name="plan_tasks"),
        AutomationStep(name="plan_patch", skill_name="plan_patch"),
        AutomationStep(name="verify_changes", skill_name="verify_changes"),
    ],
}
