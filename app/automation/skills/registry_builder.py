from __future__ import annotations

from app.automation.registry import SkillAutomationRegistry

from .research import (
    decompose_objective_skill,
    plan_tasks_skill,
    profile_project_skill,
    run_research_skill,
)
from .workspace import clone_repo_skill, prepare_workspace_skill
from .patch import (
    apply_patch_skill,
    generate_patch_requests_skill,
    generate_semantic_patch_skill,
    plan_patch_skill,
)
from .verify import (
    repair_from_verification_skill,
    repair_with_retry_skill,
    run_tests_skill,
    verify_changes_skill,
)
from .git import (
    generate_pr_summary_skill,
    git_commit_skill,
    git_diff_skill,
)
from .safety import (
    check_patch_scope_skill,
    detect_sensitive_edit_skill,
    enhanced_safety_check_skill,
)
from .telemetry import export_token_report_skill, record_telemetry_skill


def build_default_registry() -> SkillAutomationRegistry:
    registry = SkillAutomationRegistry()
    registry.register("profile_project", profile_project_skill)
    registry.register("decompose_objective", decompose_objective_skill)
    registry.register("run_research", run_research_skill)
    registry.register("prepare_workspace", prepare_workspace_skill)
    registry.register("clone_repo", clone_repo_skill)
    registry.register("run_tests", run_tests_skill)
    registry.register("generate_patch_requests", generate_patch_requests_skill)
    registry.register("generate_semantic_patch", generate_semantic_patch_skill)
    registry.register("apply_patch", apply_patch_skill)
    registry.register("check_patch_scope", check_patch_scope_skill)
    registry.register("detect_sensitive_edit", detect_sensitive_edit_skill)
    registry.register("plan_tasks", plan_tasks_skill)
    registry.register("plan_patch", plan_patch_skill)
    registry.register("verify_changes", verify_changes_skill)
    registry.register("repair_from_verification", repair_from_verification_skill)
    registry.register("repair_with_retry", repair_with_retry_skill)
    registry.register("git_diff", git_diff_skill)
    registry.register("git_commit", git_commit_skill)
    registry.register("generate_pr_summary", generate_pr_summary_skill)
    registry.register("record_telemetry", record_telemetry_skill)
    registry.register("export_token_report", export_token_report_skill)
    registry.register("enhanced_safety_check", enhanced_safety_check_skill)
    return registry
