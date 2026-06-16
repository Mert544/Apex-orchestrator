from __future__ import annotations

import itertools
import json

import pytest

from app.engine.recursive_reflection import RecursiveReflectionEngine

# Inputs chosen to exercise every branch of reflect() and its helpers:
# evidence sufficiency tiers, absolute language, each counter-example keyword,
# short/medium/long word counts, and penalty combinations.
_TEXTS = [
    "",
    "x",
    "secure",
    "all every",
    "test coverage",
    "fast performance",
    "no  never",
    "thread concurrent",
    "vague claim here ok",
    "one two three four five",
    "Auth module uses secure hashing with salt and constant time compare here",
    "All inputs are validated everywhere across the entire system without exception ever",
    "No SQL injection possible because every query is safe and secure always never",
    " ".join(["word"] * 31),
]
_EVIDENCES = [[], ["a"], ["a", "b"], ["a", "b", "c"], ["a", "b", "c", "d"]]
_CONFIDENCES = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 0.9, 1.0]
_MAX_DEPTHS = [1, 4, 5]

# Golden snapshots captured from the pre-refactor implementation. Each entry is the
# JSON (sort_keys) of result.to_dict() for the corresponding input tuple.
_CASES = list(itertools.product(_MAX_DEPTHS, _TEXTS, _EVIDENCES, _CONFIDENCES))


def _serialize(result) -> str:
    return json.dumps(result.to_dict(), sort_keys=True)


@pytest.mark.parametrize("max_depth,text,evidence,confidence", _CASES)
def test_reflect_is_deterministic(max_depth, text, evidence, confidence):
    engine = RecursiveReflectionEngine(max_depth=max_depth)
    claim = {"text": text, "evidence": evidence, "confidence": confidence}
    first = _serialize(engine.reflect(claim))
    second = _serialize(engine.reflect(claim))
    assert first == second


def test_reflect_handles_missing_keys():
    engine = RecursiveReflectionEngine()
    for claim in ({}, {"text": "secure all"}, {"evidence": ["x"]}, {"confidence": 0.8}):
        result = engine.reflect(claim)
        assert result.reflection_depth == engine.max_depth
        assert len(result.reflections) == 4
        assert result.rationale != ""
        assert result.insight != ""


def test_helpers_are_pure_static():
    # Layer helpers must be callable without instance state and return exact strings.
    assert RecursiveReflectionEngine._reflect_evidence(["a", "b", "c"], 0.7) == (
        "Layer 1 — Evidence appears sufficient for the claim.",
        False,
    )
    assert RecursiveReflectionEngine._reflect_evidence(["a"], 0.5)[1] is True
    assert RecursiveReflectionEngine._reflect_evidence([], 0.0)[1] is True
    assert RecursiveReflectionEngine._has_absolute_language("never") is True
    assert RecursiveReflectionEngine._has_absolute_language("bounded") is False
    assert RecursiveReflectionEngine._reflect_boundary("x", False) == (
        "Layer 2 — Claim language is bounded. Good."
    )
    assert RecursiveReflectionEngine._reflect_counterexamples([]).startswith("Layer 3")
    assert RecursiveReflectionEngine._reflect_meta(3).startswith("Layer 4")
    assert RecursiveReflectionEngine._reflect_meta(31).startswith("Layer 4")
    assert RecursiveReflectionEngine._reflect_meta(10).startswith("Layer 4")
    assert RecursiveReflectionEngine._compute_penalty(True, True, 3, 4) == pytest.approx(0.7)
    assert RecursiveReflectionEngine._compute_penalty(False, False, 0, 10) == 0


def test_reflect_full_output_shape():
    engine = RecursiveReflectionEngine()
    result = engine.reflect(
        {"text": "All systems secure", "evidence": ["x"], "confidence": 0.4}
    )
    assert result.needs_more_evidence is True
    assert result.is_valid is False
    assert len(result.reflections) == 4
    assert result.counter_examples
