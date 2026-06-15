"""Edge/branch coverage for app.policies.constitution.

The three functions are pure guards over question/node attributes; no module
imports them in the existing policy-filtered suite, so all branches were
uncovered. These tests pin each branch deterministically:

  - enforce_four_question_types raises iff a mandatory class is absent, and is
    silent when all four are present;
  - downgrade_if_unsupported caps confidence to 0.30 only when there is no
    supporting evidence, and leaves a high-confidence supported node alone;
  - must_search_counter_evidence injects the placeholder only when no
    counter-evidence exists, and is a no-op otherwise.

Lightweight SimpleNamespace stand-ins keep the tests stdlib-only and hermetic
(the functions only read .qtype / .evidence_for / .evidence_against /
.confidence — no pydantic construction required).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.enums import QuestionType
from app.policies.constitution import (
    MANDATORY_QUESTION_TYPES,
    downgrade_if_unsupported,
    enforce_four_question_types,
    must_search_counter_evidence,
)


def _q(qtype: QuestionType) -> SimpleNamespace:
    return SimpleNamespace(qtype=qtype)


# --------------------------------------------------------------------------- #
# enforce_four_question_types                                                  #
# --------------------------------------------------------------------------- #
def test_all_four_types_present_is_silent():
    questions = [_q(t) for t in MANDATORY_QUESTION_TYPES]
    assert enforce_four_question_types(questions) is None


def test_missing_one_type_raises_naming_the_gap():
    # Drop RISK; the other three are present.
    questions = [
        _q(QuestionType.MISSING),
        _q(QuestionType.CONTRADICTION),
        _q(QuestionType.DEEPENING),
    ]
    with pytest.raises(ValueError) as exc:
        enforce_four_question_types(questions)
    assert "RISK" in str(exc.value)


def test_empty_questions_raises():
    with pytest.raises(ValueError):
        enforce_four_question_types([])


# --------------------------------------------------------------------------- #
# downgrade_if_unsupported                                                     #
# --------------------------------------------------------------------------- #
def test_unsupported_node_confidence_is_capped():
    node = SimpleNamespace(evidence_for=[], confidence=0.95)
    out = downgrade_if_unsupported(node)
    assert out is node
    assert out.confidence == 0.30


def test_unsupported_node_already_low_confidence_unchanged():
    # min(0.10, 0.30) == 0.10 — the cap never raises confidence.
    node = SimpleNamespace(evidence_for=[], confidence=0.10)
    out = downgrade_if_unsupported(node)
    assert out.confidence == 0.10


def test_supported_node_keeps_high_confidence():
    node = SimpleNamespace(evidence_for=["a citation"], confidence=0.95)
    out = downgrade_if_unsupported(node)
    assert out.confidence == 0.95


# --------------------------------------------------------------------------- #
# must_search_counter_evidence                                                 #
# --------------------------------------------------------------------------- #
def test_missing_counter_evidence_gets_placeholder():
    node = SimpleNamespace(evidence_against=[])
    out = must_search_counter_evidence(node)
    assert out is node
    assert out.evidence_against == [
        "No counter-evidence found yet; search incomplete."
    ]


def test_existing_counter_evidence_untouched():
    node = SimpleNamespace(evidence_against=["a real rebuttal"])
    out = must_search_counter_evidence(node)
    assert out.evidence_against == ["a real rebuttal"]
