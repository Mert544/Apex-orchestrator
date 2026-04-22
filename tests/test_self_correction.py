from __future__ import annotations

from app.engine.self_correction import SelfCorrectionEngine, CorrectionAction


def test_no_correction_when_strong():
    engine = SelfCorrectionEngine(min_confidence=0.6)
    claim = {
        "claim": "Auth module uses secure hashing",
        "confidence": 0.85,
        "evidence_count": 3,
        "counter_evidence_count": 1,
        "depth": 2,
    }
    result = engine.evaluate(claim, budget_remaining=10)
    assert result.action == CorrectionAction.NONE
    assert result.should_expand is False


def test_expand_when_low_confidence():
    engine = SelfCorrectionEngine(min_confidence=0.6)
    claim = {
        "claim": "Payment gateway is untested",
        "confidence": 0.35,
        "evidence_count": 1,
        "counter_evidence_count": 0,
        "depth": 1,
    }
    result = engine.evaluate(claim, budget_remaining=10)
    # Low confidence + missing counter-evidence triggers SEEK_COUNTER_EVIDENCE first
    assert result.action == CorrectionAction.SEEK_COUNTER_EVIDENCE
    assert result.should_expand is True
    assert "counter-evidence" in result.rationale.lower()


def test_expand_when_missing_counter_evidence():
    engine = SelfCorrectionEngine(min_confidence=0.6)
    claim = {
        "claim": "All inputs are validated",
        "confidence": 0.75,
        "evidence_count": 2,
        "counter_evidence_count": 0,
        "depth": 1,
    }
    result = engine.evaluate(claim, budget_remaining=10)
    assert result.action == CorrectionAction.SEEK_COUNTER_EVIDENCE
    assert result.should_expand is True
    assert "counter-evidence" in result.rationale.lower()


def test_no_expand_when_budget_exhausted():
    engine = SelfCorrectionEngine(min_confidence=0.6)
    claim = {
        "claim": "Something vague",
        "confidence": 0.3,
        "evidence_count": 0,
        "counter_evidence_count": 0,
        "depth": 3,
    }
    result = engine.evaluate(claim, budget_remaining=0)
    assert result.action == CorrectionAction.BUDGET_HALT
    assert result.should_expand is False
    assert "budget" in result.rationale.lower()


def test_flag_meta_claim():
    engine = SelfCorrectionEngine(min_confidence=0.6)
    claim = {
        "claim": "The previous claim about claims is questionable",
        "confidence": 0.5,
        "evidence_count": 0,
        "counter_evidence_count": 0,
        "depth": 2,
    }
    result = engine.evaluate(claim, budget_remaining=10)
    assert result.action == CorrectionAction.FLAG_META
    assert "meta" in result.rationale.lower()


def test_deep_claims_get_less_aggressive_expansion():
    engine = SelfCorrectionEngine(min_confidence=0.6)
    claim = {
        "claim": "Deep nested insight",
        "confidence": 0.5,
        "evidence_count": 1,
        "counter_evidence_count": 0,
        "depth": 5,
    }
    result = engine.evaluate(claim, budget_remaining=10)
    # Deep claims get lower priority for expansion
    assert result.priority == "low"
