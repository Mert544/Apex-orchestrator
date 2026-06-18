from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


# Distinct stress-test scenarios per development lens. Each lens introduces its
# own class of risk, so the counterfactual that pressure-tests it differs — this
# is what stops every idea collapsing onto one generic "malformed input" caveat.
#
# Coverage invariant: every operator name in DEVELOPMENT_OPERATORS
# (app/engine/idea_permutation.py) must have an entry here, so no development
# lens ever falls through to the generic keyword fallback. The test suite
# (tests/test_counterfactual_depth.py) enforces this. Each scenario names a
# *concrete* failure mode — a test gap, a rollback risk, a coupling seam, a
# SafetyGates rejection — never a vague "something could break". Security stays
# a supporting signal (it surfaces under harden/fortify), never the headline.
_LENS_SCENARIOS: dict[str, list[str]] = {
    "extend": [
        "What untested path does this new capability add, so its first failure lands in production unguarded?",
        "What existing behavior does the new code path quietly perturb, with no regression test pinning the old contract?",
    ],
    "harden": [
        "What if an attacker reaches this with None, malformed, or maximum-size input the new guard never anticipated?",
        "What legitimate edge case does the tightened guard now wrongly reject, breaking a caller that relied on the looser behavior?",
    ],
    "test": [
        "What behavior is asserted nowhere, so a regression merges green and ships unnoticed?",
        "What boundary (empty, single, maximum) does the current suite skip, leaving that branch unexercised?",
    ],
    "simplify": [
        "What subtle behavior could the refactor silently change, with no characterization test to flag the rollback?",
        "What caller depends on the exact structure or ordering this cleanup removes?",
    ],
    "document": [
        "What contract do callers already assume that is written down nowhere, so the docs codify a guess?",
        "What drifts the moment the behavior changes but the documentation does not, misleading the next reader?",
    ],
    "integrate": [
        "What if the other subsystem is down, slow, or returns an unexpected shape this seam never validates?",
        "What version skew or contract mismatch across this new coupling breaks both sides at once?",
    ],
    "generalize": [
        "What assumption breaks when a second caller drives this with different config than the original use?",
        "What hard-coded default silently becomes wrong once this is reused outside its first context?",
    ],
    "observe": [
        "What failure currently happens invisibly here, with no metric or log to catch it before users do?",
        "What early signal would reveal this degrading, and does the new instrumentation actually emit it under load?",
    ],
    "decouple": [
        "What hidden behavior of the concrete dependency does a caller secretly rely on, that the new interface drops?",
        "What coupling does swapping in an abstraction merely relocate rather than remove, leaving the seam just as fragile?",
    ],
    "verify": [
        "What invariant does this code assume but never actually assert, so the proof rests on an unchecked premise?",
        "What input would make the proof's preconditions false, so the guarantee silently stops holding?",
    ],
    "fortify": [
        "What edge input (None, empty, malformed, or past the boundary) reaches this unhandled today and trips the failure the guard is meant to close?",
        "What legitimate value would the new minimal guard wrongly reject or alter behavior for, regressing a passing caller?",
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


# Risk-pattern rule table for keyword-derived scenarios. Each rule is a
# (predicate, scenarios) pair: the predicate inspects the lowercased claim text
# and context, and when it fires its scenarios are appended in table order. The
# table replaces a flat series of independent guards so _keyword_scenarios stays
# a simple fold; rule ORDER here is the emitted scenario order and must not move.


def _has_any(text: str, *needles: str) -> bool:
    return any(n in text for n in needles)


# Pattern: missing validation / no guard
def _rule_validation(text: str, context: str) -> bool:
    return _has_any(text, "validation", "guard", "check", "sanitize")


# Pattern: eval / exec / dangerous function
def _rule_eval(text: str, context: str) -> bool:
    return "eval" in text or "exec" in text


# Pattern: missing docstring / documentation
def _rule_docs(text: str, context: str) -> bool:
    return "docstring" in text or "documented" in text


# Pattern: network / external call
def _rule_network(text: str, context: str) -> bool:
    return _has_any(text, "network", "request", "fetch", "call")


# Pattern: hardcoded values / secrets
def _rule_secrets(text: str, context: str) -> bool:
    return _has_any(text, "hardcoded", "secret", "password")


# Pattern: bare except
def _rule_bare_except(text: str, context: str) -> bool:
    return "bare except" in text or "except:" in context


# Pattern: long function / complex
def _rule_complex(text: str, context: str) -> bool:
    return "long" in text or "complex" in text


# Pattern: mutable default argument
def _rule_mutable_default(text: str, context: str) -> bool:
    return "mutable default" in text or "default arg" in text


_KEYWORD_RULES: list[tuple[Callable[[str, str], bool], list[str]]] = [
    (
        _rule_validation,
        [
            "What if an attacker provides None or malformed input?",
            "What if the input is at the maximum possible size?",
            "What if the input contains unicode null bytes or escape sequences?",
        ],
    ),
    (
        _rule_eval,
        [
            "What if the expression string contains '__import__('os').system('rm -rf /')'?",
            "What if a trusted user accidentally passes user-controlled input?",
        ],
    ),
    (
        _rule_docs,
        [
            "What if a new developer joins and cannot understand the function's contract?",
            "What if the function behavior changes but the callers assume the old contract?",
        ],
    ),
    (
        _rule_network,
        [
            "What if the remote server is down or responds with a 500 error?",
            "What if the connection hangs indefinitely (no timeout)?",
            "What if DNS resolution fails or the network is partitioned?",
        ],
    ),
    (
        _rule_secrets,
        [
            "What if the source code is leaked or committed to a public repository?",
            "What if the hardcoded value needs to change across environments (dev/staging/prod)?",
        ],
    ),
    (
        _rule_bare_except,
        [
            "What if a KeyboardInterrupt or SystemExit is silently swallowed?",
            "What if an unrelated bug is masked because all exceptions are caught?",
        ],
    ),
    (
        _rule_complex,
        [
            "What if a bug exists in line 40 but tests only cover lines 1-10?",
            "What if two developers modify different parts of this function simultaneously?",
        ],
    ),
    (
        _rule_mutable_default,
        [
            "What if the function is called twice — does the default list accumulate state?",
        ],
    ),
]


# Deterministic translation from a converging signal label (a confluence family
# name or an idea ``fact_label``) to the concrete CONSEQUENCE of leaving that
# concern unaddressed — the "what happens if this is NOT fixed?" half of a
# counterfactual. Small, explicit, and obviously correct; any label not listed
# here is simply skipped (it contributes no consequence). Several distinct labels
# legitimately share one consequence (a hub, a dependency-hub and a symbol-hub
# all blast-radius the same way); the enricher de-duplicates identical fragments
# so two synonymous labels do not repeat the same clause.
_SIGNAL_CONSEQUENCE_MAP: dict[str, str] = {
    # high blast-radius / central coupling — a change ripples outward
    "hub": "a change here ripples to every dependent",
    "dependency-hub": "a change here ripples to every dependent",
    "symbol-hub": "a change here ripples to every dependent",
    "god-class": "a change here ripples to every dependent",
    "fragile": "a change here ripples to every dependent",
    # missing tests — a regression merges and ships unnoticed
    "untested": "there is no test to catch the regression",
    "critical-untested": "a safety-critical regression ships with no test to catch it",
    "shallow-coverage": "the shape-only tests let a real regression slip past unnoticed",
    # security / sensitive paths — an attacker reaches it unguarded
    "sensitive-path": "an attacker can reach this path with crafted input",
    "security-finding": "untrusted input flows into a dangerous call unchecked",
    "eval": "untrusted input flows into a dynamic-eval call unchecked",
    "security-eval": "untrusted input flows into a dynamic-eval call unchecked",
    # complexity — a rare branch stays unexercised and silently wrong
    "complexity-hotspot": "a rare branch stays unexercised and silently breaks",
    "complex-function": "a rare branch stays unexercised and silently breaks",
    # missing automated gate — broken changes merge undetected
    "missing-ci": "broken changes merge with no automated gate to stop them",
    # documentation drift — callers act on a stale contract
    "doc-drift": "callers keep trusting a contract the code no longer honours",
    "missing-docstring": "callers keep trusting a contract written down nowhere",
}


def counterfactual_enrichment(labels: object) -> "tuple[str | None, list[str] | None]":
    """Counterfactual ("risk if unaddressed") reasoning over converging labels.

    Maps the converging signal labels to the likely CONSEQUENCE of leaving these
    concerns unfixed and returns a grounded, deterministic one-line clause plus
    the matching extra source_fact, mirroring the ``_abductive`` enricher's
    contract: ``(clause, [f"counterfactual: {clause}"])`` on success, or
    ``(None, None)`` when fewer than 2 labels are mappable (so an idea without
    grounded reasoning stays byte-identical). Deterministic — no time/random.
    """
    consequences: list[str] = []
    seen: set[str] = set()
    for label in labels or []:
        fragment = _SIGNAL_CONSEQUENCE_MAP.get(label)
        if fragment is None or fragment in seen:
            continue
        seen.add(fragment)
        consequences.append(fragment)
    if len(consequences) < 2:
        return None, None
    clause = "risk if unaddressed: " + " and ".join(consequences)
    return clause, [f"counterfactual: {clause}"]


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

        # Symbol-grounded scenarios come first: when the claim names an actual
        # function, the caveat should interrogate *it*, not recite a template.
        scenarios = self._symbol_scenarios(symbol)

        # A keyed claim (development lens, or a root idea's seeding fact) routes
        # to its own discriminated scenario list and returns immediately, so it
        # never collapses onto the generic validation-keyword branch below.
        keyed = self._keyed_scenarios(operator, claim.get("fact_label", ""))
        if keyed is not None:
            seed, extra = keyed
            scenarios.extend(extra)
            return self._build(scenarios, seed or text, claim)

        # Otherwise interrogate the claim text/context for known risk patterns,
        # falling back to a generic pair when none match.
        scenarios.extend(self._keyword_scenarios(text, context))
        if not scenarios:
            scenarios.append("What if the claim holds in the current codebase but fails after the next refactoring?")
            scenarios.append("What if the observed pattern is actually a symptom of a deeper architectural issue?")

        return self._build(scenarios, text, claim)

    def _build(
        self, scenarios: list[str], insight_seed: str, claim: dict[str, Any]
    ) -> CounterfactualResult:
        return CounterfactualResult(
            scenarios=scenarios[:5],
            insight=self._generate_insight(insight_seed, scenarios),
            claim_text=claim.get("text", ""),
        )

    @staticmethod
    def _symbol_scenarios(symbol: str) -> list[str]:
        if not symbol:
            return []
        return [
            f"What if {symbol}() hits its rarest branch with an input no test has ever exercised?",
            f"What if a caller depends on an undocumented behavior of {symbol}() that a refactor silently changes?",
        ]

    @staticmethod
    def _keyed_scenarios(
        operator: str, fact_label: str
    ) -> tuple[str, list[str]] | None:
        # Lens-specific stress test: each development lens fails in a different
        # way, so the caveat must interrogate *that* lens — not route every idea
        # through the validation-keyword branch (which made 'extend', 'test',
        # and 'generalize' all emit the same "attacker provides None" scenario).
        if operator in _LENS_SCENARIOS:
            return operator, list(_LENS_SCENARIOS[operator])
        # A root idea (no lens) is discriminated by the fact that seeded it.
        if fact_label in _FACT_SCENARIOS:
            return fact_label, list(_FACT_SCENARIOS[fact_label])
        return None

    @staticmethod
    def _keyword_scenarios(text: str, context: str) -> list[str]:
        scenarios: list[str] = []
        for predicate, matches in _KEYWORD_RULES:
            if predicate(text, context):
                scenarios.extend(matches)
        return scenarios

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
