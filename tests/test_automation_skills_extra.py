from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext
from app.automation.skills._context import _target_root
from app.automation.skills.safety import (
    check_patch_scope_skill,
    detect_sensitive_edit_skill,
    enhanced_safety_check_skill,
)
from app.automation.skills.workspace import clone_repo_skill, prepare_workspace_skill


def _make_context(project_root: Path, **kwargs) -> AutomationContext:
    return AutomationContext(
        project_root=project_root,
        objective="cover the skills",
        config=kwargs.pop("config", {}),
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# _context._target_root
# --------------------------------------------------------------------------- #


def test_target_root_defaults_to_project_root(tmp_path: Path):
    context = _make_context(tmp_path)
    assert _target_root(context) == tmp_path


def test_target_root_prefers_workspace_dir(tmp_path: Path):
    workspace = tmp_path / "ws"
    context = _make_context(tmp_path, workspace_dir=workspace)
    assert _target_root(context) == workspace


def test_target_root_uses_cloned_repo_project_dir(tmp_path: Path):
    context = _make_context(tmp_path)
    cloned = tmp_path / "cloned"
    context.state["cloned_repo"] = {"project_dir": str(cloned)}
    assert _target_root(context) == cloned


def test_target_root_uses_workspace_state_project_dir(tmp_path: Path):
    context = _make_context(tmp_path)
    prepared = tmp_path / "prepared"
    context.state["workspace"] = {"project_dir": str(prepared)}
    assert _target_root(context) == prepared


def test_target_root_workspace_dir_wins_over_state(tmp_path: Path):
    workspace = tmp_path / "ws"
    context = _make_context(tmp_path, workspace_dir=workspace)
    context.state["cloned_repo"] = {"project_dir": str(tmp_path / "cloned")}
    assert _target_root(context) == workspace


# --------------------------------------------------------------------------- #
# safety.check_patch_scope_skill
# --------------------------------------------------------------------------- #


def test_check_patch_scope_skill_ok(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/main.py", "app/cli.py"]
    result = context.state.get("changed_files")
    out = check_patch_scope_skill(context)
    assert out["ok"] is True
    assert out["changed_file_count"] == 2
    assert context.state["patch_scope"] is out
    assert result == ["app/main.py", "app/cli.py"]


def test_check_patch_scope_skill_flags_sensitive(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/auth.py"]
    out = check_patch_scope_skill(context)
    assert out["ok"] is False
    assert out["touched_sensitive_paths"] == ["app/auth.py"]


def test_check_patch_scope_skill_defaults_to_empty(tmp_path: Path):
    context = _make_context(tmp_path)
    out = check_patch_scope_skill(context)
    assert out["changed_file_count"] == 0
    assert out["ok"] is True


# --------------------------------------------------------------------------- #
# safety.detect_sensitive_edit_skill
# --------------------------------------------------------------------------- #


def test_detect_sensitive_edit_skill_clean(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/main.py"]
    out = detect_sensitive_edit_skill(context)
    assert out["ok"] is True
    assert out["touched_sensitive_paths"] == []
    assert context.state["sensitive_edit"] is out


def test_detect_sensitive_edit_skill_flags(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/auth.py"]
    out = detect_sensitive_edit_skill(context)
    assert out["ok"] is False
    assert out["touched_sensitive_paths"]


# --------------------------------------------------------------------------- #
# safety.enhanced_safety_check_skill
# --------------------------------------------------------------------------- #


def test_enhanced_safety_check_skill_passes(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/main.py"]
    out = enhanced_safety_check_skill(context)
    assert out["blocked"] is False
    assert context.state["safety_gates"] is out
    # not blocked -> no verification scaffolding written
    assert "verification" not in context.state


def test_enhanced_safety_check_skill_blocks_on_secret(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/main.py"]
    context.state["new_code"] = 'password = "supersecret123"'
    out = enhanced_safety_check_skill(context)
    assert out["blocked"] is True
    assert context.state["verification"]["ok"] is False
    assert context.state["verification"]["safety_gates"] is out


def test_enhanced_safety_check_skill_blocks_on_too_many_files(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = [f"app/f{i}.py" for i in range(10)]
    out = enhanced_safety_check_skill(context)
    assert out["blocked"] is True


def test_enhanced_safety_check_skill_respects_config_max_files(tmp_path: Path):
    context = _make_context(
        tmp_path,
        config={"safety": {"max_changed_files": 1}},
    )
    context.state["changed_files"] = ["app/a.py", "app/b.py"]
    out = enhanced_safety_check_skill(context)
    assert out["blocked"] is True


def test_enhanced_safety_check_skill_preserves_existing_verification(tmp_path: Path):
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app/main.py"]
    context.state["new_code"] = 'api_key = "abcdefgh12345678"'
    context.state["verification"] = {"existing": True}
    out = enhanced_safety_check_skill(context)
    assert out["blocked"] is True
    assert context.state["verification"]["existing"] is True
    assert context.state["verification"]["ok"] is False


# --------------------------------------------------------------------------- #
# workspace.prepare_workspace_skill
# --------------------------------------------------------------------------- #


def test_prepare_workspace_skill_with_project_root(tmp_path: Path):
    target = tmp_path / "proj"
    context = _make_context(target)
    out = prepare_workspace_skill(context)
    assert out["ok"] is True
    assert out["repo_name"] == "proj"
    assert out["error"] is None
    assert context.workspace_dir == Path(out["project_dir"])
    assert context.state["workspace"] is out
    assert target.exists()


# --------------------------------------------------------------------------- #
# workspace.clone_repo_skill
# --------------------------------------------------------------------------- #


def test_clone_repo_skill_missing_url(tmp_path: Path):
    context = _make_context(tmp_path)
    out = clone_repo_skill(context)
    assert out["ok"] is False
    assert out["error"] == "repo_url missing for clone_repo skill"
    assert context.state["cloned_repo"] is out
    assert context.workspace_dir is None


def test_clone_repo_skill_success(tmp_path: Path, monkeypatch):
    from app.automation.skills import workspace as workspace_mod
    from app.skills.execution.clone_repo import CloneRepoResult

    project_dir = tmp_path / "myrepo"

    class _FakeCloneSkill:
        def run(self, repo_url, branch=None):
            return CloneRepoResult(
                repo_url=repo_url,
                workspace_root=str(tmp_path),
                project_dir=str(project_dir),
                ok=True,
            )

    monkeypatch.setattr(workspace_mod, "CloneRepoSkill", _FakeCloneSkill)
    context = _make_context(tmp_path, repo_url="https://example.com/myrepo.git")
    out = clone_repo_skill(context)
    assert out["ok"] is True
    assert out["repo_url"] == "https://example.com/myrepo.git"
    assert context.workspace_dir == project_dir
    assert context.state["cloned_repo"] is out


def test_clone_repo_skill_failure(tmp_path: Path, monkeypatch):
    from app.automation.skills import workspace as workspace_mod
    from app.skills.execution.clone_repo import CloneRepoResult

    class _FakeCloneSkill:
        def run(self, repo_url, branch=None):
            return CloneRepoResult(
                repo_url=repo_url,
                workspace_root=str(tmp_path),
                project_dir=str(tmp_path / "x"),
                ok=False,
                error="git clone failed",
            )

    monkeypatch.setattr(workspace_mod, "CloneRepoSkill", _FakeCloneSkill)
    context = _make_context(tmp_path, repo_url="https://example.com/x.git")
    out = clone_repo_skill(context)
    assert out["ok"] is False
    assert out["error"] == "git clone failed"
    assert context.workspace_dir is None
