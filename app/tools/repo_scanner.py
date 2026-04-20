from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".scss",
    ".sql",
}


@dataclass
class RepoEvidence:
    path: str
    snippet: str
    score: int


class RepoScanner:
    def __init__(self, root: str | Path, max_file_size: int = 200_000) -> None:
        self.root = Path(root)
        self.max_file_size = max_file_size

    def search(self, query: str, top_k: int = 3) -> list[RepoEvidence]:
        keywords = self._keywords(query)
        if not keywords or not self.root.exists():
            return []

        matches: list[RepoEvidence] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > self.max_file_size:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            lowered_content = content.lower()
            lowered_path = str(path.relative_to(self.root)).lower()
            score = sum(lowered_content.count(k) for k in keywords)
            score += sum(2 for k in keywords if k in lowered_path)
            if score <= 0:
                continue

            snippet = self._make_snippet(content, keywords)
            matches.append(
                RepoEvidence(
                    path=str(path.relative_to(self.root)),
                    snippet=snippet,
                    score=score,
                )
            )

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:top_k]

    def _keywords(self, query: str) -> list[str]:
        words = []
        for raw in query.lower().replace(":", " ").replace("?", " ").split():
            token = raw.strip(".,()[]{}\"'`-_")
            if len(token) >= 4 and token not in {"what", "which", "this", "that", "claim", "evidence", "against"}:
                words.append(token)
        return list(dict.fromkeys(words))[:8]

    def _make_snippet(self, content: str, keywords: list[str], window: int = 220) -> str:
        lowered = content.lower()
        first_index = min((lowered.find(k) for k in keywords if lowered.find(k) >= 0), default=-1)
        if first_index < 0:
            return content[:window].replace("\n", " ").strip()
        start = max(0, first_index - 80)
        end = min(len(content), first_index + window)
        return content[start:end].replace("\n", " ").strip()
