from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RepairSuggestion:
    repair_type: str
    suggested_actions: list[str] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    retry_recommended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RepairFailedTestSkill:
    def run(self, failure_analysis: dict[str, Any], patch_plan: dict[str, Any] | None = None) -> RepairSuggestion:
        failure_type = str(failure_analysis.get("primary_failure_type", "unknown"))
        patch_plan = patch_plan or {}
        target_files = list(patch_plan.get("target_files", []) or [])

        if failure_type == "patch_apply_failure":
            return RepairSuggestion(
                repair_type="patch_input_repair",
                suggested_actions=[
                    "Check patch input structure and required keys.",
                    "Verify file paths are inside project root.",
                    "Retry with explicit expected_old_content when patching existing files.",
                ],
                target_files=target_files,
                retry_recommended=True,
            )

        if failure_type == "test_failure":
            return RepairSuggestion(
                repair_type="test_failure_repair",
                suggested_actions=[
                    "Inspect failing test output and isolate the first failing command.",
                    "Generate the smallest patch that restores the intended behavior.",
                    "Add or refine a regression test if the behavior gap is not already covered.",
                ],
                target_files=target_files,
                retry_recommended=True,
            )

        if failure_type == "patch_scope_failure":
            return RepairSuggestion(
                repair_type="scope_reduction",
                suggested_actions=[
                    "Reduce the patch to fewer files.",
                    "Split the task into smaller edits and re-run verification.",
                ],
                target_files=target_files[:3],
                retry_recommended=True,
            )

        if failure_type == "sensitive_edit":
            return RepairSuggestion(
                repair_type="sensitive_review_required",
                suggested_actions=[
                    "Escalate for manual review before applying changes.",
                    "Prefer non-sensitive supporting files or tests in the first pass.",
                ],
                target_files=target_files,
                retry_recommended=False,
            )

        return RepairSuggestion(
            repair_type="no_repair_needed",
            suggested_actions=["No repair action required yet."],
            target_files=target_files,
            retry_recommended=False,
        )
