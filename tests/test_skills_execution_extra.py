from __future__ import annotations

from pathlib import Path

from app.runtime.command_runner import CommandResult
from app.runtime.git_adapter import GitAdapter
from app.runtime.workspace import WorkspaceManager
from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch
from app.skills.execution.clone_repo import CloneRepoSkill
from app.skills.execution.prepare_workspace import PrepareWorkspaceSkill


class _FakeRunner:
    """Stub CommandRunner that records calls and returns a canned result."""

    def __init__(self, result: CommandResult) -> None:
        self._result = result
        self.calls: list[list[str]] = []

    def run(self, spec) -> CommandResult:
        self.calls.append(list(spec.command))
        return self._result


def _ok_result(command: list[str]) -> CommandResult:
    return CommandResult(
        command=command,
        cwd=".",
        returncode=0,
        stdout="cloned",
        stderr="",
        duration_seconds=0.0,
    )


def _fail_result(command: list[str], stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(
        command=command,
        cwd=".",
        returncode=128,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.0,
    )


# --- CloneRepoSkill ---------------------------------------------------------


def test_clone_repo_success_resolves_project_dir(tmp_path: Path):
    runner = _FakeRunner(_ok_result(["git", "clone"]))
    skill = CloneRepoSkill(
        workspace_manager=WorkspaceManager(base_dir=tmp_path),
        git=GitAdapter(runner=runner),
    )

    result = skill.run("https://example.com/acme/widgets.git", branch="main")

    assert result.ok is True
    assert result.error is None
    assert result.repo_url == "https://example.com/acme/widgets.git"
    # project_dir is the resolved path of workspace.project_dir
    assert result.project_dir == str(Path(result.project_dir).resolve())
    assert Path(result.project_dir).name == "widgets"
    assert runner.calls[0][:2] == ["git", "clone"]
    assert "--branch" in runner.calls[0]


def test_clone_repo_failure_uses_stderr(tmp_path: Path):
    runner = _FakeRunner(_fail_result(["git", "clone"], stderr="auth denied"))
    skill = CloneRepoSkill(
        workspace_manager=WorkspaceManager(base_dir=tmp_path),
        git=GitAdapter(runner=runner),
    )

    result = skill.run("https://example.com/acme/widgets.git")

    assert result.ok is False
    assert result.error == "auth denied"
    assert Path(result.workspace_root).exists()


def test_clone_repo_failure_falls_back_to_stdout(tmp_path: Path):
    runner = _FakeRunner(_fail_result(["git", "clone"], stdout="some output"))
    skill = CloneRepoSkill(
        workspace_manager=WorkspaceManager(base_dir=tmp_path),
        git=GitAdapter(runner=runner),
    )

    result = skill.run("https://example.com/acme/widgets.git")

    assert result.ok is False
    assert result.error == "some output"


def test_clone_repo_failure_default_message(tmp_path: Path):
    runner = _FakeRunner(_fail_result(["git", "clone"]))
    skill = CloneRepoSkill(
        workspace_manager=WorkspaceManager(base_dir=tmp_path),
        git=GitAdapter(runner=runner),
    )

    result = skill.run("https://example.com/acme/widgets.git")

    assert result.ok is False
    assert result.error == "git clone failed"


def test_clone_repo_defaults_construct_dependencies():
    skill = CloneRepoSkill()
    assert isinstance(skill.workspace_manager, WorkspaceManager)
    assert isinstance(skill.git, GitAdapter)


# --- ApplyPatchSkill --------------------------------------------------------


def test_apply_patch_creates_new_file_and_missing_dirs(tmp_path: Path):
    result = ApplyPatchSkill().run(
        tmp_path,
        [FilePatch(path="src/new_module.py", new_content="x = 1\n")],
    )

    assert result.ok is True
    assert result.changed_files == ["src/new_module.py"]
    assert result.skipped_files == []
    assert (tmp_path / "src" / "new_module.py").read_text(encoding="utf-8") == "x = 1\n"


def test_apply_patch_overwrites_existing_when_old_matches(tmp_path: Path):
    target = tmp_path / "f.py"
    target.write_text("old\n", encoding="utf-8")

    result = ApplyPatchSkill().run(
        tmp_path,
        [FilePatch(path="f.py", new_content="new\n", expected_old_content="old\n")],
    )

    assert result.ok is True
    assert result.changed_files == ["f.py"]
    assert target.read_text(encoding="utf-8") == "new\n"


def test_apply_patch_skips_when_old_content_mismatch(tmp_path: Path):
    target = tmp_path / "f.py"
    target.write_text("actual\n", encoding="utf-8")

    result = ApplyPatchSkill().run(
        tmp_path,
        [FilePatch(path="f.py", new_content="new\n", expected_old_content="expected\n")],
    )

    assert result.ok is True
    assert result.changed_files == []
    assert result.skipped_files == ["f.py"]
    assert target.read_text(encoding="utf-8") == "actual\n"


def test_apply_patch_skips_missing_file_with_expected_old_content(tmp_path: Path):
    result = ApplyPatchSkill().run(
        tmp_path,
        [FilePatch(path="absent.py", new_content="data\n", expected_old_content="anything\n")],
    )

    assert result.ok is True
    assert result.changed_files == []
    assert result.skipped_files == ["absent.py"]
    assert not (tmp_path / "absent.py").exists()


def test_apply_patch_does_not_create_dirs_when_disabled(tmp_path: Path):
    result = ApplyPatchSkill().run(
        tmp_path,
        [FilePatch(path="deep/nested/file.py", new_content="data\n")],
        create_missing_dirs=False,
    )

    # Parent dir was not created, so write_text raises -> caught as error.
    assert result.ok is False
    assert result.error is not None
    assert result.changed_files == []


def test_apply_patch_rejects_path_escaping_root(tmp_path: Path):
    result = ApplyPatchSkill().run(
        tmp_path,
        [FilePatch(path="../escape.py", new_content="bad\n")],
    )

    assert result.ok is False
    assert result.error is not None
    assert "escapes project root" in result.error
    assert not (tmp_path.parent / "escape.py").exists()


# --- PrepareWorkspaceSkill --------------------------------------------------


def test_prepare_workspace_with_existing_project_root(tmp_path: Path):
    project = tmp_path / "myproj"
    result = PrepareWorkspaceSkill().run(project_root=project)

    assert result.ok is True
    assert result.repo_name == "myproj"
    assert result.project_dir == str(project.resolve())
    assert result.workspace_root == str(project.resolve())
    assert project.exists()


def test_prepare_workspace_creates_from_repo_url(tmp_path: Path):
    skill = PrepareWorkspaceSkill(workspace_manager=WorkspaceManager(base_dir=tmp_path))

    result = skill.run(repo_url="https://example.com/org/cool-repo.git")

    assert result.ok is True
    assert result.repo_name == "cool-repo"
    assert Path(result.project_dir).name == "cool-repo"
    assert Path(result.workspace_root).exists()


def test_prepare_workspace_defaults_repo_name_when_no_url(tmp_path: Path):
    skill = PrepareWorkspaceSkill(workspace_manager=WorkspaceManager(base_dir=tmp_path))

    result = skill.run()

    assert result.ok is True
    assert result.repo_name == "project"


def test_prepare_workspace_returns_error_on_failure(monkeypatch, tmp_path: Path):
    skill = PrepareWorkspaceSkill(workspace_manager=WorkspaceManager(base_dir=tmp_path))

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(skill.workspace_manager, "create", _boom)

    result = skill.run(repo_url="https://example.com/org/repo.git")

    assert result.ok is False
    assert result.workspace_root == ""
    assert result.project_dir == ""
    assert result.error == "disk full"


def test_prepare_workspace_default_constructs_manager():
    skill = PrepareWorkspaceSkill()
    assert isinstance(skill.workspace_manager, WorkspaceManager)
