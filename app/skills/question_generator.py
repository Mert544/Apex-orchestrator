from __future__ import annotations

from app.models.enums import ClaimType, QuestionType
from app.models.question import Question
from app.skills.claim_analyzer import ClaimAnalyzer

# (impact, uncertainty, risk) per question type — drives prioritisation.
_PROFILE: dict[QuestionType, tuple[float, float, float]] = {
    QuestionType.MISSING: (0.9, 0.9, 0.5),
    QuestionType.CONTRADICTION: (0.8, 0.7, 0.6),
    QuestionType.RISK: (0.7, 0.6, 0.9),
    QuestionType.DEEPENING: (0.75, 0.7, 0.4),
}

# Generic fallback when a claim has no clear domain.
_GENERAL: dict[QuestionType, str] = {
    QuestionType.MISSING: "What concrete evidence in the code is still missing to validate that: {claim}?",
    QuestionType.CONTRADICTION: "What observation in the codebase would directly contradict that: {claim}?",
    QuestionType.RISK: "If this is wrong, what part of the system breaks and how badly: {claim}?",
    QuestionType.DEEPENING: "Which underlying components or call paths actually produce this behavior: {claim}? Assumption anchor: {assumption}",
}

# Domain-specific question phrasing, keyed by claim type then question type.
# {focus} = the strongest detected signal; {claim} = short claim reference.
_TEMPLATES: dict[ClaimType, dict[QuestionType, str]] = {
    ClaimType.SECURITY: {
        QuestionType.MISSING: "Which untrusted inputs reach {focus} unsanitized, and what proves the path is safe? ({claim})",
        QuestionType.CONTRADICTION: "Is there an existing validation, auth, or sandbox layer that already neutralizes {focus}? ({claim})",
        QuestionType.RISK: "If {focus} is exploited, what data, credentials, or privileges are exposed? ({claim})",
        QuestionType.DEEPENING: "Trace the exact path from user input to {focus}: which function introduces the exposure? Assumption anchor: {assumption}",
    },
    ClaimType.VALIDATION: {
        QuestionType.MISSING: "Which behaviors of {focus} have no asserting test today? ({claim})",
        QuestionType.CONTRADICTION: "Could {focus} already be covered indirectly by integration or end-to-end tests? ({claim})",
        QuestionType.RISK: "Which untested branch around {focus} would silently break in production? ({claim})",
        QuestionType.DEEPENING: "What edge cases (empty, None, boundary, error paths) must {focus}'s tests assert? Assumption anchor: {assumption}",
    },
    ClaimType.ARCHITECTURE: {
        QuestionType.MISSING: "Which module boundaries or dependencies around {focus} are undocumented or unverified? ({claim})",
        QuestionType.CONTRADICTION: "Is there a cleaner existing seam that contradicts the need to touch {focus}? ({claim})",
        QuestionType.RISK: "If {focus}'s structure is wrong, which downstream modules suffer cascading change? ({claim})",
        QuestionType.DEEPENING: "What is the real control/data flow through {focus}, component by component? Assumption anchor: {assumption}",
    },
    ClaimType.CONFIGURATION: {
        QuestionType.MISSING: "Which environment or dependency settings behind {focus} are unspecified or implicit? ({claim})",
        QuestionType.CONTRADICTION: "Does a default or override already make {focus} safe across environments? ({claim})",
        QuestionType.RISK: "If {focus} differs between dev/staging/prod, what fails at runtime? ({claim})",
        QuestionType.DEEPENING: "Which config keys, env vars, or versions concretely determine {focus}? Assumption anchor: {assumption}",
    },
    ClaimType.AUTOMATION: {
        QuestionType.MISSING: "Which step in the {focus} pipeline lacks a verifying check or gate? ({claim})",
        QuestionType.CONTRADICTION: "Is {focus} already enforced by an existing workflow or hook? ({claim})",
        QuestionType.RISK: "If {focus} fails silently in CI, which regressions reach main? ({claim})",
        QuestionType.DEEPENING: "What are the exact triggers, jobs, and dependencies of {focus}? Assumption anchor: {assumption}",
    },
    ClaimType.FEATURE_GAP: {
        QuestionType.MISSING: "What concrete capability is absent for {focus}, and where would it live? ({claim})",
        QuestionType.CONTRADICTION: "Is {focus} actually implemented elsewhere under a different name? ({claim})",
        QuestionType.RISK: "What user-facing behavior is impossible today because {focus} is missing? ({claim})",
        QuestionType.DEEPENING: "Which existing functions would a fix for {focus} build on? Assumption anchor: {assumption}",
    },
    ClaimType.OPERATIONS: {
        QuestionType.MISSING: "Which runtime signals (logs, metrics, health) around {focus} are not observable? ({claim})",
        QuestionType.CONTRADICTION: "Is {focus} already monitored or handled by existing operational tooling? ({claim})",
        QuestionType.RISK: "If {focus} degrades in production, how long until it is detected? ({claim})",
        QuestionType.DEEPENING: "What is the runtime lifecycle of {focus} from start to failure? Assumption anchor: {assumption}",
    },
}

_ORDER = (
    QuestionType.MISSING,
    QuestionType.CONTRADICTION,
    QuestionType.RISK,
    QuestionType.DEEPENING,
)


class QuestionGenerator:
    """Generate the four mandatory question types, tailored to the claim.

    Instead of emitting the same four generic stems for every claim, the
    generator classifies the claim (reusing ClaimAnalyzer) and phrases each
    question for that domain — security, tests, architecture, config, CI,
    feature gaps, or operations — anchored on the concrete signal detected in
    the claim. Fully deterministic, no LLM.
    """

    def __init__(self, analyzer: ClaimAnalyzer | None = None) -> None:
        self.analyzer = analyzer or ClaimAnalyzer()

    def generate(self, claim: str, assumptions: list[str]) -> list[Question]:
        analysis = self.analyzer.analyze(claim)
        templates = _TEMPLATES.get(analysis.claim_type, _GENERAL)
        focus = analysis.signals[0] if analysis.signals else "the subject of this claim"
        assumption = assumptions[0] if assumptions else "No explicit assumptions extracted."
        claim_ref = claim if len(claim) <= 80 else claim[:77] + "..."

        questions: list[Question] = []
        for qtype in _ORDER:
            text = templates[qtype].format(
                focus=focus, claim=claim_ref, assumption=assumption
            )
            impact, uncertainty, risk = _PROFILE[qtype]
            questions.append(
                Question(
                    text=text,
                    qtype=qtype,
                    impact=impact,
                    uncertainty=uncertainty,
                    risk=risk,
                )
            )
        return questions
