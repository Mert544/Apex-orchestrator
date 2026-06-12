"""QualityJudge: evidence composes the score additively, capped at 1.0."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.skills.quality_judge import QualityJudge


def _node(evidence_for=(), evidence_against=(), assumptions=(), questions=()):
    return SimpleNamespace(
        evidence_for=list(evidence_for), evidence_against=list(evidence_against),
        assumptions=list(assumptions), questions=list(questions),
    )


def test_bare_node_gets_the_floor_score():
    assert QualityJudge().evaluate(_node()) == 0.35


def test_each_evidence_kind_adds_its_weight():
    judge = QualityJudge()
    assert judge.evaluate(_node(evidence_for=["a"])) == pytest.approx(0.55)
    assert judge.evaluate(_node(evidence_against=["b"])) == pytest.approx(0.50)
    assert judge.evaluate(_node(assumptions=["c"])) == pytest.approx(0.45)
    # Questions only count once there are at least four (real interrogation).
    assert judge.evaluate(_node(questions=["q"] * 3)) == pytest.approx(0.35)
    assert judge.evaluate(_node(questions=["q"] * 4)) == pytest.approx(0.45)


def test_full_evidence_caps_below_one():
    node = _node(evidence_for=["a"], evidence_against=["b"],
                 assumptions=["c"], questions=["q"] * 5)
    score = QualityJudge().evaluate(node)
    assert score == 0.90 and score <= 1.0
