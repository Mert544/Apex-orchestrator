from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FileFingerprint:
    path: str
    mtime: float
    size: int
    content_hash: str


@dataclass
class IncrementalAnalysisResult:
    changed_files: list[str] = field(default_factory=list)
    unchanged_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)


class IncrementalAnalyzer:
    """Track file changes across runs to avoid re-analyzing unchanged files.

    Stores fingerprints in .apex/fingerprints.json and compares on next run.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self._state_path = self.root / ".apex" / "fingerprints.json"
        self._previous: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        if self._state_path.exists():
            try:
                with open(self._state_path, encoding="utf-8") as f:
                    self._previous = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._previous = {}

    def _save_state(self, current: dict[str, dict[str, Any]]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)

    def _fingerprint(self, path: Path) -> FileFingerprint | None:
        try:
            stat = path.stat()
            content = path.read_bytes()
            return FileFingerprint(
                path=str(path.relative_to(self.root).as_posix()),
                mtime=stat.st_mtime,
                size=stat.st_size,
                content_hash=hashlib.sha256(content).hexdigest()[:16],
            )
        except (OSError, ValueError):
            return None

    def analyze(self, files: list[str] | None = None) -> IncrementalAnalysisResult:
        self._load_state()
        result = IncrementalAnalysisResult()
        current: dict[str, dict[str, Any]] = {}

        if files is None:
            files = [
                str(p.relative_to(self.root).as_posix())
                for p in self.root.rglob("*.py")
                if ".apex" not in p.parts and "__pycache__" not in p.parts
            ]

        previous_paths = set(self._previous.keys())
        current_paths: set[str] = set()

        for rel_path in files:
            full = self.root / rel_path
            fp = self._fingerprint(full)
            if fp is None:
                continue
            current_paths.add(rel_path)
            current[rel_path] = {
                "path": fp.path,
                "mtime": fp.mtime,
                "size": fp.size,
                "content_hash": fp.content_hash,
            }

            prev = self._previous.get(rel_path)
            if prev is None:
                result.new_files.append(rel_path)
            elif prev.get("content_hash") != fp.content_hash:
                result.changed_files.append(rel_path)
            else:
                result.unchanged_files.append(rel_path)

        for prev_path in previous_paths - current_paths:
            result.deleted_files.append(prev_path)

        self._save_state(current)

        return result
