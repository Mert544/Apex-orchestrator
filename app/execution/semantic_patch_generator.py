from __future__ import annotations

from pathlib import Path
from typing import Any

from app.execution.context_extractor import ContextExtractor
from app.execution.edit_strategy import EditStrategy
from app.execution.target_selector import TargetSelector

from app.execution.semantic.result import SemanticPatchResult
from app.execution.semantic.generators.stub import try_create_stub
from app.execution.semantic.generators.draft import fallback_draft
from app.execution.semantic.transforms import docstring
from app.execution.semantic.transforms import type_annotations
from app.execution.semantic.transforms import guard_clause
from app.execution.semantic.transforms import repair_test
from app.execution.semantic.transforms import rename_variable
from app.execution.semantic.transforms import extract_method
from app.execution.semantic.transforms import inline_variable
from app.execution.semantic.transforms import organize_imports
from app.execution.semantic.transforms import move_class
from app.execution.semantic.transforms import extract_class
from app.execution.semantic.transforms import security as security_transforms


class SemanticPatchGenerator:
    """Generate real, small code changes using AST-based transforms.

    Design principles:
    - One transform per call, minimal surface area.
    - expected_old_content is always set for safety.
    - If file state changed since read, patch is skipped (ApplyPatchSkill handles this).
    - Falls back to draft mode only when no semantic transform applies.
    - Uses explicit target selection, context extraction, and edit-strategy choice.
    """

    def __init__(self) -> None:
        self.target_selector = TargetSelector()
        self.context_extractor = ContextExtractor()
        self.edit_strategy = EditStrategy()

    def generate(
        self,
        project_root: str | Path,
        patch_plan: dict[str, Any],
        task: dict[str, Any] | None = None,
        repair_context: dict[str, Any] | None = None,
        project_profile: dict[str, Any] | None = None,
    ) -> SemanticPatchResult:
        root = Path(project_root).resolve()
        task = task or {}
        repair = repair_context or {}
        title = str(patch_plan.get("title", task.get("title", "Unnamed task")))
        task_id = str(patch_plan.get("task_id", task.get("id", "task-0")))
        branch = patch_plan.get("branch") or task.get("branch") or "x.unknown"

        selection = self.target_selector.select(
            project_root=root,
            patch_plan=patch_plan,
            task=task,
            project_profile=project_profile,
        )
        target_files = [target.path for target in selection.targets]
        contexts = self.context_extractor.extract(root, target_files)
        related_tests: list[str] = []
        if contexts.contexts:
            related_tests = contexts.contexts[0].related_tests

        strategy = self.edit_strategy.choose(
            title=title,
            patch_plan=patch_plan,
            related_tests=related_tests,
            repair_context=repair,
        )

        if repair.get("failure_type") == "patch_scope_failure":
            target_files = target_files[:3]

        if not target_files:
            result = fallback_draft(root, task_id, title, branch, patch_plan, reason="No target files.")
            return self._attach_metadata(result, selection, contexts, strategy)

        for rel_path in target_files:
            target = (root / rel_path).resolve()
            if not str(target).startswith(str(root)):
                continue
            if not target.exists():
                stub = try_create_stub(root, rel_path, title, task_id)
                if stub:
                    return self._attach_metadata(self._estimate_and_return(stub), selection, contexts, strategy)
                continue

            if target.suffix.lower() != ".py":
                continue

            current = target.read_text(encoding="utf-8")
            transform = strategy.strategy
            result: SemanticPatchResult | None = None

            if transform == "add_docstring":
                result = docstring.apply(rel_path, current, title)
            elif transform == "add_type_annotations":
                result = type_annotations.apply(rel_path, current, title)
            elif transform == "add_guard_clause":
                result = guard_clause.apply(rel_path, current, title)
            elif transform == "repair_test_assertion":
                result = repair_test.apply(rel_path, current, repair)
            elif transform == "rename_variable":
                rename_cfg = patch_plan.get("rename", {})
                result = rename_variable.apply(
                    rel_path, current,
                    old_name=rename_cfg.get("old_name", ""),
                    new_name=rename_cfg.get("new_name", ""),
                    target_function=rename_cfg.get("target_function", ""),
                )
            elif transform == "extract_method":
                extract_cfg = patch_plan.get("extract", {})
                result = extract_method.apply(
                    rel_path, current,
                    start_line=extract_cfg.get("start_line", 0),
                    end_line=extract_cfg.get("end_line", 0),
                    new_function_name=extract_cfg.get("new_function_name", ""),
                    target_function=extract_cfg.get("target_function", ""),
                    parameters=extract_cfg.get("parameters", []),
                )
            elif transform == "inline_variable":
                inline_cfg = patch_plan.get("inline", {})
                result = inline_variable.apply(
                    rel_path, current,
                    var_name=inline_cfg.get("var_name", ""),
                    target_function=inline_cfg.get("target_function", ""),
                )
            elif transform == "organize_imports":
                result = organize_imports.apply(rel_path, current)
            elif transform == "move_class":
                move_cfg = patch_plan.get("move", {})
                result = move_class.apply(
                    rel_path, current,
                    class_name=move_cfg.get("class_name", ""),
                    new_module=move_cfg.get("new_module", ""),
                )
            elif transform == "extract_class":
                extract_cfg = patch_plan.get("extract_class", {})
                result = extract_class.apply(
                    rel_path, current,
                    methods=extract_cfg.get("methods", []),
                    new_class_name=extract_cfg.get("new_class_name", ""),
                    base_class=extract_cfg.get("base_class", None),
                )
            elif transform in ("fix_eval", "fix_os_system", "fix_bare_except"):
                result = security_transforms.apply(rel_path, current, title)

            if result:
                return self._attach_metadata(self._estimate_and_return(result), selection, contexts, strategy)

        result = fallback_draft(
            root, task_id, title, branch, patch_plan,
            reason="No safe semantic transform matched target files.",
        )
        return self._attach_metadata(result, selection, contexts, strategy)

    def _attach_metadata(
        self,
        result: SemanticPatchResult,
        selection: Any,
        contexts: Any,
        strategy: Any,
    ) -> SemanticPatchResult:
        result.selected_targets = selection.to_dict()["targets"]
        result.extracted_contexts = contexts.to_dict()["contexts"]
        result.chosen_strategy = strategy.to_dict()
        result.rationale = [
            *strategy.reasons,
            *result.rationale,
        ]
        return result

    def _estimate_and_return(self, result: SemanticPatchResult) -> SemanticPatchResult:
        total_chars = sum(len(pr["new_content"]) for pr in result.patch_requests)
        result.estimated_tokens = total_chars // 4
        return result
