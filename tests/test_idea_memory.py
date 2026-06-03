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
