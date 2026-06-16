from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RankedTarget:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class TargetSelectionResult:
    targets: list[RankedTarget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"targets": [asdict(target) for target in self.targets]}


def _score_existence(target: Path) -> tuple[float, str]:
    if target.exists():
        return 1.0, "File exists."
    return 0.0, "File does not exist yet."


def _score_suffix(target: Path) -> tuple[float, str]:
    suffix = target.suffix.lower()
    if suffix == ".py":
        return 2.0, "Python file."
    if suffix in {".md", ".txt", ".rst"}:
        return 0.5, "Documentation file."
    return 0.0, "Non-Python file."


def _score_test(rel_path: str, title: str) -> tuple[float, str] | None:
    if "test" not in rel_path.lower():
        return None
    if "test" in title or "coverage" in title:
        return 1.5, "Title suggests test work."
    return 0.5, "Test file but title does not mention tests."


def _score_sensitive(rel_path: str, sensitive: list[str]) -> tuple[float, str] | None:
    for pattern in sensitive:
        if pattern in rel_path:
            return -3.0, "Matches sensitive path pattern."
    return None


def _resolve_suggested(patch_plan: dict[str, Any], task: dict[str, Any]) -> list[str]:
    candidates = patch_plan.get("target_files", []) or task.get("suggested_files", []) or []
    return list(dict.fromkeys(candidates))


def _rank_target(
    root: Path,
    rel_path: str,
    title: str,
    sensitive: list[str],
) -> RankedTarget:
    target = (root / rel_path).resolve()
    score = 0.0
    reasons: list[str] = []

    for component in (
        _score_existence(target),
        _score_suffix(target),
        _score_test(rel_path, title),
        _score_sensitive(rel_path, sensitive),
    ):
        if component is None:
            continue
        delta, reason = component
        score += delta
        reasons.append(reason)

    return RankedTarget(path=rel_path, score=round(score, 2), reasons=reasons)


class TargetSelector:
    """Choose the safest high-value file targets for semantic patching."""

    def select(
        self,
        project_root: str | Path,
        patch_plan: dict[str, Any],
        task: dict[str, Any] | None = None,
        project_profile: dict[str, Any] | None = None,
    ) -> TargetSelectionResult:
        root = Path(project_root).resolve()
        task = task or {}
        project_profile = project_profile or {}
        title = str(task.get("title") or patch_plan.get("title") or "").lower()
        suggested = _resolve_suggested(patch_plan, task)
        sensitive = project_profile.get("sensitive_paths") or []

        ranked = [_rank_target(root, rel_path, title, sensitive) for rel_path in suggested]
        ranked.sort(key=lambda t: t.score, reverse=True)
        return TargetSelectionResult(targets=ranked)
