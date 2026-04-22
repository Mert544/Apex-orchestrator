from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReflectionResult:
    is_valid: bool = False
    needs_more_evidence: bool = False
    reflection_depth: int = 0
    reflections: list[str] = field(default_factory=list)
    counter_examples: list[str] = field(default_factory=list)
    insight: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "needs_more_evidence": self.needs_more_evidence,
            "reflection_depth": self.reflection_depth,
            "reflections": self.reflections,
            "counter_examples": self.counter_examples,
            "insight": self.insight,
            "rationale": self.rationale,
        }


class RecursiveReflectionEngine:
    """Multi-layer reflection on a claim to validate its soundness.

    Reflection layers:
    1. Evidence sufficiency — are the provided pieces enough?
    2. Boundary check — when is this claim true vs false?
    3. Counter-example generation — what would falsify it?
    4. Meta-check — is the claim too broad, absolute, or vague?
    """

    def __init__(self, max_depth: int = 4) -> None:
        self.max_depth = max_depth

    def reflect(self, claim: dict[str, Any]) -> ReflectionResult:
        text = claim.get("text", "")
        evidence = claim.get("evidence", [])
        confidence = claim.get("confidence", 0.0)

        result = ReflectionResult()
        result.reflection_depth = self.max_depth

        # Layer 1: Evidence sufficiency
        ev_score = len(evidence)
        if ev_score >= 3 and confidence >= 0.7:
            result.reflections.append("Layer 1 — Evidence appears sufficient for the claim.")
        elif ev_score >= 1 and confidence >= 0.5:
            result.reflections.append("Layer 1 — Evidence is present but may be incomplete.")
            result.needs_more_evidence = True
        else:
            result.reflections.append("Layer 1 — Evidence is weak or missing. Claim is under-supported.")
            result.needs_more_evidence = True

        # Layer 2: Boundary check
        absolute_words = ["all", "every", "always", "never", "no ", "none"]
        has_absolute = any(aw in text.lower() for aw in absolute_words)
        if has_absolute:
            result.reflections.append(
                f"Layer 2 — Claim uses absolute language ('{text}'). "
                "Absolute claims are rarely true in software systems."
            )
        else:
            result.reflections.append("Layer 2 — Claim language is bounded. Good.")

        # Layer 3: Counter-example generation
        counter_examples = self._generate_counterexamples(text, evidence)
        result.counter_examples = counter_examples
        if counter_examples:
            result.reflections.append(
                f"Layer 3 — Generated {len(counter_examples)} counter-example scenario(s). "
                "Claim must survive these to be considered robust."
            )
        else:
            result.reflections.append("Layer 3 — Could not generate obvious counter-examples. This may mean the claim is too vague.")

        # Layer 4: Meta-check (vagueness, circularity)
        word_count = len(text.split())
        if word_count < 5:
            result.reflections.append("Layer 4 — Claim is very short. May be too vague to evaluate meaningfully.")
        elif word_count > 30:
            result.reflections.append("Layer 4 — Claim is very long. May contain multiple sub-claims that should be split.")
        else:
            result.reflections.append("Layer 4 — Claim length is appropriate for evaluation.")

        # Final verdict
        penalty = 0
        if result.needs_more_evidence:
            penalty += 0.3
        if has_absolute:
            penalty += 0.2
        if len(counter_examples) >= 3:
            penalty += 0.1
        if word_count < 5:
            penalty += 0.1

        adjusted_confidence = max(0.0, confidence - penalty)
        result.is_valid = adjusted_confidence >= 0.5

        if result.is_valid:
            result.rationale = f"Claim survived {self.max_depth} reflection layers with adjusted confidence {adjusted_confidence:.2f}."
            result.insight = self._generate_insight(text, evidence, "valid")
        else:
            result.rationale = f"Claim failed reflection scrutiny (adjusted confidence {adjusted_confidence:.2f}). Needs more evidence or narrower scope."
            result.insight = self._generate_insight(text, evidence, "invalid")

        return result

    @staticmethod
    def _generate_counterexamples(text: str, evidence: list[str]) -> list[str]:
        counters = []
        lower = text.lower()

        if "secure" in lower or "safe" in lower:
            counters.append("What if an attacker provides crafted input that bypasses the validation?")
        if "all" in lower or "every" in lower:
            counters.append("What if there is an edge case file or function not covered by the evidence?")
        if "test" in lower or "coverage" in lower:
            counters.append("What if the tests exist but do not actually assert meaningful behavior?")
        if "fast" in lower or "performance" in lower:
            counters.append("What if the performance is acceptable for small inputs but degrades at scale?")
        if "no " in lower or "never" in lower:
            counters.append("What if the issue exists in a dependency or transitive module not scanned?")
        if "thread" in lower or "concurrent" in lower:
            counters.append("What if a race condition occurs under high load that is not visible in static analysis?")
        if not counters:
            counters.append("What if the evidence is outdated and the code has changed since?")
            counters.append("What if the claim holds in the current context but fails in a different environment?")

        return counters[:3]

    @staticmethod
    def _generate_insight(text: str, evidence: list[str], verdict: str) -> str:
        if verdict == "valid":
            return f"The claim '{text[:40]}...' is well-supported. Consider documenting the boundary conditions explicitly."
        else:
            return f"The claim '{text[:40]}...' needs strengthening. Gather more direct evidence or narrow the scope."
