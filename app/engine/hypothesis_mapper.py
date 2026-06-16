from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HypothesisTestMapping:
    claim_text: str
    hypothesis: str
    is_testable: bool
    test_snippets: list[str] = field(default_factory=list)
    test_file_path: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_text": self.claim_text,
            "hypothesis": self.hypothesis,
            "is_testable": self.is_testable,
            "test_snippets": self.test_snippets,
            "test_file_path": self.test_file_path,
            "rationale": self.rationale,
        }


class HypothesisMapper:
    """Convert structural claims into concrete, testable Python assertions.

    Example:
        Claim: "Function process lacks input validation"
        → Hypothesis: "process raises ValueError on invalid input"
        → Test: "def test_process_rejects_invalid_input(): pytest.raises(ValueError)"
    """

    def map_to_test(self, claim: dict[str, Any]) -> HypothesisTestMapping:
        text = claim.get("text", "").lower()
        target = claim.get("target_function", "")
        source = claim.get("source_file", "")

        if not target or len(text.split()) < 4:
            return HypothesisTestMapping(
                claim_text=text,
                hypothesis="",
                is_testable=False,
                rationale="Claim is too vague or lacks a target function.",
            )

        hypothesis, snippets = self._generate(text, target)
        test_file = self._infer_test_file(source)

        return HypothesisTestMapping(
            claim_text=text,
            hypothesis=hypothesis,
            is_testable=len(snippets) > 0,
            test_snippets=snippets,
            test_file_path=test_file,
            rationale=f"Mapped to {len(snippets)} test snippet(s).",
        )

    def _generate(self, text: str, target: str) -> tuple[str, list[str]]:
        hypothesis = ""
        snippets: list[str] = []

        for matches, make_hypothesis, make_snippet in self._PATTERNS:
            if matches(text):
                hypothesis = make_hypothesis(target)
                snippets.append(make_snippet(target))

        if not snippets:
            hypothesis = self._fallback_hypothesis(target)
            snippets.append(self._fallback_snippet(target))

        return hypothesis, snippets

    @staticmethod
    def _matches_validation(text: str) -> bool:
        keys = ("input validation", "no guard", "lacks validation", "not validated")
        return any(k in text for k in keys)

    @staticmethod
    def _snippet_validation(target: str) -> str:
        return (
            f"def test_{target}_rejects_invalid_input():\n"
            f"    with pytest.raises(ValueError):\n"
            f"        {target}(None)\n"
        )

    @staticmethod
    def _matches_docstring(text: str) -> bool:
        return "docstring" in text or "documented" in text

    @staticmethod
    def _snippet_docstring(target: str) -> str:
        return (
            f"def test_{target}_has_docstring():\n"
            f"    assert {target}.__doc__ is not None\n"
            f"    assert len({target}.__doc__.strip()) > 0\n"
        )

    @staticmethod
    def _matches_eval(text: str) -> bool:
        return "eval" in text

    @staticmethod
    def _snippet_eval(target: str) -> str:
        return (
            f"def test_{target}_avoids_eval():\n"
            f"    import ast\n"
            f"    source = inspect.getsource({target})\n"
            f"    assert 'eval(' not in source\n"
        )

    @staticmethod
    def _matches_typing(text: str) -> bool:
        return "type annotation" in text or "typing" in text or "not typed" in text

    @staticmethod
    def _snippet_typing(target: str) -> str:
        return (
            f"def test_{target}_has_type_annotations():\n"
            f"    import inspect\n"
            f"    sig = inspect.signature({target})\n"
            f"    for param in sig.parameters.values():\n"
            f"        assert param.annotation is not inspect.Parameter.empty\n"
        )

    @staticmethod
    def _matches_zero(text: str) -> bool:
        return "zero" in text or "division" in text or "guard" in text

    @staticmethod
    def _snippet_zero(target: str) -> str:
        return (
            f"def test_{target}_handles_edge_cases():\n"
            f"    result = {target}(0)\n"
            f"    assert result is not None\n"
        )

    @staticmethod
    def _matches_bare_except(text: str) -> bool:
        return "bare except" in text or "except:" in text

    @staticmethod
    def _snippet_bare_except(target: str) -> str:
        return (
            f"def test_{target}_catches_specific_exceptions():\n"
            f"    import inspect\n"
            f"    source = inspect.getsource({target})\n"
            f"    assert 'except:' not in source.replace(' ', '')\n"
        )

    @staticmethod
    def _fallback_hypothesis(target: str) -> str:
        return f"{target} exists and is callable"

    @staticmethod
    def _fallback_snippet(target: str) -> str:
        return (
            f"def test_{target}_exists_and_callable():\n"
            f"    assert callable({target})\n"
        )

    _PATTERNS = (
        (
            _matches_validation,
            lambda t: f"{t} raises ValueError on invalid input",
            _snippet_validation,
        ),
        (
            _matches_docstring,
            lambda t: f"{t} has a non-empty docstring",
            _snippet_docstring,
        ),
        (
            _matches_eval,
            lambda t: f"{t} does not use eval() on untrusted data",
            _snippet_eval,
        ),
        (
            _matches_typing,
            lambda t: f"{t} has type annotations on all parameters",
            _snippet_typing,
        ),
        (
            _matches_zero,
            lambda t: f"{t} handles edge case inputs gracefully",
            _snippet_zero,
        ),
        (
            _matches_bare_except,
            lambda t: f"{t} catches specific exceptions only",
            _snippet_bare_except,
        ),
    )

    @staticmethod
    def _infer_test_file(source_path: str) -> str:
        path = Path(source_path)
        name = path.stem
        return f"tests/test_{name}.py"
