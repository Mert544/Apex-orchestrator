"""Cross-project knowledge corpus — signature, fold/merge/consult, IO tolerance."""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.knowledge_corpus import (
    SCHEMA,
    SCHEMA_VERSION,
    code_shape_signature,
    consult,
    load_corpus,
    merge_run,
    new_corpus,
    record_outcome,
    save_corpus,
)

# --- code_shape_signature: stability + canonicalisation --------------------


def test_signature_is_deterministic_for_same_features():
    feats = {"action_type": "harden", "is_hub": True, "is_untested": True}
    assert code_shape_signature(feats) == code_shape_signature(dict(feats))


def test_signature_canonical_regardless_of_dict_order():
    a = {"action_type": "harden", "is_hub": True, "is_untested": True}
    b = {"is_untested": True, "is_hub": True, "action_type": "harden"}
    assert code_shape_signature(a) == code_shape_signature(b)


def test_signature_sorts_shape_tokens():
    sig = code_shape_signature(
        {"action_type": "fix", "is_untested": True, "is_hub": True, "is_large": True}
    )
    # action token, then sorted shape tokens.
    assert sig == "fix|is_hub,is_large,is_untested"


def test_signature_only_lists_true_flags():
    sig = code_shape_signature({"action_type": "test", "is_hub": False, "is_large": True})
    assert sig == "test|is_large"


def test_signature_canonicalises_action_casing_and_whitespace():
    a = code_shape_signature({"action_type": "Harden", "is_hub": True})
    b = code_shape_signature({"action_type": " harden ", "is_hub": True})
    assert a == b == "harden|is_hub"


def test_signature_coerces_loose_truthiness():
    a = code_shape_signature({"action_type": "x", "is_hub": 1, "is_large": "true"})
    b = code_shape_signature({"action_type": "x", "is_hub": True, "is_large": True})
    assert a == b


def test_signature_missing_action_uses_placeholder():
    assert code_shape_signature({"is_hub": True}) == "unknown|is_hub"


def test_signature_no_flags_is_action_only():
    assert code_shape_signature({"action_type": "refactor"}) == "refactor|"


def test_signature_empty_features():
    assert code_shape_signature({}) == "unknown|"


# --- record_outcome ---------------------------------------------------------


def test_record_outcome_accumulates():
    c = new_corpus()
    record_outcome(c, "harden|is_hub", "applied")
    record_outcome(c, "harden|is_hub", "applied")
    record_outcome(c, "harden|is_hub", "rolled_back")
    res = consult(c, "harden|is_hub")
    assert res["applied"] == 2
    assert res["rolled_back"] == 1
    assert res["samples"] == 3


def test_record_outcome_unknown_folds_to_blocked():
    c = new_corpus()
    record_outcome(c, "s", "exploded")
    assert consult(c, "s")["blocked"] == 1


def test_record_outcome_returns_corpus_for_chaining():
    c = new_corpus()
    assert record_outcome(c, "s", "applied") is c


# --- merge_run --------------------------------------------------------------


def _summary(by_action: dict) -> dict:
    return {"by_action": by_action, "by_module": {}}


def test_merge_run_ingests_by_action():
    c = new_corpus()
    merge_run(c, _summary({
        "harden|is_hub": {"applied": 3, "rolled_back": 1, "blocked": 0, "total": 4},
    }))
    res = consult(c, "harden|is_hub")
    assert res["applied"] == 3
    assert res["rolled_back"] == 1
    assert res["samples"] == 4


def test_merge_run_accumulates_across_projects():
    c = new_corpus()
    merge_run(c, _summary({"sig": {"applied": 2, "rolled_back": 0, "blocked": 0}}))
    merge_run(c, _summary({"sig": {"applied": 1, "rolled_back": 1, "blocked": 0}}))
    res = consult(c, "sig")
    assert res["applied"] == 3
    assert res["rolled_back"] == 1
    assert res["samples"] == 4


def test_merge_run_is_commutative():
    a = merge_run(new_corpus(), _summary({"s": {"applied": 5, "blocked": 1}}))
    a = merge_run(a, _summary({"s": {"applied": 1, "rolled_back": 2}}))
    b = merge_run(new_corpus(), _summary({"s": {"applied": 1, "rolled_back": 2}}))
    b = merge_run(b, _summary({"s": {"applied": 5, "blocked": 1}}))
    assert consult(a, "s") == consult(b, "s")


def test_merge_run_tolerant_of_malformed():
    c = new_corpus()
    assert merge_run(c, {}) is c
    assert merge_run(c, {"by_action": "nope"}) is c
    merge_run(c, {"by_action": {"s": "notdict", "t": {"applied": 1}}})
    assert consult(c, "t")["applied"] == 1
    assert consult(c, "s")["samples"] == 0


def test_merge_run_none_summary():
    c = new_corpus()
    merge_run(c, None)
    assert c["signatures"] == {}


# --- consult: bounded + neutral --------------------------------------------


