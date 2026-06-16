"""Characterization tests proving the refactored TargetSelector.select is
byte-identical to the original HEAD implementation across many inputs.

The original implementation is reconstructed inline below so the comparison is
self-contained and does not depend on git state at test time.
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.execution.target_selector import TargetSelector


# --- Original implementation snapshot (from `git show HEAD`) -----------------
@dataclass
class _OrigRankedTarget:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class _OrigResult:
    targets: list[_OrigRankedTarget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"targets": [asdict(t) for t in self.targets]}


class _OrigSelector:
    def select(self, project_root, patch_plan, task=None, project_profile=None):
        root = Path(project_root).resolve()
        task = task or {}
        project_profile = project_profile or {}
        title = str(task.get("title") or patch_plan.get("title") or "").lower()
        suggested = list(dict.fromkeys(patch_plan.get("target_files", []) or task.get("suggested_files", []) or []))
        ranked: list[_OrigRankedTarget] = []

        for rel_path in suggested:
            target = (root / rel_path).resolve()
            score = 0.0
            reasons: list[str] = []

            if target.exists():
                reasons.append("File exists.")
                score += 1.0
            else:
                reasons.append("File does not exist yet.")

            if target.suffix.lower() == ".py":
                reasons.append("Python file.")
                score += 2.0
            elif target.suffix.lower() in {".md", ".txt", ".rst"}:
                reasons.append("Documentation file.")
                score += 0.5
            else:
                reasons.append("Non-Python file.")

            if "test" in rel_path.lower():
                if "test" in title or "coverage" in title:
                    reasons.append("Title suggests test work.")
                    score += 1.5
                else:
                    reasons.append("Test file but title does not mention tests.")
                    score += 0.5

            sensitive = project_profile.get("sensitive_paths") or []
            for pattern in sensitive:
                if pattern in rel_path:
                    reasons.append("Matches sensitive path pattern.")
                    score -= 3.0
                    break

            ranked.append(_OrigRankedTarget(path=rel_path, score=round(score, 2), reasons=reasons))

        ranked.sort(key=lambda t: t.score, reverse=True)
        return _OrigResult(targets=ranked)


# --- Input matrix covering every branch --------------------------------------
def _make_fs(tmp_path: Path) -> Path:
    (tmp_path / "exists.py").write_text("x = 1\n")
    (tmp_path / "doc.md").write_text("# doc\n")
    (tmp_path / "test_exists.py").write_text("def test(): pass\n")
    sub = tmp_path / "secret"
    sub.mkdir()
    (sub / "keys.py").write_text("KEY = 1\n")
    return tmp_path


_REL_PATHS = [
    "exists.py",            # exists + python
    "missing.py",           # missing + python
    "doc.md",               # exists + doc
    "notes.txt",            # missing + doc (txt)
    "readme.rst",           # missing + doc (rst)
    "data.json",            # missing + non-python
    "test_exists.py",       # exists + python + test
    "tests/test_missing.py",  # missing + python + test
    "test_doc.md",          # missing + doc + test
    "secret/keys.py",       # exists + python + sensitive
    "secret/other.py",      # missing + python + sensitive
    "duplicate.py",         # used to force dedup
]

_TITLES = [
    None,
    "Add tests for module",
    "Improve coverage of selector",
    "Refactor the engine",
    "",
]

_SENSITIVE = [
    None,
    [],
    ["secret"],
    ["secret", "keys"],
    ["nomatch"],
]


def _build_cases():
    cases = []
    # Single-path cases across all titles and sensitive configs.
    for rel in _REL_PATHS:
        for title in _TITLES:
            for sens in _SENSITIVE:
                cases.append(([rel], title, sens))
    # Multi-path + dedup cases.
    for combo in itertools.combinations(_REL_PATHS, 3):
        cases.append((list(combo), "Add tests", ["secret"]))
    # Explicit dedup ordering.
    cases.append((["duplicate.py", "exists.py", "duplicate.py"], None, None))
    # Empty suggestion list.
    cases.append(([], "tests", ["secret"]))
    return cases


@pytest.mark.parametrize("rel_paths,title,sensitive", _build_cases())
def test_byte_identical(tmp_path: Path, rel_paths, title, sensitive):
    root = _make_fs(tmp_path)
    patch_plan = {"target_files": rel_paths}
    task = {"title": title} if title is not None else {}
    profile = {"sensitive_paths": sensitive} if sensitive is not None else {}

    orig = _OrigSelector().select(root, patch_plan, task, profile).to_dict()
    new = TargetSelector().select(root, patch_plan, task, profile).to_dict()
    assert new == orig


def test_suggested_files_fallback(tmp_path: Path):
    root = _make_fs(tmp_path)
    # No target_files -> falls back to task suggested_files; title from patch_plan.
    patch_plan = {"title": "Coverage push"}
    task = {"suggested_files": ["test_exists.py", "missing.py"]}
    profile = {"sensitive_paths": ["keys"]}
    orig = _OrigSelector().select(root, patch_plan, task, profile).to_dict()
    new = TargetSelector().select(root, patch_plan, task, profile).to_dict()
    assert new == orig


def test_none_defaults(tmp_path: Path):
    root = _make_fs(tmp_path)
    patch_plan = {"target_files": ["exists.py", "test_missing.py"]}
    orig = _OrigSelector().select(root, patch_plan).to_dict()
    new = TargetSelector().select(root, patch_plan).to_dict()
    assert new == orig
