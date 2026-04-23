from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext
from app.execution.pr_summary_generator import PRSummaryGenerator
from app.runtime.git_adapter import GitAdapter

from ._context import _target_root


def git_diff_skill(context: AutomationContext):
    target_root = _target_root(context)
    git = GitAdapter()
    diff_result = git.diff_stat(target_root)
    status_result = git.status(target_root)
    result_dict = {
        "ok": diff_result.ok and status_result.ok,
        "diff_stat": diff_result.stdout,
        "status_short": status_result.stdout,
        "project_root": str(Path(target_root).resolve()),
    }
    context.state["git_diff"] = result_dict
    return result_dict


def git_commit_skill(context: AutomationContext):
    target_root = _target_root(context)
    changed_files = context.state.get("changed_files", [])
    patch_plan = context.state.get("patch_plan", {})
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    title = str(task.get("title", patch_plan.get("title", "Apex Orchestrator patch")))
    # Prefer PR summary commit_message if available (includes co-authored-by in team mode)
    pr_summary = context.state.get("pr_summary", {})
    commit_message = pr_summary.get("commit_message") or title.strip(".")
    git = GitAdapter()
    # Stage only files we actually changed
    if changed_files:
        git.add(target_root, changed_files)
    commit_result = git.commit(target_root, message=commit_message)
    result_dict = {
        "ok": commit_result.ok,
        "stdout": commit_result.stdout,
        "stderr": commit_result.stderr,
        "commit_message": commit_message,
        "project_root": str(Path(target_root).resolve()),
    }
    context.state["git_commit"] = result_dict
    return result_dict


def generate_pr_summary_skill(context: AutomationContext):
    target_root = _target_root(context)
    changed_files = context.state.get("changed_files", [])
    patch_plan = context.state.get("patch_plan", {})
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    verification = context.state.get("verification", {})
    git_diff = context.state.get("git_diff", {})
    result = PRSummaryGenerator().generate(
        project_root=target_root,
        changed_files=changed_files,
        patch_plan=patch_plan,
        task=task,
        verification=verification,
        git_diff_stat=git_diff.get("diff_stat", ""),
    )
    result_dict = result.to_dict()
    context.state["pr_summary"] = result_dict
    return result_dict
