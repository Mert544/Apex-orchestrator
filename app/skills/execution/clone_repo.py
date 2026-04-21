from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.runtime.git_adapter import GitAdapter
from app.runtime.workspace import WorkspaceManager


@dataclass
class CloneRepoResult:
    repo_url: str
    workspace_root: str
    project_dir: str
    ok: bool
    error: str | None = None


class CloneRepoSkill:
    def __init__(self, workspace_manager: WorkspaceManager | None = None, git: GitAdapter | None = None) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.git = git or GitAdapter()

    def run(self, repo_url: str, branch: str | None = None) -> CloneRepoResult:
        repo_name = self.workspace_manager.infer_repo_name(repo_url)
        workspace = self.workspace_manager.create(repo_name=repo_name)
        result = self.git.clone(repo_url=repo_url, destination=workspace.project_dir, branch=branch)
        if not result.ok:
            return CloneRepoResult(
                repo_url=repo_url,
                workspace_root=str(workspace.root),
                project_dir=str(workspace.project_dir),
                ok=False,
                error=result.stderr or result.stdout or "git clone failed",
            )
        return CloneRepoResult(
            repo_url=repo_url,
            workspace_root=str(workspace.root),
            project_dir=str(Path(workspace.project_dir).resolve()),
            ok=True,
        )
