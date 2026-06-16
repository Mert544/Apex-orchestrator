from __future__ import annotations

from pathlib import Path

from typing import Any

from app.execution._draft_document import build_draft_document

from ..result import SemanticPatchResult


def fallback_draft(
    root: Path, task_id: str, title: str, branch: str, patch_plan: dict[str, Any], reason: str
) -> SemanticPatchResult:
    fallback_path = root / ".apex" / "patch-drafts" / f"{task_id}.md"
    content = build_draft_document(task_id=task_id, title=title, branch=branch, patch_plan=patch_plan)
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
