from __future__ import annotations

import json

from app.engine.idea_memory import MEMORY_REL, IdeaMemory, _Stat


def _summary(*results):
    return {"results": list(results)}


def _r(operator="", label="", applied=False, rolled_back=False, blocked=False):
    return {"operator": operator, "label": label, "applied": applied,
            "rolled_back": rolled_back, "blocked": blocked}


# --- load() error / fallback paths (the 81-82 except branch) -----------------

def test_load_corrupt_json_returns_empty_memory(tmp_path):
    p = tmp_path / MEMORY_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", encoding="utf-8")
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_operator == {}
    assert mem.by_label == {}
    assert mem.by_sequence == {}


def test_load_when_path_is_a_directory_returns_empty(tmp_path):
    # Reading a directory raises OSError -> the except path returns a fresh memory.
    p = tmp_path / MEMORY_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir()  # the memory "file" is actually a directory
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_operator == {}


def test_load_explicit_path_override(tmp_path):
    custom = tmp_path / "custom-memory.json"
    custom.write_text(json.dumps(
        {"by_operator": {"test": {"applied": 2, "rolled_back": 0, "blocked": 0}}}),
        encoding="utf-8")
    mem = IdeaMemory.load(str(tmp_path), path=str(custom))
    assert mem.by_operator["test"].applied == 2


def test_load_null_tables_coalesce_to_empty(tmp_path):
    # Explicit nulls for the tables must coalesce to empty dicts, not crash.
    p = tmp_path / MEMORY_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"by_operator": None, "by_label": None, "by_sequence": None}), encoding="utf-8")
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_operator == {} and mem.by_label == {} and mem.by_sequence == {}


# --- save() creates the directory + explicit path ----------------------------

def test_save_creates_parent_directory(tmp_path):
    mem = IdeaMemory()
    mem.record_outcomes(_summary(_r(operator="harden", applied=True)))
    out = mem.save(str(tmp_path))
    assert out.exists()
    assert out == tmp_path / MEMORY_REL


def test_save_explicit_path(tmp_path):
    dest = tmp_path / "nested" / "mem.json"
    mem = IdeaMemory()
    out = mem.save(str(tmp_path), path=str(dest))
    assert out == dest and dest.exists()


# --- _Stat helpers -----------------------------------------------------------

def test_stat_total_and_success_rate_empty_is_zero():
    s = _Stat()
    assert s.total == 0
    assert s.success_rate == 0.0  # no division-by-zero on an empty stat


def test_stat_success_rate_partial():
    s = _Stat(applied=3, rolled_back=1, blocked=0)
    assert s.total == 4
    assert s.success_rate == 0.75


def test_stat_to_dict():
    assert _Stat(applied=1, rolled_back=2, blocked=3).to_dict() == {
        "applied": 1, "rolled_back": 2, "blocked": 3}


# --- record_outcomes degenerate inputs ---------------------------------------

def test_record_outcomes_handles_missing_results_key():
    mem = IdeaMemory()
    mem.record_outcomes({})  # no "results" key at all
    assert mem.by_operator == {} and mem.by_label == {}


def test_record_outcomes_handles_null_results():
    mem = IdeaMemory()
    mem.record_outcomes({"results": None})  # explicit None -> treated as empty
    assert mem.by_operator == {}


def test_record_outcomes_blocked_outcome_recorded():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(_r(operator="test", blocked=True)))
    assert mem.by_operator["test"].blocked == 1
    assert mem.by_operator["test"].applied == 0


def test_record_outcomes_empty_operator_and_label_skipped():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(_r()))  # no operator, no label
    assert mem.by_operator == {} and mem.by_label == {}


def test_record_outcomes_rolled_back_takes_precedence_over_blocked_when_not_applied():
    # applied is falsey, rolled_back truthy -> outcome is rolled_back, not blocked.
    mem = IdeaMemory()
    mem.record_outcomes(_summary(_r(operator="x", rolled_back=True)))
    assert mem.by_operator["x"].rolled_back == 1
    assert mem.by_operator["x"].blocked == 0


# --- feasibility_factor edge selection ---------------------------------------

def test_feasibility_factor_unknown_operator_falls_back_to_label():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="root", label="risky", applied=True),
        _r(operator="root", label="risky", rolled_back=True),
    ))
    # operator branch declines (root / unknown) -> label branch, 50% -> neutral.
    assert mem.feasibility_factor("root", "risky") == 1.0


def test_feasibility_factor_root_operator_ignored_even_if_present():
    mem = IdeaMemory()
    # Force a "root" key into by_operator directly; the factor must still ignore it.
    mem.by_operator["root"] = _Stat(applied=5, rolled_back=0)
    assert mem.feasibility_factor("root") == 1.0


def test_feasibility_factor_half_success_is_neutral():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="mix", applied=True), _r(operator="mix", rolled_back=True)))
    assert mem.feasibility_factor("mix") == 1.0  # 50% -> exactly 1.0


# --- sequence_factor edge cases ----------------------------------------------

def test_sequence_factor_empty_operator_neutral():
    mem = IdeaMemory()
    assert mem.sequence_factor("test", "") == 1.0
    assert mem.sequence_factor("", "harden") == 1.0


def test_sequence_factor_below_min_samples_neutral():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="a", applied=True), _r(operator="b", applied=True)))
    # only one sample for the pair a>b -> neutral until _MIN_SAMPLES reached.
    assert mem.sequence_factor("a", "b") == 1.0


# --- summary() shaping --------------------------------------------------------

def test_summary_empty_memory():
    s = IdeaMemory().summary()
    assert s["operators_tracked"] == 0
    assert s["most_reliable"] == []
    assert s["least_reliable"] == []
    assert s["reliable_sequences"] == []


def test_summary_omits_under_sampled_keys():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(_r(operator="lonely", applied=True)))  # 1 sample
    s = mem.summary()
    assert s["operators_tracked"] == 1  # tracked...
    assert s["most_reliable"] == []     # ...but not ranked (under _MIN_SAMPLES)


def test_summary_caps_top_lists_at_five():
    mem = IdeaMemory()
    for i in range(7):
        op = f"op{i}"
        mem.record_outcomes(_summary(_r(operator=op, applied=True),
                                     _r(operator=op, applied=True)))
    s = mem.summary()
    assert len(s["most_reliable"]) == 5  # top-5 only


# --- learn_from with explicit path -------------------------------------------

def test_learn_from_explicit_path_roundtrip(tmp_path):
    dest = tmp_path / "seq.json"
    IdeaMemory.learn_from(_summary(
        _r(operator="a", applied=True), _r(operator="b", applied=True)),
        str(tmp_path), path=str(dest))
    reloaded = IdeaMemory.load(str(tmp_path), path=str(dest))
    assert reloaded.by_sequence["a>b"].applied == 1
