"""Tests for idea_memory's per-MODULE-CHARACTERISTIC learning dimension.

This second, finer learning dimension buckets outcomes by a coarse module trait
(hub / untested / security / complex / testfile) derived deterministically from
already-recorded context (the seeding ``label`` and the ``target`` path). It is
ADDITIVE and OPT-IN: with no recorded characteristic data the feasibility nudge
is byte-identical to the lens/label-only behaviour, and the combined nudge stays
inside the same bounded ±_MAX_NUDGE range.
"""

from __future__ import annotations

from app.engine.idea_memory import _MAX_NUDGE, IdeaMemory, _trait_key


def _summary(*results):
    return {"results": list(results)}


def _r(operator="", label="", target="", applied=False, rolled_back=False, blocked=False):
    return {"operator": operator, "label": label, "target": target,
            "applied": applied, "rolled_back": rolled_back, "blocked": blocked}


# --- trait-key derivation (pure, deterministic) ------------------------------

def test_trait_key_from_label():
    assert _trait_key("hub-untested") == "hub"          # most-specific wins
    assert _trait_key("sensitive-path") == "security"
    assert _trait_key("untested") == "untested"
    assert _trait_key("complexity-hotspot") == "complex"


def test_trait_key_from_target_when_no_label():
    assert _trait_key("", "tests/test_foo.py") == "testfile"
    assert _trait_key("", "app/sub/test_bar.py") == "testfile"


def test_trait_key_empty_when_nothing_matches():
    assert _trait_key("", "") == ""
    assert _trait_key("plain-thing", "app/svc.py") == ""


def test_trait_key_is_deterministic():
    for _ in range(5):
        assert _trait_key("a-central-dependency-hub", "app/core.py") == "hub"


# --- recording the characteristic dimension ----------------------------------

def test_characteristic_recorded_with_operator_and_trait():
    m = IdeaMemory()
    m.record_outcomes(_summary(
        _r(operator="harden", label="hub-untested", applied=True),
        _r(operator="harden", label="hub-untested", rolled_back=True),
    ))
    assert m.by_characteristic["harden@hub"].applied == 1
    assert m.by_characteristic["harden@hub"].rolled_back == 1


def test_characteristic_not_recorded_without_a_trait():
    m = IdeaMemory()
    # No label, app-code target -> no derivable trait -> nothing recorded.
    m.record_outcomes(_summary(_r(operator="harden", target="app/svc.py", applied=True)))
    assert m.by_characteristic == {}
    assert m.by_operator["harden"].applied == 1  # lens dimension still recorded


def test_characteristic_not_recorded_for_root():
    m = IdeaMemory()
    m.record_outcomes(_summary(_r(operator="root", label="hub-untested", applied=True)))
    assert m.by_characteristic == {}


def test_same_operator_splits_by_trait():
    m = IdeaMemory()
    # harden lands on leaves (testfile) but rolls back on hubs.
    m.record_outcomes(_summary(
        _r(operator="harden", target="tests/test_a.py", applied=True),
        _r(operator="harden", target="tests/test_b.py", applied=True),
        _r(operator="harden", label="dependency-hub", rolled_back=True),
        _r(operator="harden", label="dependency-hub", rolled_back=True),
    ))
    assert m.by_characteristic["harden@testfile"].applied == 2
    assert m.by_characteristic["harden@hub"].rolled_back == 2


# --- combined nudge: consulted, bounded, in-range ----------------------------

def test_characteristic_nudge_is_consulted():
    m = IdeaMemory()
    # Operator-level mixed (neutral-ish), but a strong hub track record.
    m.record_outcomes(_summary(
        _r(operator="harden", label="dependency-hub", rolled_back=True),
        _r(operator="harden", label="dependency-hub", rolled_back=True),
    ))
    # On a hub, the characteristic cell drags the factor below 1.0.
    f_hub = m.feasibility_factor("harden", label="dependency-hub")
    assert f_hub < 1.0


def test_characteristic_blend_stays_bounded():
    m = IdeaMemory()
    # Operator: all rollbacks (delta -MAX). Characteristic also all rollbacks.
    m.record_outcomes(_summary(
        _r(operator="harden", label="dependency-hub", rolled_back=True),
        _r(operator="harden", label="dependency-hub", rolled_back=True),
    ))
    f = m.feasibility_factor("harden", label="dependency-hub")
    # Averaging two equal deltas cannot exceed the single-delta bound.
    assert 1.0 - _MAX_NUDGE - 1e-9 <= f <= 1.0 + _MAX_NUDGE + 1e-9


def test_combined_factor_in_unit_range_for_extremes():
    m = IdeaMemory()
    m.record_outcomes(_summary(
        _r(operator="harden", label="hub-untested", applied=True),
        _r(operator="harden", label="hub-untested", applied=True),
    ))
    f = m.feasibility_factor("harden", label="hub-untested")
    # Even a maximally-positive blend keeps a typical feasibility in [0,1].
    nudged = min(1.0, max(0.0, 0.8 * f))
    assert 0.0 <= nudged <= 1.0


