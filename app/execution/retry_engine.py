from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.execution.patch_planner import PatchPlanner
from app.execution.semantic_patch_generator import SemanticPatchGenerator
from app.execution.verifier import Verifier
from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch
from app.skills.repair.analyze_failure_log import AnalyzeFailureLogSkill
from app.skills.repair.repair_failed_test import RepairFailedTestSkill


@dataclass
class RetryEngineResult:
    status: str = ""  # success, exhausted, human_review_required, no_retry_needed
    attempts: int = 0
    max_retries: int = 1
    final_verification: dict[str, Any] = field(default_factory=dict)
    failure_analysis: dict[str, Any] = field(default_factory=dict)
    repair_suggestion: dict[str, Any] = field(default_factory=dict)
    patch_requests: list[dict[str, Any]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RetryEngine:
    """Controlled retry loop for verification failures.

    Flow:
      1. Classify failure via AnalyzeFailureLogSkill.
      2. Generate repair suggestion via RepairFailedTestSkill.
      3. If retry_recommended and budget allows:
         - Generate semantic repair patch.
         - Apply patch (with expected_old_content safety).
         - Re-verify.
         - Loop up to max_retries.
      4. Return final status with full audit trail.
    """

    def __init__(
        self,
        max_retries: int = 1,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        semantic_generator: SemanticPatchGenerator | None = None,
        verifier: Verifier | None = None,
        patch_applier: ApplyPatchSkill | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.semantic_generator = semantic_generator or SemanticPatchGenerator()
        self.verifier = verifier or Verifier()
        self.patch_applier = patch_applier or ApplyPatchSkill()
        self.failure_analyzer = AnalyzeFailureLogSkill()
        self.repair_planner = RepairFailedTestSkill()

    def run(
        self,
        project_root: str | Path,
        verification: dict[str, Any],
        patch_plan: dict[str, Any] | None = None,
        task: dict[str, Any] | None = None,
    ) -> RetryEngineResult:
        root = Path(project_root).resolve()
        patch_plan = patch_plan or {}
        task = task or {}
        result = RetryEngineResult(max_retries=self.max_retries)
        rationale: list[str] = []

        analysis = self.failure_analyzer.run(verification).to_dict()
        suggestion = self.repair_planner.run(analysis, patch_plan).to_dict()

        result.failure_analysis = analysis
        result.repair_suggestion = suggestion

        failure_type = analysis.get("primary_failure_type", "unknown")
        if failure_type == "no_failure_detected":
            result.status = "no_retry_needed"
            result.final_verification = verification
            rationale.append("No failure detected; retry not required.")
            result.rationale = rationale
            return result

        if failure_type == "sensitive_edit":
            result.status = "human_review_required"
            result.final_verification = verification
            rationale.append("Sensitive edit detected; automatic retry blocked by policy.")
            result.rationale = rationale
            return result

        retry_recommended = suggestion.get("retry_recommended", False)
        if not retry_recommended:
            result.status = "human_review_required"
            result.final_verification = verification
            rationale.append(f"Failure type '{failure_type}' does not recommend automatic retry.")
            result.rationale = rationale
            return result

        current_verification = verification
        current_patch_plan = dict(patch_plan)

        for attempt in range(1, self.max_retries + 1):
            result.attempts = attempt
            rationale.append(f"Attempt {attempt}/{self.max_retries}: generating repair patch for '{failure_type}'.")

            if attempt > 1:
                delay = min(self.base_delay * (2 ** (attempt - 2)), self.max_delay)
                jitter = delay * 0.1 * (random.random() * 2 - 1)
                time.sleep(max(0.0, delay + jitter))

            repair_context = {
                "failure_type": failure_type,
                "analysis_summary": analysis.get("summary", []),
                "suggested_actions": suggestion.get("suggested_actions", []),
            }

            # Scope reduction for retry
            if failure_type == "patch_scope_failure":
                current_patch_plan["target_files"] = current_patch_plan.get("target_files", [])[:3]
                rationale.append("Reduced target files to 3 for scope safety.")

            gen_result = self.semantic_generator.generate(
                project_root=root,
                patch_plan=current_patch_plan,
                task=task,
                repair_context=repair_context,
            )

            if not gen_result.patch_requests:
                rationale.append("No repair patch generated; stopping retry loop.")
                break

            result.patch_requests = list(gen_result.patch_requests)
            rationale.extend(gen_result.rationale)

            patches = [
                FilePatch(
                    path=item["path"],
                    new_content=item["new_content"],
                    expected_old_content=item.get("expected_old_content"),
                )
                for item in gen_result.patch_requests
            ]

            apply_result = self.patch_applier.run(root, patches)
            result.changed_files = list(apply_result.changed_files)

            if not apply_result.ok:
                rationale.append(f"Patch apply failed: {apply_result.error}")
                current_verification = {
                    **current_verification,
                    "patch_apply": {
                        "ok": False,
                        "error": apply_result.error,
                        "changed_files": apply_result.changed_files,
                        "skipped_files": apply_result.skipped_files,
                    },
                }
                # Re-analyze for next loop iteration if budget remains
                analysis = self.failure_analyzer.run(current_verification).to_dict()
                failure_type = analysis.get("primary_failure_type", "unknown")
                continue

            # Re-verify
            current_verification = self.verifier.verify(
                project_root=root, changed_files=apply_result.changed_files
            ).to_dict()
            current_verification["patch_apply"] = {
                "ok": True,
                "changed_files": apply_result.changed_files,
                "skipped_files": apply_result.skipped_files,
                "error": None,
            }

            if current_verification.get("ok", False):
                result.status = "success"
                result.final_verification = current_verification
                rationale.append(f"Verification passed after attempt {attempt}.")
                result.rationale = rationale
                return result

            # Failure persists; re-analyze for next attempt
            analysis = self.failure_analyzer.run(current_verification).to_dict()
            suggestion = self.repair_planner.run(analysis, current_patch_plan).to_dict()
            failure_type = analysis.get("primary_failure_type", "unknown")
            retry_recommended = suggestion.get("retry_recommended", False)
            if not retry_recommended:
                rationale.append(f"Retry no longer recommended after attempt {attempt}.")
                break

        result.status = "exhausted"
        result.final_verification = current_verification
        rationale.append(f"Retry budget exhausted after {result.attempts} attempt(s).")
        result.rationale = rationale
        return result
