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
