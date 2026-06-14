from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Distinct stress-test scenarios per development lens. Each lens introduces its
# own class of risk, so the counterfactual that pressure-tests it differs — this
# is what stops every idea collapsing onto one generic "malformed input" caveat.
_LENS_SCENARIOS: dict[str, list[str]] = {
    "extend": [
        "What new failure mode does this capability add that nothing exercises yet?",
        "What if the new path interacts with an existing one in a way no test covers?",
    ],
    "harden": [
        "What if an attacker provides None, malformed, or maximum-size input?",
        "What legitimate edge case might the new guard wrongly reject?",
    ],
    "test": [
        "What behavior is asserted nowhere, so a regression would pass silently?",
        "What boundary (empty, single, maximum) does the current suite skip?",
    ],
    "simplify": [
        "What subtle behavior could silently change when this is refactored?",
        "What currently depends on the exact structure a cleanup would remove?",
    ],
    "document": [
        "What contract do callers assume that is written down nowhere?",
        "What breaks when the behavior changes but the documentation does not?",
    ],
    "integrate": [
        "What if the other subsystem is down, slow, or returns an unexpected shape?",
        "What version skew or contract mismatch could break this seam?",
    ],
    "generalize": [
        "What assumption breaks when a second caller uses this with different config?",
        "What hard-coded default becomes wrong once this is reused elsewhere?",
    ],
    "observe": [
        "What failure currently happens invisibly, with no metric or log to catch it?",
        "What early signal would reveal this degrading before it fails outright?",
    ],
    "decouple": [
        "What hidden behavior of the concrete dependency does a caller secretly rely on?",
        "What breaks once this talks to an interface instead of the real collaborator?",
    ],
    "verify": [
        "What invariant does this code assume but never actually assert or prove?",
        "What input would make the proof's preconditions false, so the guarantee silently stops holding?",
    ],
    "fortify": [
        "What edge input (None, empty, malformed, or past the boundary) reaches this unhandled today?",
        "What legitimate value would the new minimal guard wrongly reject or alter behavior for?",
    ],
}


# Root ideas have no lens yet — their discriminator is the fact that seeded them.
# Keying caveats on that fact stops every security/coverage root collapsing onto
# the same generic "malformed input" scenario.
_FACT_SCENARIOS: dict[str, list[str]] = {
    "untested": [
        "What breaks the moment someone changes this, with no test to catch it?",
        "What current behavior would a rewrite silently alter, undetected?",
    ],
    "critical-untested": [
        "What production failure would land first if this safety-critical path regressed?",
        "What behavior is relied on here that no test currently pins down?",
    ],
    "sensitive-path": [
        "What can an attacker do by reaching this path with crafted input?",
        "What sensitive data leaks if this path fails open instead of closed?",
    ],
    "security-finding": [
        "What can an attacker execute by reaching the eval/exec/deserialize call here?",
        "What untrusted input flows into this dangerous call unchecked?",
    ],
    "fragile": [
        "What downstream module breaks if this heavily-depended-on hub changes behavior?",
        "What untested edge here cascades across everything that imports it?",
    ],
    "dependency-hub": [
        "What ripples through the system if this central module's contract shifts?",
        "What hidden coupling does this hub's blast radius conceal?",
    ],
    "complexity-hotspot": [
        "What rare branch in this complex module is exercised by no test?",
        "What second-developer change could collide inside this complexity?",
    ],
    "shallow-coverage": [
        "What real behavior do these shape-only (isinstance/None) tests fail to pin down?",
        "What regression slips silently past an assertion that only checks types?",
    ],
    "convergence": [
        "Which converging risk do you fix first, and what does deferring the rest cost?",
        "What happens if you harden this before the safety-net tests are in place?",
    ],
    "missing-ci": [
        "What broken change merges undetected with no automated gate to stop it?",
        "What passes locally but fails in a clean environment nobody checks?",
    ],
}


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
        symbol = claim.get("symbol", "")
        operator = claim.get("operator", "")
        scenarios = []

        # Symbol-grounded scenarios come first: when the claim names an actual
        # function, the caveat should interrogate *it*, not recite a template.
        if symbol:
            scenarios.append(
                f"What if {symbol}() hits its rarest branch with an input no test has ever exercised?"
            )
            scenarios.append(
                f"What if a caller depends on an undocumented behavior of {symbol}() that a refactor silently changes?"
            )

        # Lens-specific stress test: each development lens fails in a different
        # way, so the caveat must interrogate *that* lens — not route every idea
        # through the validation-keyword branch below (which made 'extend',
        # 'test', and 'generalize' all emit the same "attacker provides None"
        # scenario). When the claim names its operator, branch on it directly.
        if operator in _LENS_SCENARIOS:
            scenarios.extend(_LENS_SCENARIOS[operator])
            insight = self._generate_insight(operator or text, scenarios)
            return CounterfactualResult(
                scenarios=scenarios[:5], insight=insight, claim_text=claim.get("text", ""),
            )

        # A root idea (no lens) is discriminated by the fact that seeded it.
        fact_label = claim.get("fact_label", "")
        if fact_label in _FACT_SCENARIOS:
            scenarios.extend(_FACT_SCENARIOS[fact_label])
            insight = self._generate_insight(fact_label, scenarios)
            return CounterfactualResult(
                scenarios=scenarios[:5], insight=insight, claim_text=claim.get("text", ""),
            )

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
