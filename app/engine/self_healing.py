from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.semantic_patch_generator import SemanticPatchGenerator
from app.execution.semantic.result import SemanticPatchResult


@dataclass
class SelfHealingResult:
    original_failures: list[str] = field(default_factory=list)
    fixed_failures: list[str] = field(default_factory=list)
    remaining_failures: list[str] = field(default_factory=list)
    patches_applied: list[SemanticPatchResult] = field(default_factory=list)
    iterations: int = 0


class SelfHealingTestEngine:
    """Automatically repair failing tests via semantic patches.

    1. Run tests, capture failures
    2. Generate repair patches for failed test files
    3. Apply patches
    4. Re-run tests
    5. Repeat up to max_iterations
    """

    def __init__(
        self,
        project_root: str | Path,
        max_iterations: int = 3,
        test_command: str | None = None,
    ) -> None:
        self.root = Path(project_root).resolve()
        self.max_iterations = max_iterations
        self.test_command = test_command or "pytest"
        self._generator = SemanticPatchGenerator()

    def _run_tests(self) -> tuple[list[str], str]:
        proc = subprocess.run(
            self.test_command.split(),
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        failures: list[str] = []
        for line in proc.stdout.splitlines():
            if "FAILED" in line and ".py::" in line:
                parts = line.split()
                for part in parts:
                    if ".py::" in part:
                        failures.append(part.split("::")[0])
        return list(dict.fromkeys(failures)), proc.stdout + proc.stderr

    def heal(self) -> SelfHealingResult:
        result = SelfHealingResult()

        for iteration in range(self.max_iterations):
            result.iterations = iteration + 1
            failures, _ = self._run_tests()

            if iteration == 0:
                result.original_failures = failures[:]

            if not failures:
                result.fixed_failures = result.original_failures[:]
                break

            fixed_this_round: list[str] = []
            for test_file in failures:
                patch_result = self._generator.generate(
                    project_root=self.root,
                    patch_plan={
                        "task_id": f"heal-{iteration}",
                        "title": f"Repair failing test {test_file}",
                        "target_files": [test_file],
                        "change_strategy": ["Repair test assertion."],
                    },
                    repair_context={"failure_type": "test_failure"},
                )
                if patch_result.patch_requests:
                    result.patches_applied.append(patch_result)
                    fixed_this_round.append(test_file)

            if not fixed_this_round:
                result.remaining_failures = failures
                break

        final_failures, _ = self._run_tests()
        result.remaining_failures = final_failures
        result.fixed_failures = [
            f for f in result.original_failures
            if f not in final_failures
        ]

        return result
