from __future__ import annotations

from app.engine.recursive_reflection import RecursiveReflectionEngine, ReflectionResult


def test_reflection_on_strong_claim():
    engine = RecursiveReflectionEngine()
    claim = {
        "text": "Auth module uses secure hashing with salt",
        "evidence": ["Line 15: hashlib.sha256(salt + password)", "Line 20: random salt generation", "Line 25: constant time compare"],
        "confidence": 0.85,
        "source_file": "app/auth/tokens.py",
    }
    result = engine.reflect(claim)
    assert result.is_valid is True
    assert result.reflection_depth >= 3
    assert any("sufficient" in r.lower() for r in result.reflections)


def test_reflection_on_weak_claim():
    engine = RecursiveReflectionEngine()
    claim = {
        "text": "All inputs are validated everywhere",
        "evidence": ["Line 5: input() in main.py"],
        "confidence": 0.4,
        "source_file": "app/main.py",
    }
    result = engine.reflect(claim)
    assert result.needs_more_evidence is True
    assert any("insufficient" in r.lower() or "weak" in r.lower() for r in result.reflections)


def test_reflection_checks_boundaries():
    engine = RecursiveReflectionEngine()
    claim = {
        "text": "Payment gateway is thread-safe",
        "evidence": ["Line 10: uses threading.Lock"],
        "confidence": 0.7,
        "source_file": "app/payments/gateway.py",
    }
    result = engine.reflect(claim)
    assert any("bounded" in r.lower() or "boundary" in r.lower() or "scope" in r.lower() for r in result.reflections)


def test_reflection_generates_counterexamples():
    engine = RecursiveReflectionEngine()
    claim = {
        "text": "No SQL injection possible",
        "evidence": ["Line 8: uses parameterized queries"],
        "confidence": 0.9,
        "source_file": "app/db/queries.py",
    }
    result = engine.reflect(claim)
    assert len(result.counter_examples) > 0
    assert any("what if" in ce.lower() or "if" in ce.lower() for ce in result.counter_examples)


def test_reflection_produces_insight():
    engine = RecursiveReflectionEngine()
    claim = {
        "text": "Function is too long",
        "evidence": ["Line 1-50: 50 lines"],
        "confidence": 0.6,
        "source_file": "app/utils.py",
    }
    result = engine.reflect(claim)
    assert result.insight != ""
    assert len(result.reflections) >= 3


def test_deep_recursive_reflection():
    engine = RecursiveReflectionEngine(max_depth=5)
    claim = {
        "text": "Project has no security issues",
        "evidence": ["Manual review completed"],
        "confidence": 0.3,
        "source_file": "",
    }
    result = engine.reflect(claim)
    assert result.reflection_depth >= 4
    assert result.is_valid is False
    assert result.rationale != ""
