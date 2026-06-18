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


# --- Testable-hypothesis enrichment over converging signal labels -----------
#
# A reasoning enricher (same contract as ``app.engine.idea_reasoning``): a pure
# function over a confluence idea's converging signal labels that reframes the
# convergence as a FALSIFIABLE hypothesis plus a concrete way to test it. Each
# mappable label contributes one "probe" — a (risk phrase, test method,
# falsification condition) triple — and the enricher fires only when >= 2 labels
# are mappable, so an un-reasoned idea stays byte-identical.
#
# Deterministic and order-preserving: no time, no randomness, small explicit
# basis. Several distinct labels legitimately share a probe (a hub, a symbol-hub
# and a god-class all read as "concentrates fan-in"); each still counts as one
# converging label, so two such labels still form a genuine confluence.

# label -> (risk_phrase, test_method, falsification_condition)
_HYPOTHESIS_PROBES: dict[str, tuple[str, str, str]] = {
    # missing / shallow coverage on risky code
    "untested": (
        "concentrates untested risk",
        "a characterization test around its hottest path will pin an untested edge case",
        "branch coverage is already complete",
    ),
    "critical-untested": (
        "concentrates untested risk",
        "a characterization test around its hottest path will pin an untested edge case",
        "branch coverage is already complete",
    ),
    "impure-untested": (
        "hides untested side effects",
        "a test that records its I/O will expose an unasserted side effect",
        "every effect is already asserted",
    ),
    "shallow-coverage": (
        "is only shallowly covered",
        "a branch-targeted test will hit a path the current suite skips",
        "every branch is already exercised",
    ),
    "hub-untested": (
        "is a widely-imported but untested chokepoint",
        "a regression test here will guard a path many importers depend on",
        "no importer relies on the untested path",
    ),
    # structural concentration of fan-in / responsibilities
    "hub": (
        "concentrates fan-in",
        "isolating one dependency in a seam test will reveal hidden coupling",
        "the dependency is already injectable",
    ),
    "dependency-hub": (
        "concentrates fan-in",
        "isolating one dependency in a seam test will reveal hidden coupling",
        "the dependency is already injectable",
    ),
    "symbol-hub": (
        "concentrates fan-in",
        "isolating one dependency in a seam test will reveal hidden coupling",
        "the dependency is already injectable",
    ),
    "god-class": (
        "bundles multiple responsibilities",
        "a test exercising one responsibility in isolation will need most of the class set up",
        "each responsibility is already independently constructible",
    ),
    # complexity / control-flow risk
    "complexity-hotspot": (
        "concentrates branching complexity",
        "a characterization test around its hottest function will reveal an untested edge case",
        "branch coverage is already complete",
    ),
    "complex-function": (
        "concentrates branching complexity",
        "a characterization test around its hottest function will reveal an untested edge case",
        "branch coverage is already complete",
    ),
    "hotspot-function": (
        "concentrates branching complexity",
        "a characterization test around its hottest function will reveal an untested edge case",
        "branch coverage is already complete",
    ),
    "deep-nesting": (
        "buries logic in deep nesting",
        "an input driving the innermost branch will need an improbably specific setup",
        "the innermost branch is reachable from a flat input",
    ),
    # change-coupling / churn risk
    "churn-hotspot": (
        "changes often",
        "a test pinning current behavior will start failing within a few edits",
        "behavior stays stable across edits",
    ),
    "cochange-testgap": (
        "co-changes with files it shares no tests with",
        "a cross-module test will catch a break the per-file suites miss",
        "the co-change partners never break together",
    ),
}


def _hypothesis_probes(labels: object) -> list[tuple[str, str, str]]:
    """Map converging signal labels to hypothesis probes, order-preserving.

    Each mappable label yields its ``(risk, method, falsifier)`` triple in the
    order it appears; unmapped labels are skipped. ``[]`` for empty/None input.
    """
    return [
        _HYPOTHESIS_PROBES[label]
        for label in (labels or [])
        if isinstance(label, str) and label in _HYPOTHESIS_PROBES
    ]


def hypothesis_enrichment(labels: object) -> tuple[str | None, list[str] | None]:
    """Reframe converging signals as a falsifiable hypothesis + how to test it.

    Returns ``(clause, [clause])`` when ``>= 2`` of the labels map to a probe (a
    genuine convergence worth testing), else ``(None, None)`` so the idea stays
    byte-identical. The clause already leads with ``hypothesis:`` (its own lens
    prefix), so the source_fact is the clause itself — no doubled prefix. The
    clause names the converging risk, the concrete test that would confirm it,
    and the condition that would FALSIFY it. Deterministic (no time/random).
    """
    probes = _hypothesis_probes(labels)
    if len(probes) < 2:
        return None, None

    risk = probes[0][0]
    method = probes[0][1]
    # The second converging probe supplies the falsifier, so the hypothesis is
    # grounded in the CONFLUENCE rather than a single signal.
    falsifier = probes[1][2]
    clause = (
        f"hypothesis: this code {risk} — {method}; "
        f"falsified if {falsifier}"
    )
    return clause, [clause]
