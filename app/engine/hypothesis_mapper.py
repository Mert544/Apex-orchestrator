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
        snippets: list[str] = []
        hypothesis = ""

        # Pattern: missing input validation / no guard / lacks validation
        if any(k in text for k in ("input validation", "no guard", "lacks validation", "not validated")):
            hypothesis = f"{target} raises ValueError on invalid input"
            snippets.append(
                f"def test_{target}_rejects_invalid_input():\n"
                f"    with pytest.raises(ValueError):\n"
                f"        {target}(None)\n"
            )

        # Pattern: missing docstring
        if "docstring" in text or "documented" in text:
            hypothesis = f"{target} has a non-empty docstring"
            snippets.append(
                f"def test_{target}_has_docstring():\n"
                f"    assert {target}.__doc__ is not None\n"
                f"    assert len({target}.__doc__.strip()) > 0\n"
            )

        # Pattern: uses eval / exec / dangerous function
        if "eval" in text:
            hypothesis = f"{target} does not use eval() on untrusted data"
            snippets.append(
                f"def test_{target}_avoids_eval():\n"
                f"    import ast\n"
                f"    source = inspect.getsource({target})\n"
                f"    assert 'eval(' not in source\n"
            )

        # Pattern: missing type annotations
        if "type annotation" in text or "typing" in text or "not typed" in text:
            hypothesis = f"{target} has type annotations on all parameters"
            snippets.append(
                f"def test_{target}_has_type_annotations():\n"
                f"    import inspect\n"
                f"    sig = inspect.signature({target})\n"
                f"    for param in sig.parameters.values():\n"
                f"        assert param.annotation is not inspect.Parameter.empty\n"
            )

        # Pattern: zero division / missing guard
        if "zero" in text or "division" in text or "guard" in text:
            hypothesis = f"{target} handles edge case inputs gracefully"
            snippets.append(
                f"def test_{target}_handles_edge_cases():\n"
                f"    result = {target}(0)\n"
                f"    assert result is not None\n"
            )

        # Pattern: bare except
        if "bare except" in text or "except:" in text:
            hypothesis = f"{target} catches specific exceptions only"
            snippets.append(
                f"def test_{target}_catches_specific_exceptions():\n"
                f"    import inspect\n"
                f"    source = inspect.getsource({target})\n"
                f"    assert 'except:' not in source.replace(' ', '')\n"
            )

        # Fallback: if no specific pattern matched, generate a generic structural test
        if not snippets:
            hypothesis = f"{target} exists and is callable"
            snippets.append(
                f"def test_{target}_exists_and_callable():\n"
                f"    assert callable({target})\n"
            )

        return hypothesis, snippets

    @staticmethod
    def _infer_test_file(source_path: str) -> str:
        path = Path(source_path)
        name = path.stem
        return f"tests/test_{name}.py"
