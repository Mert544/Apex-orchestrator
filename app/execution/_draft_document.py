"""Shared builder for the standalone patch-draft document.

When no safe inline edit target exists, both the supervised patch-request
generator and the semantic draft-fallback emit the same standalone markdown
draft under ``.apex/patch-drafts/``. The document body — a fixed header plus the
plan's change-strategy and verification-step bullets — was duplicated verbatim in
both. Hoisting it here keeps one source of truth; the produced string is
byte-for-byte identical to the originals. Deterministic, stdlib-only.
"""

from __future__ import annotations

from typing import Any


def build_draft_document(
    task_id: str, title: str, branch: str, patch_plan: dict[str, Any]
) -> str:
    """The standalone patch-draft markdown content for a task and its plan."""
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
    return "\n".join(lines) + "\n"
