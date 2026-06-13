from __future__ import annotations

from app.engine.idea_memory import IdeaMemory


def _summary(*results):
    return {"results": list(results)}


def _r(operator="", label="", applied=False, rolled_back=False):
    return {"operator": operator, "label": label, "applied": applied, "rolled_back": rolled_back}


def test_record_and_persist_roundtrip(tmp_path):
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="harden", applied=True),
        _r(operator="harden", rolled_back=True),
        _r(operator="test", applied=True),
    ))
    mem.save(str(tmp_path))
    reloaded = IdeaMemory.load(str(tmp_path))
    assert reloaded.by_operator["harden"].applied == 1
    assert reloaded.by_operator["harden"].rolled_back == 1
    assert reloaded.by_operator["test"].applied == 1


def test_missing_memory_is_neutral(tmp_path):
    mem = IdeaMemory.load(str(tmp_path))
    # No file -> empty -> neutral factor for everything.
    assert mem.feasibility_factor("harden") == 1.0
    assert mem.feasibility_factor("test", "untested") == 1.0


def test_feasibility_factor_rewards_success(tmp_path):
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="harden", applied=True), _r(operator="harden", applied=True),
        _r(operator="harden", applied=True),
    ))
    # 100% success -> factor at the +10% ceiling.
    assert mem.feasibility_factor("harden") == 1.10


def test_feasibility_factor_penalizes_failure(tmp_path):
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="test", rolled_back=True), _r(operator="test", rolled_back=True),
    ))
    # 0% success -> factor at the -10% floor.
    assert mem.feasibility_factor("test") == 0.90


def test_min_samples_gate(tmp_path):
    mem = IdeaMemory()
    mem.record_outcomes(_summary(_r(operator="harden", applied=True)))  # 1 sample only
    assert mem.feasibility_factor("harden") == 1.0  # not enough data yet


def test_root_keyed_by_label():
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="root", label="sensitive-path", applied=True),
        _r(operator="root", label="sensitive-path", applied=True),
    ))
    # roots don't record under operator "root"; they learn by label.
    assert "root" not in mem.by_operator
    assert mem.feasibility_factor("root", "sensitive-path") == 1.10


def test_learn_from_loads_records_saves(tmp_path):
    IdeaMemory.learn_from(_summary(_r(operator="harden", applied=True)), str(tmp_path))
    IdeaMemory.learn_from(_summary(_r(operator="harden", applied=True)), str(tmp_path))
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_operator["harden"].applied == 2  # accumulated across calls


def test_summary_ranks_reliability(tmp_path):
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="harden", applied=True), _r(operator="harden", applied=True),
        _r(operator="test", rolled_back=True), _r(operator="test", rolled_back=True),
    ))
    s = mem.summary()
    assert s["operators_tracked"] == 2
    assert s["most_reliable"][0]["key"] == "harden"
    assert s["least_reliable"][0]["key"] == "test"


def test_engine_applies_learned_nudge(tmp_path):
    # With a memory that loves 'harden', harden ideas score at least as high as
    # they would with no memory (feasibility nudged up, clamped).
    from app.engine.idea_permutation import IdeaPermutationEngine

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("import os\ndef r(c):\n    return eval(c)\n")
    cfg = {"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 4}

    base = IdeaPermutationEngine({**cfg, "learning": False}, tmp_path).run()
    base_harden = [i.value for i in base.ideas if i.operator == "harden"]

    IdeaMemory(by_operator={}).save(str(tmp_path))  # ensure dir
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="harden", applied=True), _r(operator="harden", applied=True),
    ))
    mem.save(str(tmp_path))
    learned = IdeaPermutationEngine(cfg, tmp_path).run()
    learned_harden = [i.value for i in learned.ideas if i.operator == "harden"]

    assert base_harden and learned_harden
    assert max(learned_harden) >= max(base_harden)


# --- composition / sequence memory (credit assignment over orderings) --------

def test_sequence_recorded_only_after_a_landed_step():
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    # test landed, then harden landed → the pair test>harden is credited.
    m.record_outcomes({"results": [
        {"operator": "test", "applied": True},
        {"operator": "harden", "applied": True},
    ]})
    assert "test>harden" in m.by_sequence
    assert m.by_sequence["test>harden"].applied == 1


def test_sequence_not_recorded_when_first_step_did_not_land():
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    # test BLOCKED, then harden ran — no composition (test changed nothing).
    m.record_outcomes({"results": [
        {"operator": "test", "blocked": True},
        {"operator": "harden", "applied": True},
    ]})
    assert m.by_sequence == {}


def test_sequence_records_second_step_outcome():
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    m.record_outcomes({"results": [
        {"operator": "test", "applied": True},
        {"operator": "harden", "blocked": True},
    ]})
    assert m.by_sequence["test>harden"].blocked == 1
    assert m.by_sequence["test>harden"].applied == 0


def test_root_steps_break_the_chain():
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    # A root step (operator "root") is not a development operator and must not
    # participate in a composition pair.
    m.record_outcomes({"results": [
        {"operator": "test", "applied": True},
        {"operator": "root", "applied": True},
        {"operator": "harden", "applied": True},
    ]})
    # test>root and root>harden must NOT exist; test>harden is not adjacent.
    assert "root" not in "".join(m.by_sequence.keys())
    # The chain resumes from the last real operator (test) to harden.
    assert "test>harden" in m.by_sequence


def test_sequence_factor_bounds_and_neutrality():
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    # No prior operator → neutral.
    assert m.sequence_factor("", "harden") == 1.0
    # Unknown pair → neutral.
    assert m.sequence_factor("test", "harden") == 1.0
    # Two clean landings → positive nudge, bounded by +10%.
    for _ in range(2):
        m.record_outcomes({"results": [
            {"operator": "test", "applied": True},
            {"operator": "harden", "applied": True},
        ]})
    f = m.sequence_factor("test", "harden")
    assert 1.0 < f <= 1.10
    # A consistently blocking pair drops below 1.0, bounded by -10%.
    bad = IdeaMemory()
    for _ in range(2):
        bad.record_outcomes({"results": [
            {"operator": "simplify", "applied": True},
            {"operator": "harden", "blocked": True},
        ]})
    fb = bad.sequence_factor("simplify", "harden")
    assert 0.90 <= fb < 1.0


def test_sequence_persistence_round_trip(tmp_path):
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    m.record_outcomes({"results": [
        {"operator": "test", "applied": True},
        {"operator": "harden", "applied": True},
    ]})
    m.save(str(tmp_path))
    reloaded = IdeaMemory.load(str(tmp_path))
    assert reloaded.by_sequence["test>harden"].applied == 1


def test_old_memory_file_without_sequence_loads(tmp_path):
    # Backward compatibility: a pre-existing memory file with no by_sequence key
    # must load cleanly with an empty sequence table.
    import json
    from app.engine.idea_memory import MEMORY_REL, IdeaMemory

    p = tmp_path / MEMORY_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"by_operator": {"test": {"applied": 3, "rolled_back": 0, "blocked": 0}}}),
                 encoding="utf-8")
    m = IdeaMemory.load(str(tmp_path))
    assert m.by_sequence == {}
    assert m.by_operator["test"].applied == 3


def test_summary_includes_reliable_sequences():
    from app.engine.idea_memory import IdeaMemory

    m = IdeaMemory()
    for _ in range(2):
        m.record_outcomes({"results": [
            {"operator": "test", "applied": True},
            {"operator": "harden", "applied": True},
        ]})
    s = m.summary()
    assert s["sequences_tracked"] == 1
    assert s["reliable_sequences"] and s["reliable_sequences"][0]["key"] == "test>harden"
