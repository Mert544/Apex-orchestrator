from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PatchPlan:
    task_id: str
    title: str
    branch: str | None
    target_files: list[str] = field(default_factory=list)
    change_strategy: list[str] = field(default_factory=list)
    verification_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PatchPlanner:
    def plan(self, task: dict[str, Any]) -> PatchPlan:
        suggested_files = list(task.get("suggested_files", []) or [])
        title = str(task.get("title", "Unnamed task"))
        branch = task.get("branch")
        strategy = self._strategy_for_task(title)
        verification = self._verification_for_task(task)
        warnings = self._warnings_for_task(task)

        return PatchPlan(
            task_id=str(task.get("id", "task-0")),
            title=title,
            branch=branch,
            target_files=suggested_files,
            change_strategy=strategy,
            verification_steps=verification,
            warnings=warnings,
        )

    def _strategy_for_task(self, title: str) -> list[str]:
        lowered = title.lower()
        if "test gap" in lowered:
            return [
                "Inspect missing or weak tests around the target module.",
                "Add focused regression tests before broadening scope.",
                "Keep the production diff minimal and test-led.",
            ]
        if "security" in lowered or "sensitive" in lowered or "harden" in lowered:
            return [
                "Review sensitive paths first and avoid broad edits.",
                "Prefer small, auditable hardening changes.",
                "Run scope and sensitive edit checks before patch apply.",
            ]
        if "dependency hub" in lowered or "coupling" in lowered:
            return [
                "Identify the highest-pressure module and isolate one coupling improvement.",
                "Favor extraction or simplification over large refactors.",
                "Verify tests after each small architectural edit.",
            ]
        return [
            "Keep the patch minimal and focused on one task.",
            "Document touched files and intended behavior change.",
        ]

    def _verification_for_task(self, task: dict[str, Any]) -> list[str]:
        acceptance = list(task.get("acceptance_criteria", []) or [])
        verification = ["Run detected project tests."]
        for criterion in acceptance:
            if criterion not in verification:
                verification.append(criterion)
        return verification

    def _warnings_for_task(self, task: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for path in task.get("suggested_files", []) or []:
            lowered = str(path).lower()
            if any(hint in lowered for hint in ("auth", "payment", "secret", "token", ".github/workflows")):
                warnings.append(f"Sensitive file candidate detected: {path}")
        if not task.get("suggested_files"):
            warnings.append("No concrete target files inferred yet; manual file selection may be required.")
        return warnings
