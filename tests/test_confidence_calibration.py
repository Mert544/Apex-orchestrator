from __future__ import annotations

from app.engine.confidence_calibration import ConfidenceCalibrator, CalibrationResult


def test_calibrate_with_strong_evidence():
    calibrator = ConfidenceCalibrator()
    claim = {
        "confidence": 0.8,
        "evidence": [
            {"source": "static_analysis", "type": "direct", "weight": 1.0},
            {"source": "test_failure", "type": "direct", "weight": 1.0},
            {"source": "code_review", "type": "indirect", "weight": 0.7},
        ],
    }
    result = calibrator.calibrate(claim)
    assert result.adjusted_confidence > claim["confidence"]
    assert result.reliability == "high"
    assert result.is_calibrated is True


def test_calibrate_with_weak_evidence():
    calibrator = ConfidenceCalibrator()
    claim = {
        "confidence": 0.8,
        "evidence": [
            {"source": "heuristic_guess", "type": "indirect", "weight": 0.3},
        ],
    }
    result = calibrator.calibrate(claim)
    assert result.adjusted_confidence < claim["confidence"]
    assert result.reliability in ("low", "medium")


def test_calibrate_with_conflicting_evidence():
    calibrator = ConfidenceCalibrator()
    claim = {
        "confidence": 0.9,
        "evidence": [
            {"source": "static_analysis", "type": "direct", "weight": 1.0},
            {"source": "runtime_log", "type": "direct", "weight": 1.0, "contradicts": True},
        ],
    }
    result = calibrator.calibrate(claim)
    assert result.adjusted_confidence < claim["confidence"]
    assert result.has_conflict is True


def test_diversity_bonus():
    calibrator = ConfidenceCalibrator()
    claim = {
        "confidence": 0.6,
        "evidence": [
            {"source": "static_analysis", "type": "direct", "weight": 1.0},
            {"source": "test_failure", "type": "direct", "weight": 1.0},
            {"source": "manual_review", "type": "direct", "weight": 1.0},
        ],
    }
    result = calibrator.calibrate(claim)
    assert result.diversity_score >= 0.8


def test_calibration_with_no_evidence():
    calibrator = ConfidenceCalibrator()
    claim = {"confidence": 0.5, "evidence": []}
    result = calibrator.calibrate(claim)
    assert result.adjusted_confidence < claim["confidence"]
    assert result.reliability == "low"


def test_calibration_result_to_dict():
    calibrator = ConfidenceCalibrator()
    result = calibrator.calibrate({"confidence": 0.7, "evidence": [{"source": "test", "type": "direct", "weight": 1.0}]})
    d = result.to_dict()
    assert "adjusted_confidence" in d
    assert "reliability" in d
