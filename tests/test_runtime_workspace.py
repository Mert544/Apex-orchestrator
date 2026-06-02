from pathlib import Path

from app.runtime.workspace import WorkspaceInfo, WorkspaceManager


def test_create_workspace(tmp_path):
    mgr = WorkspaceManager(base_dir=tmp_path)
    ws = mgr.create(repo_name="myrepo")
    assert ws.root.exists()
    assert ws.repo_name == "myrepo"
    assert ws.project_dir == ws.root / "myrepo"


def test_create_default_project_name(tmp_path):
    ws = WorkspaceManager(base_dir=tmp_path).create()
    assert ws.project_dir.name == "project"


def test_cleanup_removes_workspace(tmp_path):
    mgr = WorkspaceManager(base_dir=tmp_path)
    ws = mgr.create()
    assert ws.root.exists()
    mgr.cleanup(ws)
    assert not ws.root.exists()


def test_cleanup_accepts_plain_path(tmp_path):
    mgr = WorkspaceManager(base_dir=tmp_path)
    ws = mgr.create()
    mgr.cleanup(ws.root)  # pass a Path, not WorkspaceInfo
    assert not ws.root.exists()


def test_cleanup_missing_is_noop(tmp_path):
    # Cleaning up a non-existent path must not raise.
    WorkspaceManager().cleanup(tmp_path / "nope")


def test_ensure_project_root_creates(tmp_path):
    target = tmp_path / "a" / "b"
    result = WorkspaceManager().ensure_project_root(target)
    assert result.exists()
    assert result == target.resolve()


def test_infer_repo_name():
    mgr = WorkspaceManager()
    assert mgr.infer_repo_name("https://github.com/user/repo.git") == "repo"
    assert mgr.infer_repo_name("https://github.com/user/repo/") == "repo"
    assert mgr.infer_repo_name("git@host:org/proj") == "proj"
    assert mgr.infer_repo_name("") == "project"


def test_workspace_info_dataclass(tmp_path):
    info = WorkspaceInfo(root=tmp_path, project_dir=tmp_path / "p")
    assert info.repo_name is None
