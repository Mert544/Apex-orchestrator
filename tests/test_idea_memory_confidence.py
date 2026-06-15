from __future__ import annotations

from app.engine.idea_memory import IdeaMemory


def _summary(*results):
    return {"results": list(results)}


def _r(operator="", label="", applied=False, rolled_back=False, blocked=False):
    return {"operator": operator, "label": label, "applied": applied,
            "rolled_back": rolled_back, "blocked": blocked}


def _apply(mem, operator, applied=0, failed=0):
    rows = []
    for _ in range(applied):
        rows.append(_r(operator=operator, applied=True))
    for _ in range(failed):
        rows.append(_r(operator=operator, rolled_back=True))
    # Record each row independently so no spurious sequence credit accrues
    # (a single-step summary never forms an adjacent operator pair here since
    # all rows share one operator — but keep them isolated for clarity).
    for row in rows:
        mem.record_outcomes(_summary(row))


def test_high_sample_90_outranks_lucky_1_of_1():
    mem = IdeaMemory()
    _apply(mem, "lucky", applied=1)            # 1-of-1 -> 100%, 1 sample
    _apply(mem, "proven", applied=9, failed=1)  # 9-of-10 -> 90%, 10 samples

    # Raw success_rate would rank the lucky 1-of-1 first.
    assert mem.by_operator["lucky"].success_rate > mem.by_operator["proven"].success_rate
    # Confidence (Wilson lower bound) ranks the well-attested 90% first.
    assert mem.by_operator["proven"].confidence > mem.by_operator["lucky"].confidence

    ranking = mem.confident_ranking("operator", best=True)
    # The 1-sample key is below _MIN_SAMPLES and excluded entirely.
    keys = [r["key"] for r in ranking]
    assert keys[0] == "proven"
    assert "lucky" not in keys


def test_more_evidence_at_same_rate_raises_confidence():
    small = IdeaMemory()
    big = IdeaMemory()
    _apply(small, "x", applied=2)            # 2-of-2, 100%
    _apply(big, "x", applied=20)             # 20-of-20, 100%
    assert small.by_operator["x"].success_rate == big.by_operator["x"].success_rate == 1.0
    assert big.by_operator["x"].confidence > small.by_operator["x"].confidence


def test_empty_memory_is_safe():
    mem = IdeaMemory()
    assert mem.confident_ranking("operator") == []
    assert mem.confident_ranking("label") == []
    assert mem.confident_ranking("sequence") == []
    assert mem.confident_ranking("operator", best=False) == []
    # Zero-sample stat confidence is 0.0, never a division error.
    from app.engine.idea_memory import _Stat
    assert _Stat().confidence == 0.0
    # summary on empty memory still exposes the new additive keys, empty.
    s = mem.summary()
    assert s["most_confident"] == []
    assert s["least_confident"] == []


def test_existing_summary_keys_intact():
    mem = IdeaMemory()
    _apply(mem, "harden", applied=2)
    s = mem.summary()
    for key in ("operators_tracked", "labels_tracked", "sequences_tracked",
                "most_reliable", "least_reliable", "reliable_sequences"):
        assert key in s
    # New additive keys present too.
    assert "most_confident" in s and "least_confident" in s


def test_determinism_twice_and_compare():
    def build():
        m = IdeaMemory()
        _apply(m, "proven", applied=9, failed=1)
        _apply(m, "alpha", applied=4, failed=1)
        _apply(m, "beta", applied=4, failed=1)  # ties alpha on rate+samples
        return m

    a = build().confident_ranking("operator", best=True)
    b = build().confident_ranking("operator", best=True)
    assert a == b
    # Stable key tiebreak: alpha before beta (same rate, same samples).
    keys = [r["key"] for r in a]
    assert keys.index("alpha") < keys.index("beta")


def test_least_confident_is_reverse_friendly():
    mem = IdeaMemory()
    _apply(mem, "good", applied=9, failed=1)
    _apply(mem, "bad", applied=2, failed=8)
    best = mem.confident_ranking("operator", best=True)
    worst = mem.confident_ranking("operator", best=False)
    assert best[0]["key"] == "good"
    assert worst[0]["key"] == "bad"


def test_min_samples_gate_excludes_one_sample():
    mem = IdeaMemory()
    _apply(mem, "single", applied=1)
    assert mem.confident_ranking("operator") == []


def test_persisted_round_trip_preserves_confidence(tmp_path):
    mem = IdeaMemory()
    _apply(mem, "proven", applied=9, failed=1)
    before = mem.confident_ranking("operator")
    mem.save(str(tmp_path))
    reloaded = IdeaMemory.load(str(tmp_path))
    after = reloaded.confident_ranking("operator")
    assert before == after
    assert after[0]["key"] == "proven"
    assert 0.0 < after[0]["confidence"] < 0.9


def test_sequence_table_ranking():
    mem = IdeaMemory()
    for _ in range(3):
        mem.record_outcomes(_summary(
            _r(operator="test", applied=True),
            _r(operator="harden", applied=True),
        ))
    ranking = mem.confident_ranking("sequence", best=True)
    assert ranking and ranking[0]["key"] == "test>harden"
