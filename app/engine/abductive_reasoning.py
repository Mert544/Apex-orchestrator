from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AbductionResult:
    root_causes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    observations: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_causes": self.root_causes,
            "confidence": self.confidence,
            "observations_count": len(self.observations),
            "rationale": self.rationale,
        }


class AbductiveReasoner:
    """Infer probable root causes from observed code patterns.

    Unlike deductive reasoning (general → specific), abduction goes from
    observations → best explanation. This helps the agent answer 'why?'.

    Example:
        Observation: function is 55 lines long
        → Best explanation: function has multiple responsibilities
        → Recommendation: extract method or split into smaller functions
    """

    # Observation type → possible root causes
    CAUSE_MAP: dict[str, list[str]] = {
        "long_function": [
            "Function has multiple responsibilities (SRP violation)",
            "Lack of helper function extraction",
            "Accumulated technical debt without refactoring",
        ],
        "many_arguments": [
            "Function depends on too many data sources",
            "Missing parameter object or data class",
            "Feature envy — function may belong to another module",
        ],
        "high_import_count": [
            "Module is a 'god module' with too many concerns",
            "Low cohesion — unrelated functionality grouped together",
            "Possible circular dependency risk",
        ],
        "bare_except": [
            "Developer was unsure which exceptions to catch",
            "Error handling was added as an afterthought",
            "Missing domain-specific exception hierarchy",
        ],
        "missing_docstring": [
            "Rapid prototyping without documentation discipline",
            "Developer assumed code was self-explanatory",
            "Missing code review process that checks documentation",
        ],
        "unused_import": [
            "Refactoring left dead imports behind",
            "Copy-paste coding from another module",
            "Lack of automated linting (e.g. flake8)",
        ],
        "deep_nesting": [
            "Complex conditional logic without early returns",
            "Missing guard clause pattern adoption",
            "State machine or strategy pattern could simplify",
        ],
        "mutable_default_arg": [
            "Python gotcha — mutable default arguments are dangerous",
            "Developer unfamiliar with Python's default argument behavior",
            "Missing static analysis tools that catch this",
        ],
        "eval_usage": [
            "Developer chose convenience over security",
            "Lack of secure parsing alternatives awareness",
            "Missing security review in development process",
        ],
    }

    def infer(self, observations: list[dict[str, Any]]) -> AbductionResult:
        root_causes: list[str] = []
        total_weight = 0.0
        matched = 0

        for obs in observations:
            obs_type = obs.get("type", "")
            causes = self.CAUSE_MAP.get(obs_type, [])
            if causes:
                # Pick the first cause as the primary explanation
                root_causes.append(causes[0])
                # Additional causes add supporting weight
                for c in causes[1:]:
                    root_causes.append(f"  (also possible) {c}")
                matched += 1
                total_weight += self._weight_for(obs)

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for rc in root_causes:
            key = rc.lower().strip()
            if key not in seen:
                seen.add(key)
                deduped.append(rc)

        confidence = min(1.0, (matched / max(len(observations), 1)) * 0.7 + min(total_weight * 0.1, 0.3))

        rationale = (
            f"From {len(observations)} observation(s), {matched} matched known anti-patterns. "
            f"Most probable root causes identified."
        )

        return AbductionResult(
            root_causes=deduped,
            confidence=round(confidence, 2),
            observations=observations,
            rationale=rationale,
        )

    @staticmethod
    def _weight_for(observation: dict[str, Any]) -> float:
        """Heuristic weight based on severity metrics in the observation."""
        weight = 1.0
        if "line_count" in observation:
            weight += observation["line_count"] / 50.0
        if "arg_count" in observation:
            weight += observation["arg_count"] / 5.0
        if "import_count" in observation:
            weight += observation["import_count"] / 10.0
        return min(weight, 3.0)


# Deterministic translation from a seeding signal label (a confluence family
# name or an idea ``fact_label``) to an abductive observation ``type`` in
# ``AbductiveReasoner.CAUSE_MAP``. Small, explicit, and obviously correct;
# any label not listed here is simply skipped (no observation, no cause).
# Several distinct labels legitimately map to the SAME observation type (a hub,
# a god-class and a symbol-rich module all read as "too many concerns" →
# ``high_import_count``); the reasoner counts each observation, so two such
# labels still yield two converging observations.
SIGNAL_OBSERVATION_MAP: dict[str, str] = {
    # convergence on a structural "god module" / too-many-concerns cause
    "hub": "high_import_count",
    "dependency-hub": "high_import_count",
    "symbol-hub": "high_import_count",
    "god-class": "high_import_count",
    # control-flow depth
    "deep-nesting": "deep_nesting",
    # broad exception handling
    "base-exception": "bare_except",
    "bare except": "bare_except",
    # dynamic-eval security risk
    "eval": "eval_usage",
    "security-eval": "eval_usage",
    # oversized / responsibility-heavy functions
    "complexity-hotspot": "long_function",
    "complex-function": "long_function",
    "hotspot-function": "long_function",
    # python mutable-default gotcha
    "mutable-default": "mutable_default_arg",
    # too many parameters / a dead knob every caller carries
    "dead-parameter": "many_arguments",
    # documentation gaps
    "doc-drift": "missing_docstring",
    "missing-docstring": "missing_docstring",
    # dead / leftover imports
    "unused-import": "unused_import",
    "modernization-imports": "unused_import",
}


def signals_to_observations(labels: Any) -> list[dict[str, Any]]:
    """Map converging signal labels to abductive observation dicts.

    Deterministic and order-preserving: each mappable label yields one
    ``{"type": <observation>}`` dict in the order it appears; unmapped labels
    are skipped. Returns ``[]`` for empty/None input.
    """
    return [
        {"type": SIGNAL_OBSERVATION_MAP[label]}
        for label in (labels or [])
        if label in SIGNAL_OBSERVATION_MAP
    ]


def explain_signals(labels: Any) -> AbductionResult | None:
    """Abductive root-cause explanation for converging signal labels, or None.

    Returns an ``AbductionResult`` only when the labels yield ``>= 2`` mappable
    observations (a genuine convergence worth explaining); otherwise ``None``,
    so callers leave the idea byte-identical. Deterministic (no time/random).
    """
    observations = signals_to_observations(labels)
    if len(observations) < 2:
        return None
    return AbductiveReasoner().infer(observations)


def explanation_clause(result: AbductionResult) -> str:
    """A one-line ``root cause: <X> (confidence <c>)`` clause for an idea.

    The primary (first) root cause grounds the headline; the confidence rides
    alongside it. Empty string when there is no root cause to name.
    """
    if not result.root_causes:
        return ""
    primary = result.root_causes[0]
    return f"root cause: {primary} (confidence {result.confidence})"
