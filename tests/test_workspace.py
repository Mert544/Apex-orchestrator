from pathlib import Path

from app.automation.skills.workspace import prepare_workspace_skill, clone_repo_skill
from app.automation.models import AutomationContext


def test_prepare_workspace_skill(tmp_path: Path):
    ctx = AutomationContext(
        project_root=tmp_path,
        objective="test",
        config={},
    )
    result = prepare_workspace_skill(ctx)
    assert result["ok"] is True
    assert "workspace_root" in result
    assert "project_dir" in result


def test_clone_repo_skill_missing_url(tmp_path: Path):
    ctx = AutomationContext(
        project_root=tmp_path,
        objective="test",
        config={},
        repo_url="",
    )
    result = clone_repo_skill(ctx)
    assert result["ok"] is False
    assert "repo_url missing" in result["error"]
