from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass
class _LoopState:
    """Mutable state threaded through the retry loop between attempts."""

    verification: dict[str, Any]
    patch_plan: dict[str, Any]
    analysis: dict[str, Any]
    suggestion: dict[str, Any]
    failure_type: str


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

    @staticmethod
    def _short_circuit(failure_type: str, retry_recommended: bool) -> tuple[str, str] | None:
        """Return (status, rationale) for a pre-loop exit, or None to proceed."""
        if failure_type == "no_failure_detected":
            return "no_retry_needed", "No failure detected; retry not required."
        if failure_type == "sensitive_edit":
            return (
                "human_review_required",
                "Sensitive edit detected; automatic retry blocked by policy.",
            )
        if not retry_recommended:
            return (
                "human_review_required",
                f"Failure type '{failure_type}' does not recommend automatic retry.",
            )
        return None

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with bounded +/-10% jitter for attempts after the first."""
        delay = min(self.base_delay * (2 ** (attempt - 2)), self.max_delay)
        jitter = delay * 0.1 * (random.random() * 2 - 1)
        return max(0.0, delay + jitter)

    @staticmethod
    def _build_patches(patch_requests: list[dict[str, Any]]) -> list[FilePatch]:
        return [
            FilePatch(
                path=item["path"],
                new_content=item["new_content"],
                expected_old_content=item.get("expected_old_content"),
            )
            for item in patch_requests
        ]

    @staticmethod
    def _repair_context(
        failure_type: str,
        analysis: dict[str, Any],
        suggestion: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "failure_type": failure_type,
            "analysis_summary": analysis.get("summary", []),
            "suggested_actions": suggestion.get("suggested_actions", []),
        }

    @staticmethod
    def _verification_after_apply_failure(
        current_verification: dict[str, Any], apply_result: Any
    ) -> dict[str, Any]:
        return {
            **current_verification,
            "patch_apply": {
                "ok": False,
                "error": apply_result.error,
                "changed_files": apply_result.changed_files,
                "skipped_files": apply_result.skipped_files,
            },
        }

    def _generate_patches(
        self,
        root: Path,
        current_patch_plan: dict[str, Any],
        task: dict[str, Any],
        repair_context: dict[str, Any],
        result: RetryEngineResult,
        rationale: list[str],
    ) -> list[FilePatch] | None:
        """Generate repair patches; record audit trail. None means stop the loop."""
        gen_result = self.semantic_generator.generate(
            project_root=root,
            patch_plan=current_patch_plan,
            task=task,
            repair_context=repair_context,
        )
        if not gen_result.patch_requests:
            rationale.append("No repair patch generated; stopping retry loop.")
            return None
        result.patch_requests = list(gen_result.patch_requests)
        rationale.extend(gen_result.rationale)
        return self._build_patches(gen_result.patch_requests)

    def _verify_applied(self, root: Path, apply_result: Any) -> dict[str, Any]:
        """Re-verify after a successful apply and stamp the patch_apply record."""
        current_verification = self.verifier.verify(
            project_root=root, changed_files=apply_result.changed_files
        ).to_dict()
        current_verification["patch_apply"] = {
            "ok": True,
            "changed_files": apply_result.changed_files,
            "skipped_files": apply_result.skipped_files,
            "error": None,
        }
        return current_verification

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
        retry_recommended = suggestion.get("retry_recommended", False)
        exit_state = self._short_circuit(failure_type, retry_recommended)
        if exit_state is not None:
            result.status, message = exit_state
            result.final_verification = verification
            rationale.append(message)
            result.rationale = rationale
            return result

        state = _LoopState(
            verification=verification,
            patch_plan=dict(patch_plan),
            analysis=analysis,
            suggestion=suggestion,
            failure_type=failure_type,
        )

        for attempt in range(1, self.max_retries + 1):
            result.attempts = attempt
            signal = self._attempt(attempt, root, task, state, result, rationale)
            if result.status == "success":
                return result
            if signal == "stop":
                break

        result.status = "exhausted"
        result.final_verification = state.verification
        rationale.append(f"Retry budget exhausted after {result.attempts} attempt(s).")
        result.rationale = rationale
        return result

    def _attempt(
        self,
        attempt: int,
        root: Path,
        task: dict[str, Any],
        state: _LoopState,
        result: RetryEngineResult,
        rationale: list[str],
    ) -> str:
        """Run one retry attempt. Returns "stop" to end the loop or "continue" otherwise.

        On verification success, sets result.status = "success" and finalizes result.
        Mutates ``state`` to carry analysis context into the next attempt.
        """
        rationale.append(f"Attempt {attempt}/{self.max_retries}: generating repair patch for '{state.failure_type}'.")

        if attempt > 1:
            time.sleep(self._backoff_delay(attempt))

        repair_context = self._repair_context(state.failure_type, state.analysis, state.suggestion)

        # Scope reduction for retry
        if state.failure_type == "patch_scope_failure":
            state.patch_plan["target_files"] = state.patch_plan.get("target_files", [])[:3]
            rationale.append("Reduced target files to 3 for scope safety.")

        patches = self._generate_patches(
            root, state.patch_plan, task, repair_context, result, rationale
        )
        if patches is None:
            return "stop"

        apply_result = self.patch_applier.run(root, patches)
        result.changed_files = list(apply_result.changed_files)

        if not apply_result.ok:
            rationale.append(f"Patch apply failed: {apply_result.error}")
            state.verification = self._verification_after_apply_failure(
                state.verification, apply_result
            )
            # Re-analyze for next loop iteration if budget remains
            state.analysis = self.failure_analyzer.run(state.verification).to_dict()
            state.failure_type = state.analysis.get("primary_failure_type", "unknown")
            return "continue"

        # Re-verify
        state.verification = self._verify_applied(root, apply_result)

        if state.verification.get("ok", False):
            result.status = "success"
            result.final_verification = state.verification
            rationale.append(f"Verification passed after attempt {attempt}.")
            result.rationale = rationale
            return "stop"

        # Failure persists; re-analyze for next attempt
        state.analysis = self.failure_analyzer.run(state.verification).to_dict()
        state.suggestion = self.repair_planner.run(state.analysis, state.patch_plan).to_dict()
        state.failure_type = state.analysis.get("primary_failure_type", "unknown")
        if not state.suggestion.get("retry_recommended", False):
            rationale.append(f"Retry no longer recommended after attempt {attempt}.")
            return "stop"
        return "continue"
