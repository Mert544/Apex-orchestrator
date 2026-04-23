from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EditStrategyResult:
    strategy: str
    confidence: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EditStrategy:
    """Choose a conservative semantic edit strategy from task + patch signals."""

    def choose(
        self,
        title: str,
        patch_plan: dict[str, Any],
        related_tests: list[str] | None = None,
        repair_context: dict[str, Any] | None = None,
    ) -> EditStrategyResult:
        title_lower = (title or "").lower()
        strategy_text = " ".join(patch_plan.get("change_strategy", [])).lower()
        combined = f"{title_lower} {strategy_text}"
        related_tests = related_tests or []
        repair_context = repair_context or {}
        reasons: list[str] = []

        failure_type = str(repair_context.get("failure_type", ""))
        if failure_type == "test_failure":
            reasons.append("Repair context indicates a test failure.")
            return EditStrategyResult(strategy="repair_test_assertion", confidence=0.8, reasons=reasons)
        if failure_type == "patch_scope_failure":
            reasons.append("Repair context indicates scope reduction is needed.")
            return EditStrategyResult(strategy="add_docstring", confidence=0.6, reasons=reasons)

        if patch_plan.get("rename"):
            reasons.append("Patch plan explicitly requests a rename.")
            return EditStrategyResult(strategy="rename_variable", confidence=0.9, reasons=reasons)
        if patch_plan.get("extract"):
            reasons.append("Patch plan explicitly requests method extraction.")
            return EditStrategyResult(strategy="extract_method", confidence=0.8, reasons=reasons)
        if patch_plan.get("inline"):
            reasons.append("Patch plan explicitly requests variable inlining.")
            return EditStrategyResult(strategy="inline_variable", confidence=0.8, reasons=reasons)
        if patch_plan.get("move"):
            reasons.append("Patch plan explicitly requests class move.")
            return EditStrategyResult(strategy="move_class", confidence=0.7, reasons=reasons)
        if patch_plan.get("extract_class"):
            reasons.append("Patch plan explicitly requests class extraction.")
            return EditStrategyResult(strategy="extract_class", confidence=0.7, reasons=reasons)

        if "import" in combined or "unused" in combined or "cleanup" in combined:
            reasons.append("Keywords suggest import cleanup.")
            return EditStrategyResult(strategy="organize_imports", confidence=0.7, reasons=reasons)

        if "docstring" in combined or "document" in combined:
            reasons.append("Keywords suggest documentation.")
            return EditStrategyResult(strategy="add_docstring", confidence=0.85, reasons=reasons)

        if "type" in combined or "typing" in combined or "annotation" in combined:
            reasons.append("Keywords suggest type annotation work.")
            return EditStrategyResult(strategy="add_type_annotations", confidence=0.8, reasons=reasons)

        if "guard" in combined or "validate" in combined or "input" in combined or "security" in combined:
            reasons.append("Keywords suggest input validation.")
            return EditStrategyResult(strategy="add_guard_clause", confidence=0.85, reasons=reasons)

        if "test" in combined or "coverage" in combined or related_tests:
            reasons.append("Context suggests test-related work.")
            return EditStrategyResult(strategy="add_docstring", confidence=0.6, reasons=reasons)

        reasons.append("No strong signal; defaulting to add_docstring.")
        return EditStrategyResult(strategy="add_docstring", confidence=0.5, reasons=reasons)
