from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CounterfactualResult:
    scenarios: list[str] = field(default_factory=list)
    insight: str = ""
    claim_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios": self.scenarios,
            "insight": self.insight,
            "claim_text": self.claim_text,
        }


class CounterfactualGenerator:
    """Generate 'what if' scenarios to stress-test claims.

    For any given claim, the generator asks:
    - What if the opposite were true?
    - What edge cases could invalidate this?
    - What would happen in a different environment?

    This helps the agent think beyond the observed state.
    """

    def generate(self, claim: dict[str, Any]) -> CounterfactualResult:
        text = claim.get("text", "").lower()
        context = claim.get("context", "").lower()
        scenarios = []

        # Pattern: missing validation / no guard
        if any(k in text for k in ("validation", "guard", "check", "sanitize")):
            scenarios.append("What if an attacker provides None or malformed input?")
            scenarios.append("What if the input is at the maximum possible size?")
            scenarios.append("What if the input contains unicode null bytes or escape sequences?")

        # Pattern: eval / exec / dangerous function
        if "eval" in text or "exec" in text:
            scenarios.append("What if the expression string contains '__import__('os').system('rm -rf /')'?")
            scenarios.append("What if a trusted user accidentally passes user-controlled input?")

        # Pattern: missing docstring / documentation
        if "docstring" in text or "documented" in text:
            scenarios.append("What if a new developer joins and cannot understand the function's contract?")
            scenarios.append("What if the function behavior changes but the callers assume the old contract?")

        # Pattern: network / external call
        if "network" in text or "request" in text or "fetch" in text or "call" in text:
            scenarios.append("What if the remote server is down or responds with a 500 error?")
            scenarios.append("What if the connection hangs indefinitely (no timeout)?")
            scenarios.append("What if DNS resolution fails or the network is partitioned?")

        # Pattern: hardcoded values / secrets
        if "hardcoded" in text or "secret" in text or "password" in text:
            scenarios.append("What if the source code is leaked or committed to a public repository?")
            scenarios.append("What if the hardcoded value needs to change across environments (dev/staging/prod)?")

        # Pattern: bare except
        if "bare except" in text or "except:" in context:
            scenarios.append("What if a KeyboardInterrupt or SystemExit is silently swallowed?")
            scenarios.append("What if an unrelated bug is masked because all exceptions are caught?")

        # Pattern: long function / complex
        if "long" in text or "complex" in text:
            scenarios.append("What if a bug exists in line 40 but tests only cover lines 1-10?")
            scenarios.append("What if two developers modify different parts of this function simultaneously?")

        # Pattern: mutable default argument
        if "mutable default" in text or "default arg" in text:
            scenarios.append("What if the function is called twice — does the default list accumulate state?")

        # Fallback for unrecognized patterns
        if not scenarios:
            scenarios.append("What if the claim holds in the current codebase but fails after the next refactoring?")
            scenarios.append("What if the observed pattern is actually a symptom of a deeper architectural issue?")

        insight = self._generate_insight(text, scenarios)

        return CounterfactualResult(
            scenarios=scenarios[:5],
            insight=insight,
            claim_text=claim.get("text", ""),
        )

    @staticmethod
    def _generate_insight(text: str, scenarios: list[str]) -> str:
        if len(scenarios) >= 3:
            return (
                f"The claim '{text[:40]}...' appears robust on the surface, "
                f"but {len(scenarios)} critical counter-scenarios were identified. "
                f"The agent should either gather evidence against these scenarios or narrow the claim's scope."
            )
        elif scenarios:
            return (
                f"The claim '{text[:40]}...' has {len(scenarios)} potential weakness. "
                f"Further investigation recommended before accepting as valid."
            )
        return "No obvious counter-scenarios. Claim may be too vague to evaluate."
