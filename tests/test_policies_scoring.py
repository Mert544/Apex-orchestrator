from app.policies.scoring import (
    score_claim_priority,
    score_confidence,
    score_question_priority,
)


def test_score_confidence_branches():
    assert score_confidence(0, 0) == 0.25            # no evidence for
    assert score_confidence(2, 3) == 0.45            # against >= for
    assert score_confidence(3, 0) == 0.85            # strong, uncontested
    assert score_confidence(2, 1) == 0.65            # mixed but net-positive


def test_question_priority_weights_and_focus():
    full = score_question_priority(1.0, 1.0, 1.0, 1.0, relevance=1.0)
    assert full == 1.0                                # all-max, full relevance
    half = score_question_priority(1.0, 1.0, 1.0, 1.0, relevance=0.0)
    assert half == 0.5                               # off-topic -> halved, not zero
    assert score_question_priority(0.0, 0.0, 0.0, 0.0) == 0.0


def test_claim_priority_weights():
    # base = .35*imp + .30*risk + .20*nov + .15*gap, times focus multiplier
    assert round(score_claim_priority(1.0, 0.0, 0.0, 0.0), 4) == 0.35
    assert round(score_claim_priority(0.0, 1.0, 0.0, 0.0), 4) == 0.30
    assert round(score_claim_priority(1.0, 1.0, 1.0, 1.0, relevance=0.0), 4) == 0.5
