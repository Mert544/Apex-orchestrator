from __future__ import annotations

from pathlib import Path

from typing import Any

from ..result import SemanticPatchResult


def fallback_draft(
    root: Path, task_id: str, title: str, branch: str, patch_plan: dict[str, Any], reason: str
) -> SemanticPatchResult:
    fallback_path = root / ".apex" / "patch-drafts" / f"{task_id}.md"
    lines = [
        "# Apex Orchestrator Patch Draft",
        "",
        f"- task_id: {task_id}",
        f"- title: {title}",
        f"- branch: {branch}",
        "",
        "## Change strategy",
    ]
    for item in patch_plan.get("change_strategy", []) or ["No explicit change strategy captured."]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Verification steps")
    for item in patch_plan.get("verification_steps", []) or ["Run detected project tests."]:
        lines.append(f"- {item}")
    content = "\n".join(lines) + "\n"
    return SemanticPatchResult(
        patch_requests=[{
            "path": str(fallback_path.relative_to(root)),
            "new_content": content,
            "expected_old_content": None,
        }],
        transform_type="draft_fallback",
        rationale=[reason, "Fell back to standalone draft document."],
        mode="draft",
    )