def test_explicit_characteristic_override():
    m = IdeaMemory()
    # Lens record is mixed/neutral (one applied, one rolled back) so any movement
    # in the factor comes solely from the characteristic dimension.
    m.record_outcomes(_summary(
        # Two clean lands on a testfile trait...
        _r(operator="harden", target="tests/test_a.py", applied=True),
        _r(operator="harden", target="tests/test_b.py", applied=True),
        # ...and two rollbacks on hubs. Lens = 2/4 = 0.5 (neutral); hub cell 0/2.
        _r(operator="harden", label="dependency-hub", rolled_back=True),
        _r(operator="harden", label="dependency-hub", rolled_back=True),
    ))
    # Lens-only (success 2/4 = 0.5) is neutral; characteristic forced off -> 1.0.
    assert m.feasibility_factor("harden", characteristic="") == 1.0
    # Passing the trait explicitly consults the (negative) hub cell.
    assert m.feasibility_factor("harden", characteristic="hub") < 1.0


# --- THE opt-in / byte-identical invariant -----------------------------------

def test_no_memory_file_is_byte_identical(tmp_path):
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.feasibility_factor("harden") == 1.0
    assert mem.feasibility_factor("harden", label="dependency-hub") == 1.0
    assert mem.feasibility_factor("harden", label="hub-untested", target="app/core.py") == 1.0


def test_no_characteristic_data_matches_lens_only():
    """With characteristic data absent, the combined nudge == the lens-only
    nudge for every key — the critical additive/opt-in proof."""
    lens = IdeaMemory()
    lens.record_outcomes(_summary(
        _r(operator="harden", applied=True), _r(operator="harden", applied=True),
        _r(operator="harden", rolled_back=True),
    ))
    # by_characteristic is empty (no label/target carried), so each lookup
    # must equal the historical lens-only formula exactly.
    s = lens.by_operator["harden"]
    expected = round(1.0 + (s.success_rate - 0.5) * 2.0 * _MAX_NUDGE, 4)
    assert lens.by_characteristic == {}
    assert lens.feasibility_factor("harden") == expected


def test_min_samples_gate_on_characteristic():
    m = IdeaMemory()
    m.record_outcomes(_summary(_r(operator="harden", label="dependency-hub", applied=True)))
    # 1 sample on the characteristic cell -> no opinion -> lens-only (neutral).
    assert m.feasibility_factor("harden", label="dependency-hub") == 1.0


# --- determinism -------------------------------------------------------------

def test_same_memory_same_nudge():
    def build():
        mm = IdeaMemory()
        mm.record_outcomes(_summary(
            _r(operator="harden", label="hub-untested", applied=True),
            _r(operator="harden", label="hub-untested", rolled_back=True),
            _r(operator="harden", label="hub-untested", applied=True),
        ))
        return mm
    a = build().feasibility_factor("harden", label="hub-untested")
    b = build().feasibility_factor("harden", label="hub-untested")
    assert a == b


# --- persistence round-trip --------------------------------------------------

def test_characteristic_persistence_round_trip(tmp_path):
    m = IdeaMemory()
    m.record_outcomes(_summary(
        _r(operator="harden", label="hub-untested", applied=True),
        _r(operator="harden", label="hub-untested", applied=True),
    ))
    m.save(str(tmp_path))
    reloaded = IdeaMemory.load(str(tmp_path))
    assert reloaded.by_characteristic["harden@hub"].applied == 2
    # And the reloaded memory yields the same nudge (determinism across I/O).
    assert (reloaded.feasibility_factor("harden", characteristic="hub")
            == m.feasibility_factor("harden", characteristic="hub"))


def test_old_memory_file_without_characteristic_loads(tmp_path):
    import json

    from app.engine.idea_memory import MEMORY_REL

    p = tmp_path / MEMORY_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"by_operator": {"test": {"applied": 3, "rolled_back": 0, "blocked": 0}}}),
                 encoding="utf-8")
    m = IdeaMemory.load(str(tmp_path))
    assert m.by_characteristic == {}
    assert m.by_operator["test"].applied == 3


# --- ranking / summary surfaces ----------------------------------------------

def test_summary_surfaces_characteristics():
    m = IdeaMemory()
    m.record_outcomes(_summary(
        _r(operator="harden", label="hub-untested", applied=True),
        _r(operator="harden", label="hub-untested", applied=True),
    ))
    s = m.summary()
    assert s["characteristics_tracked"] == 1
    assert s["reliable_characteristics"][0]["key"] == "harden@hub"


def test_confident_ranking_characteristic_table():
    m = IdeaMemory()
    m.record_outcomes(_summary(
        _r(operator="harden", label="hub-untested", applied=True),
        _r(operator="harden", label="hub-untested", applied=True),
    ))
    ranked = m.confident_ranking("characteristic", best=True)
    assert ranked and ranked[0]["key"] == "harden@hub"
