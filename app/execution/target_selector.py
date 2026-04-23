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
        suggested = list(dict.fromkeys(patch_plan.get("target_files", []) or task.get("suggested_files", []) or []))
        ranked: list[RankedTarget] = []

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

            ranked.append(RankedTarget(path=rel_path, score=round(score, 2), reasons=reasons))

        ranked.sort(key=lambda t: t.score, reverse=True)
        return TargetSelectionResult(targets=ranked)
