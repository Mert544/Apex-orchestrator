from __future__ import annotations

from pathlib import Path

from app.tools.repo_scanner import RepoEvidence, RepoScanner


class EvidenceMapper:
    def __init__(self, project_root: str | Path | None = None, repo_scanner: RepoScanner | None = None) -> None:
        root = Path(project_root) if project_root is not None else Path.cwd()
        self.repo_scanner = repo_scanner or RepoScanner(root=root)

    def map(self, claim: str) -> dict:
        supporting = self.repo_scanner.search(claim, top_k=3)
        opposing = self.repo_scanner.search(f"counter risk contradiction {claim}", top_k=2)

        return {
            "evidence_for": self._render_results(supporting),
            "evidence_against": self._render_results(opposing),
            "sources_for": supporting,
            "sources_against": opposing,
        }

    def _render_results(self, results: list[RepoEvidence]) -> list[str]:
        rendered: list[str] = []
        for item in results:
            rendered.append(f"{item.path} | score={item.score} | {item.snippet}")
        return rendered
