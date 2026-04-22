from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PatchRequestGeneratorResult:
    patch_requests: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "draft"
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PatchRequestGenerator:
    def generate(self, project_root: str | Path, patch_plan: dict[str, Any], task: dict[str, Any] | None = None) -> PatchRequestGeneratorResult:
        root = Path(project_root).resolve()
        task = task or {}
        target_files = list(patch_plan.get("target_files", []) or [])
        title = str(patch_plan.get("title", task.get("title", "Unnamed task")))
        task_id = str(patch_plan.get("task_id", task.get("id", "task-0")))
        branch = patch_plan.get("branch") or task.get("branch") or "x.unknown"

        patch_requests: list[dict[str, Any]] = []
        rationale: list[str] = []

        for rel_path in target_files[:1]:
            target = (root / rel_path).resolve()
            if not str(target).startswith(str(root)):
                continue
            if target.exists() and target.suffix.lower() in {".md", ".txt"}:
                current = target.read_text(encoding="utf-8")
                addition = self._draft_note(task_id=task_id, title=title, branch=branch)
                if addition.strip() in current:
                    rationale.append(f"Draft note already present in {rel_path}.")
                    continue
                patch_requests.append(
                    {
                        "path": rel_path,
                        "new_content": current.rstrip() + "\n\n" + addition + "\n",
                        "expected_old_content": current,
                    }
                )
                rationale.append(f"Prepared markdown/text draft patch for {rel_path}.")
                return PatchRequestGeneratorResult(patch_requests=patch_requests, rationale=rationale)

            if target.exists() and target.suffix.lower() == ".py":
                current = target.read_text(encoding="utf-8")
                marker = self._python_marker(task_id=task_id, title=title, branch=branch)
                if marker in current:
                    rationale.append(f"Draft marker already present in {rel_path}.")
                    continue
                patch_requests.append(
                    {
                        "path": rel_path,
                        "new_content": current.rstrip() + "\n\n" + marker + "\n",
                        "expected_old_content": current,
                    }
                )
                rationale.append(f"Prepared python draft marker patch for {rel_path}.")
                return PatchRequestGeneratorResult(patch_requests=patch_requests, rationale=rationale)

        fallback_path = root / ".apex" / "patch-drafts" / f"{task_id}.md"
        fallback_content = self._draft_document(task_id=task_id, title=title, branch=branch, patch_plan=patch_plan)
        patch_requests.append(
            {
                "path": str(fallback_path.relative_to(root)),
                "new_content": fallback_content,
                "expected_old_content": None,
            }
        )
        rationale.append("No safe inline target found; generated standalone draft note under .apex/patch-drafts/.")
        return PatchRequestGeneratorResult(patch_requests=patch_requests, rationale=rationale)

    def _draft_note(self, task_id: str, title: str, branch: str) -> str:
        return "\n".join(
            [
                "<!-- apex-orchestrator:draft -->",
                f"- task: {task_id}",
                f"- title: {title}",
                f"- branch: {branch}",
                "- note: supervised patch draft generated for review before broader code edits.",
            ]
        )

    def _python_marker(self, task_id: str, title: str, branch: str) -> str:
        safe_title = title.replace("\n", " ").strip()
        return f"# apex-orchestrator draft: {task_id} | {branch} | {safe_title}"

    def _draft_document(self, task_id: str, title: str, branch: str, patch_plan: dict[str, Any]) -> str:
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
