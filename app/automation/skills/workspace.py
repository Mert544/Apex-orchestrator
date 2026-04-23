from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext
from app.skills.execution.clone_repo import CloneRepoSkill
from app.skills.execution.prepare_workspace import PrepareWorkspaceSkill

from ._context import _target_root


def prepare_workspace_skill(context: AutomationContext):
    result = PrepareWorkspaceSkill().run(repo_url=context.repo_url, project_root=context.project_root)
    result_dict = {
        "ok": result.ok,
        "workspace_root": result.workspace_root,
        "project_dir": result.project_dir,
        "repo_name": result.repo_name,
        "error": result.error,
    }
    context.state["workspace"] = result_dict
    if result.ok:
        context.workspace_dir = Path(result.project_dir)
    return result_dict


def clone_repo_skill(context: AutomationContext):
    if not context.repo_url:
        result_dict = {
            "ok": False,
            "repo_url": None,
            "workspace_root": "",
            "project_dir": "",
            "error": "repo_url missing for clone_repo skill",
        }
        context.state["cloned_repo"] = result_dict
        return result_dict

    result = CloneRepoSkill().run(context.repo_url)
    result_dict = {
        "ok": result.ok,
        "repo_url": result.repo_url,
        "workspace_root": result.workspace_root,
        "project_dir": result.project_dir,
        "error": result.error,
    }
    context.state["cloned_repo"] = result_dict
    if result.ok:
        context.workspace_dir = Path(result.project_dir)
    return result_dict
