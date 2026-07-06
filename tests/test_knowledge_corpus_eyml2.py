"""Cross-project knowledge corpus — tolerance edge paths (eyml2 wave).

Targets the branches the first wave left uncovered: a corpus whose ``signatures``
slot is missing or not a dict (rebuilt in place), and the negative-count clamp.
Deterministic, offline, stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.knowledge_corpus import (
    SCHEMA,
    _clamp_count,
    _signatures,
    consult,
    record_outcome,
)


def test_signatures_rebuilds_map_when_value_is_not_a_dict():
    corpus = {"schema": SCHEMA, "version": "1.0", "signatures": "corrupt"}
    sigs = _signatures(corpus)
    assert sigs == {}
    # The corpus is repaired in place so later folds have a real map.
    assert isinstance(corpus["signatures"], dict)
    assert corpus["signatures"] is sigs


def test_signatures_rebuilds_map_when_key_absent():
    corpus = {"schema": SCHEMA, "version": "1.0"}
    sigs = _signatures(corpus)
    assert sigs == {}
    assert isinstance(corpus["signatures"], dict)


def test_record_outcome_tolerates_missing_signatures_key():
    corpus = {"schema": SCHEMA, "version": "1.0"}
    record_outcome(corpus, "harden|is_hub", "applied")
    result = consult(corpus, "harden|is_hub")
    assert result["applied"] == 1
    assert result["samples"] == 1
    assert result["reliability"] == 1.0


def test_clamp_count_negative_becomes_zero():
    assert _clamp_count(-5) == 0
    assert _clamp_count(-1) == 0


def test_clamp_count_zero_and_small_positive_pass_through():
    assert _clamp_count(0) == 0
    assert _clamp_count(7) == 7
