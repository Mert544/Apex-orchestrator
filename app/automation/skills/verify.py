from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext
from app.execution.repair_loop import RepairLoop
from app.execution.retry_engine import RetryEngine
from app.execution.verifier import Verifier
from app.skills.execution.run_tests import RunTestsSkill

from ._context import _target_root


def run_tests_skill(context: AutomationContext):
    target_root = _target_root(context)
    result = RunTestsSkill().run(target_root)
    result_dict = {
        "project_root": result.project_root,
        "commands": result.commands,
        "results": result.results,
        "ok": result.ok,
    }
    context.state["test_run"] = result_dict
    return result_dict


def verify_changes_skill(context: AutomationContext):
    target_root = _target_root(context)
    changed_files = context.state.get("changed_files", [])
    patch_apply = context.state.get("patch_apply")
    if patch_apply and not patch_apply.get("ok", True):
        result_dict = {
            "ok": False,
            "project_root": str(Path(target_root).resolve()),
            "test_summary": {"project_root": str(Path(target_root).resolve()), "commands": [], "results": [], "ok": True},
            "patch_scope": {"ok": True, "changed_file_count": 0, "max_allowed_files": 5, "touched_sensitive_paths": [], "reasons": []},
            "sensitive_edit": {"ok": True, "touched_sensitive_paths": [], "detected_hints": {}},
            "patch_apply": patch_apply,
        }
        context.state["verification"] = result_dict
        return result_dict

    result = Verifier().verify(project_root=target_root, changed_files=changed_files)
    result_dict = result.to_dict()
    result_dict["patch_apply"] = patch_apply or {"ok": True, "changed_files": changed_files, "skipped_files": [], "error": None}
    context.state["verification"] = result_dict
    return result_dict


def repair_from_verification_skill(context: AutomationContext):
    verification = context.state.get("verification", {})
    patch_plan = context.state.get("patch_plan", {})
    result = RepairLoop().run(verification=verification, patch_plan=patch_plan)
    result_dict = result.to_dict()
    context.state["repair_loop"] = result_dict
    return result_dict


def repair_with_retry_skill(context: AutomationContext):
    target_root = _target_root(context)
    verification = context.state.get("verification", {})
    patch_plan = context.state.get("patch_plan", {})
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    max_retries = int(context.config.get("max_retries", 1))
    result = RetryEngine(max_retries=max_retries).run(
        project_root=target_root,
        verification=verification,
        patch_plan=patch_plan,
        task=task,
    )
    result_dict = result.to_dict()
    context.state["retry_engine"] = result_dict
    # If retry succeeded, update changed_files to reflect final state
    if result.status == "success":
        context.state["changed_files"] = list(result.changed_files)
    return result_dict
