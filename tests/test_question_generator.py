from app.models.enums import QuestionType
from app.skills.question_generator import QuestionGenerator


def test_question_generator_emits_all_four_types():
    qgen = QuestionGenerator()
    questions = qgen.generate("A claim", ["An assumption"])
    emitted = {q.qtype for q in questions}
    assert emitted == {
        QuestionType.MISSING,
        QuestionType.CONTRADICTION,
        QuestionType.RISK,
        QuestionType.DEEPENING,
    }


def test_questions_are_domain_specific():
    qgen = QuestionGenerator()
    sec = " ".join(q.text for q in qgen.generate("auth token secret is exposed", []))
    val = " ".join(q.text for q in qgen.generate("test coverage gap in module", []))

    # Security claims and validation claims get distinct, tailored phrasing.
    assert sec != val
    assert "exploited" in sec or "unsanitized" in sec
    assert "test" in val.lower()


def test_questions_anchor_on_detected_signal():
    qgen = QuestionGenerator()
    text = " ".join(q.text for q in qgen.generate("a security risk in payment flow", []))
    # The strongest detected signal (e.g. security/payment) is referenced.
    assert "security" in text or "payment" in text


def test_deepening_question_uses_assumption():
    qgen = QuestionGenerator()
    questions = qgen.generate("architecture module boundary", ["modules are decoupled"])
    deepening = next(q for q in questions if q.qtype == QuestionType.DEEPENING)
    assert "modules are decoupled" in deepening.text


def test_handles_claim_with_braces_safely():
    qgen = QuestionGenerator()
    # A claim containing braces must not break str.format templating.
    questions = qgen.generate("config dict {key: value} is implicit", [])
    assert len(questions) == 4
