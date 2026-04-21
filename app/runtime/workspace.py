from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceInfo:
    root: Path
    project_dir: Path
    repo_name: str | None = None


class WorkspaceManager:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else None

    def create(self, repo_name: str | None = None, prefix: str = "epistemic-") -> WorkspaceInfo:
        root = Path(tempfile.mkdtemp(prefix=prefix, dir=str(self.base_dir) if self.base_dir else None)).resolve()
        project_dir = root / (repo_name or "project")
        return WorkspaceInfo(root=root, project_dir=project_dir, repo_name=repo_name)

    def cleanup(self, workspace: WorkspaceInfo | Path) -> None:
        target = workspace.root if isinstance(workspace, WorkspaceInfo) else Path(workspace)
        if target.exists():
            shutil.rmtree(target)

    def ensure_project_root(self, project_root: str | Path) -> Path:
        path = Path(project_root).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def infer_repo_name(self, repo_url: str) -> str:
        tail = repo_url.rstrip("/").split("/")[-1]
        if tail.endswith(".git"):
            tail = tail[:-4]
        return tail or "project"
