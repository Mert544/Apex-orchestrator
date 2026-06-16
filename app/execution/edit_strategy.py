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


# Patch-plan flags that map directly to a refactoring strategy. Ordered: the
# first truthy flag wins, matching the original sequential if-chain.
_PLAN_FLAG_RULES: tuple[tuple[str, str, float, str], ...] = (
    ("rename", "rename_variable", 0.9, "Patch plan explicitly requests a rename."),
    ("extract", "extract_method", 0.8, "Patch plan explicitly requests method extraction."),
    ("inline", "inline_variable", 0.8, "Patch plan explicitly requests variable inlining."),
    ("move", "move_class", 0.7, "Patch plan explicitly requests class move."),
    ("extract_class", "extract_class", 0.7, "Patch plan explicitly requests class extraction."),
)

# Keyword rules over the combined title+strategy text. Each entry lists the
# substrings that trigger it; the first matching rule wins. Ordered exactly as
# the original if-chain so precedence (e.g. eval before guard) is preserved.
_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str, float, str], ...] = (
    (("eval",), "fix_eval", 0.85, "Keywords suggest an eval() security fix."),
    (("os.system",), "fix_os_system", 0.85, "Keywords suggest an os.system() security fix."),
    (("bare except", "bareexcept"), "fix_bare_except", 0.9, "Keywords suggest a bare-except fix."),
    (
        ("base-exception", "baseexception"),
        "fix_base_exception",
        0.9,
        "Keywords suggest narrowing except BaseException.",
    ),
    (("pickle",), "fix_pickle", 0.8, "Keywords suggest flagging unsafe pickle.loads()."),
    (("sql", "injection"), "fix_sql", 0.8, "Keywords suggest flagging an SQL-injection risk."),
    (("yaml",), "fix_yaml", 0.85, "Keywords suggest a yaml.load() safety fix."),
    (
        ("tempfile", "mktemp"),
        "fix_tempfile",
        0.8,
        "Keywords suggest flagging an insecure tempfile.mktemp().",
    ),
    (
        ("weak-hash", "hashlib"),
        "fix_weak_hash",
        0.8,
        "Keywords suggest flagging a weak hashlib.md5()/sha1().",
    ),
    (
        ("mutable default", "mutable-default"),
        "fix_mutable_default",
        0.85,
        "Keywords suggest a mutable-default-argument fix.",
    ),
    (
        ("modernize", "none-comparison", "none comparison"),
        "modernize",
        0.85,
        "Keywords suggest behavior-preserving modernization.",
    ),
    (
        ("open-encoding", "encoding"),
        "fix_open_encoding",
        0.85,
        "Keywords suggest adding an explicit open() encoding.",
    ),
    (
        ("net-timeout", "timeout", "hang"),
        "fix_net_timeout",
        0.8,
        "Keywords suggest flagging a network call without a timeout.",
    ),
    (
        ("identity-literal", "identity comparison"),
        "fix_identity_literal",
        0.85,
        "Keywords suggest fixing an identity-vs-literal comparison.",
    ),
    (
        ("negated-comparison",),
        "fix_negated_comparison",
        0.85,
        "Keywords suggest fixing a negated membership/identity test.",
    ),
    (
        ("raise-from", "raise without from"),
        "fix_raise_from",
        0.85,
        "Keywords suggest chaining a re-raised exception to its cause.",
    ),
    (
        ("fstring-no-placeholder", "f-string without placeholder"),
        "fix_fstring",
        0.85,
        "Keywords suggest dropping a dead f-string prefix.",
    ),
    (
        ("collection-literal",),
        "fix_collection_literal",
        0.85,
        "Keywords suggest replacing an empty constructor with a literal.",
    ),
    (
        ("import", "unused", "cleanup"),
        "organize_imports",
        0.7,
        "Keywords suggest import cleanup.",
    ),
    (("docstring", "document"), "add_docstring", 0.85, "Keywords suggest documentation."),
    (
        ("type", "typing", "annotation"),
        "add_type_annotations",
        0.8,
        "Keywords suggest type annotation work.",
    ),
    (
        ("guard", "validate", "input", "security"),
        "add_guard_clause",
        0.85,
        "Keywords suggest input validation.",
    ),
)


class EditStrategy:
    """Choose a conservative semantic edit strategy from task + patch signals."""

    def choose(
        self,
        title: str,
        patch_plan: dict[str, Any],
        related_tests: list[str] | None = None,
        repair_context: dict[str, Any] | None = None,
    ) -> EditStrategyResult:
        related_tests = related_tests or []
        repair_context = repair_context or {}
        combined = self._combined_text(title, patch_plan)

        for resolve in (
            self._from_repair_context,
            self._from_plan_flags,
            self._from_keywords,
        ):
            result = resolve(combined, patch_plan, repair_context)
            if result is not None:
                return result

        return self._default(combined, related_tests)

    @staticmethod
    def _combined_text(title: str, patch_plan: dict[str, Any]) -> str:
        title_lower = (title or "").lower()
        strategy_text = " ".join(patch_plan.get("change_strategy", [])).lower()
        return f"{title_lower} {strategy_text}"

    @staticmethod
    def _from_repair_context(
        combined: str,
        patch_plan: dict[str, Any],
        repair_context: dict[str, Any],
    ) -> EditStrategyResult | None:
        failure_type = str(repair_context.get("failure_type", ""))
        if failure_type == "test_failure":
            return EditStrategyResult(
                strategy="repair_test_assertion",
                confidence=0.8,
                reasons=["Repair context indicates a test failure."],
            )
        if failure_type == "patch_scope_failure":
            return EditStrategyResult(
                strategy="add_docstring",
                confidence=0.6,
                reasons=["Repair context indicates scope reduction is needed."],
            )
        return None

    @staticmethod
    def _from_plan_flags(
        combined: str,
        patch_plan: dict[str, Any],
        repair_context: dict[str, Any],
    ) -> EditStrategyResult | None:
        for flag, strategy, confidence, reason in _PLAN_FLAG_RULES:
            if patch_plan.get(flag):
                return EditStrategyResult(strategy=strategy, confidence=confidence, reasons=[reason])
        return None

    @staticmethod
    def _from_keywords(
        combined: str,
        patch_plan: dict[str, Any],
        repair_context: dict[str, Any],
    ) -> EditStrategyResult | None:
        # Concrete security fixes (AST-based) take priority over a generic
        # guard clause when the issue names a known dangerous pattern.
        for keywords, strategy, confidence, reason in _KEYWORD_RULES:
            if any(keyword in combined for keyword in keywords):
                return EditStrategyResult(strategy=strategy, confidence=confidence, reasons=[reason])
        return None

    @staticmethod
    def _default(combined: str, related_tests: list[str]) -> EditStrategyResult:
        if "test" in combined or "coverage" in combined or related_tests:
            return EditStrategyResult(
                strategy="add_docstring",
                confidence=0.6,
                reasons=["Context suggests test-related work."],
            )
        return EditStrategyResult(
            strategy="add_docstring",
            confidence=0.5,
            reasons=["No strong signal; defaulting to add_docstring."],
        )
