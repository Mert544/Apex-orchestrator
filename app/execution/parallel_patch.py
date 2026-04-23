from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.semantic_patch_generator import SemanticPatchGenerator
from app.execution.semantic.result import SemanticPatchResult


@dataclass
class ParallelPatchResult:
    results: list[SemanticPatchResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completed: int = 0
    failed: int = 0


class ParallelSemanticPatcher:
    """Apply semantic patches to multiple files in parallel.

    Each file gets its own SemanticPatchGenerator call, running in a
    ThreadPoolExecutor for I/O-bound work (file reads/writes).
    """

    def __init__(self, max_workers: int = 4) -> None:
        self.max_workers = max_workers
        self._generator = SemanticPatchGenerator()

    def apply_batch(
        self,
        project_root: str | Path,
        patch_plans: list[dict[str, Any]],
        task: dict[str, Any] | None = None,
        project_profile: dict[str, Any] | None = None,
    ) -> ParallelPatchResult:
        root = Path(project_root).resolve()
        task = task or {}
        result = ParallelPatchResult()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._generator.generate,
                    root,
                    plan,
                    task,
                    None,
                    project_profile,
                ): plan
                for plan in patch_plans
            }

            for future in concurrent.futures.as_completed(futures):
                plan = futures[future]
                try:
                    patch_result = future.result(timeout=30)
                    result.results.append(patch_result)
                    result.completed += 1
                except Exception as exc:
                    result.errors.append(f"Plan {plan.get('task_id', '?')}: {exc}")
                    result.failed += 1

        return result