def test_consult_reliability_bounded_zero_to_one():
    c = new_corpus()
    for _ in range(7):
        record_outcome(c, "s", "applied")
    for _ in range(3):
        record_outcome(c, "s", "rolled_back")
    res = consult(c, "s")
    assert 0.0 <= res["reliability"] <= 1.0
    assert res["reliability"] == 0.7
    assert res["samples"] == 10


def test_consult_empty_corpus_is_neutral():
    res = consult(new_corpus(), "anything")
    assert res["reliability"] == 0.0
    assert res["samples"] == 0


def test_consult_unknown_signature_is_neutral():
    c = new_corpus()
    record_outcome(c, "known", "applied")
    res = consult(c, "missing")
    assert res["reliability"] == 0.0
    assert res["samples"] == 0


def test_consult_all_applied_is_one():
    c = new_corpus()
    record_outcome(c, "s", "applied")
    assert consult(c, "s")["reliability"] == 1.0


def test_consult_all_blocked_is_zero_reliability_but_has_samples():
    c = new_corpus()
    record_outcome(c, "s", "blocked")
    res = consult(c, "s")
    assert res["reliability"] == 0.0
    assert res["samples"] == 1


# --- determinism: byte-identical JSON --------------------------------------


def test_save_is_byte_identical_for_same_corpus(tmp_path: Path):
    c = new_corpus()
    record_outcome(c, "b|is_hub", "applied")
    record_outcome(c, "a|is_large", "rolled_back")
    p1 = tmp_path / "c1.json"
    p2 = tmp_path / "c2.json"
    save_corpus(c, p1)
    save_corpus(c, p2)
    assert p1.read_bytes() == p2.read_bytes()


def test_save_independent_of_insertion_order(tmp_path: Path):
    c1 = new_corpus()
    record_outcome(c1, "z", "applied")
    record_outcome(c1, "a", "blocked")
    c2 = new_corpus()
    record_outcome(c2, "a", "blocked")
    record_outcome(c2, "z", "applied")
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    save_corpus(c1, p1)
    save_corpus(c2, p2)
    assert p1.read_bytes() == p2.read_bytes()


def test_saved_json_is_sorted(tmp_path: Path):
    c = new_corpus()
    record_outcome(c, "zeta", "applied")
    record_outcome(c, "alpha", "applied")
    p = tmp_path / "c.json"
    save_corpus(c, p)
    data = json.loads(p.read_text())
    assert list(data["signatures"].keys()) == ["alpha", "zeta"]
    assert data["schema"] == SCHEMA
    assert data["version"] == SCHEMA_VERSION


# --- tolerant load + round-trip --------------------------------------------


def test_load_missing_file_is_empty(tmp_path: Path):
    c = load_corpus(tmp_path / "nope.json")
    assert c == new_corpus()
    assert consult(c, "x")["samples"] == 0


def test_load_malformed_json_is_empty(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_corpus(p) == new_corpus()


def test_load_wrong_schema_is_empty(tmp_path: Path):
    p = tmp_path / "wrong.json"
    p.write_text(json.dumps({"schema": "other", "signatures": {"s": {"applied": 9}}}))
    c = load_corpus(p)
    assert c == new_corpus()
    assert consult(c, "s")["samples"] == 0


def test_load_clamps_out_of_bound_counts(tmp_path: Path):
    p = tmp_path / "huge.json"
    p.write_text(json.dumps({
        "schema": SCHEMA, "version": SCHEMA_VERSION,
        "signatures": {"s": {"applied": 10 ** 12, "rolled_back": -5, "blocked": 0}},
    }))
    res = consult(load_corpus(p), "s")
    assert res["applied"] == 1_000_000
    assert res["rolled_back"] == 0


def test_round_trip_save_load(tmp_path: Path):
    c = new_corpus()
    merge_run(c, _summary({
        "harden|is_hub": {"applied": 4, "rolled_back": 1, "blocked": 1},
        "test|is_untested": {"applied": 2, "rolled_back": 0, "blocked": 0},
    }))
    p = tmp_path / "corpus.json"
    save_corpus(c, p)
    loaded = load_corpus(p)
    assert consult(loaded, "harden|is_hub") == consult(c, "harden|is_hub")
    assert consult(loaded, "test|is_untested")["reliability"] == 1.0


def test_round_trip_is_idempotent(tmp_path: Path):
    c = new_corpus()
    record_outcome(c, "s|is_hub", "applied")
    p = tmp_path / "c.json"
    save_corpus(c, p)
    once = p.read_bytes()
    save_corpus(load_corpus(p), p)
    assert p.read_bytes() == once


# --- end-to-end: signature → record → consult ------------------------------


def test_signature_drives_global_learning(tmp_path: Path):
    # Two different "projects" both hardened an untested hub: same signature,
    # so the corpus aggregates their evidence GLOBALLY.
    sig = code_shape_signature(
        {"action_type": "harden", "is_hub": True, "is_untested": True}
    )
    c = new_corpus()
    record_outcome(c, sig, "applied")   # project A landed it
    record_outcome(c, sig, "rolled_back")  # project B rolled back
    record_outcome(c, sig, "applied")   # project C landed it
    res = consult(c, sig)
    assert res["samples"] == 3
    assert res["reliability"] == round(2 / 3, 4)
