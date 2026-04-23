from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext
from app.execution.patch_planner import PatchPlanner
from app.execution.patch_request_generator import PatchRequestGenerator
from app.execution.semantic_patch_generator import SemanticPatchGenerator
from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

from ._context import _target_root


def generate_patch_requests_skill(context: AutomationContext):
    target_root = _target_root(context)
    patch_plan = context.state.get("patch_plan", {})
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    result = PatchRequestGenerator().generate(project_root=target_root, patch_plan=patch_plan, task=task)
    result_dict = result.to_dict()
    context.state["patch_request_generation"] = result_dict
    context.state["patch_requests"] = list(result.patch_requests)
    return result_dict


def generate_semantic_patch_skill(context: AutomationContext):
    target_root = _target_root(context)
    patch_plan = context.state.get("patch_plan", {})
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    result = SemanticPatchGenerator().generate(project_root=target_root, patch_plan=patch_plan, task=task)
    result_dict = result.to_dict()
    context.state["semantic_patch_generation"] = result_dict
    context.state["patch_requests"] = list(result.patch_requests)
    return result_dict


def apply_patch_skill(context: AutomationContext):
    target_root = _target_root(context)
    patch_requests = context.state.get("patch_requests", [])
    if not patch_requests:
        result_dict = {
            "project_root": str(Path(target_root).resolve()),
            "changed_files": [],
            "skipped_files": [],
            "ok": False,
            "error": "No patch_requests provided. Supply context.state['patch_requests'] with patch dictionaries.",
        }
        context.state["patch_apply"] = result_dict
        context.state["changed_files"] = []
        return result_dict

    patches = [
        FilePatch(
            path=item["path"],
            new_content=item["new_content"],
            expected_old_content=item.get("expected_old_content"),
        )
        for item in patch_requests
    ]
    result = ApplyPatchSkill().run(target_root, patches)
    result_dict = {
        "project_root": result.project_root,
        "changed_files": result.changed_files,
        "skipped_files": result.skipped_files,
        "ok": result.ok,
        "error": result.error,
    }
    context.state["patch_apply"] = result_dict
    context.state["changed_files"] = list(result.changed_files)
    return result_dict


def plan_patch_skill(context: AutomationContext):
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    result = PatchPlanner().plan(task)
    result_dict = result.to_dict()
    context.state["patch_plan"] = result_dict
    return result_dict
