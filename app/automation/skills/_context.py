from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext


def _target_root(context: AutomationContext):
    target_root = context.project_root
    if context.workspace_dir is not None:
        target_root = context.workspace_dir
    elif context.state.get("cloned_repo", {}).get("project_dir"):
        target_root = Path(context.state["cloned_repo"]["project_dir"])
    elif context.state.get("workspace", {}).get("project_dir"):
        target_root = Path(context.state["workspace"]["project_dir"])
    return target_root
