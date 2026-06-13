from __future__ import annotations

import json

from app.engine.dev_history import (
    DevHistory,
    DevRun,
    record_run,
    render_history_markdown,
)


def _run(date="2026-06-13", objective="modernize", moves=3,
         grade_before=70, grade_after=80):
    return DevRun(date=date, objective=objective, moves=moves,
                  grade_before=grade_before, grade_after=grade_after)


def test_devrun_delta_and_to_dict():
    r = _run(grade_before=60, grade_after=75)
    assert r.delta == 15
    assert r.to_dict() == {
        "date": "2026-06-13", "objective": "modernize", "moves": 3,
        "grade_before": 60, "grade_after": 75,
    }


def test_record_run_persists_when_moves_positive(tmp_path):
    assert record_run(tmp_path, "modernize", 2, 70, 78) is True
    loaded = DevHistory.load(tmp_path)
    assert len(loaded.entries()) == 1
    run = loaded.entries()[0]
    assert run.objective == "modernize"
    assert run.moves == 2
    assert run.delta == 8


def test_record_run_skips_zero_moves(tmp_path):
    assert record_run(tmp_path, "noop", 0, 70, 70) is False
    assert DevHistory.load(tmp_path).entries() == []


def test_total_gain_sums_deltas():
    h = DevHistory()
    h.record(_run(grade_before=50, grade_after=60))  # +10
    h.record(_run(grade_before=60, grade_after=58))  # -2
    h.record(_run(grade_before=58, grade_after=70))  # +12
    assert h.total_gain() == 20


def test_save_load_roundtrip(tmp_path):
    h = DevHistory()
    h.record(_run(objective="a", moves=1, grade_before=40, grade_after=45))
    h.record(_run(objective="b", moves=4, grade_before=45, grade_after=60))
    h.save(tmp_path)
    loaded = DevHistory.load(tmp_path)
    assert loaded.to_dict() == h.to_dict()
    assert [r.objective for r in loaded.entries()] == ["a", "b"]


def test_missing_file_loads_empty(tmp_path):
    assert DevHistory.load(tmp_path).entries() == []
    assert DevHistory.load(tmp_path).total_gain() == 0


def test_corrupt_json_loads_empty(tmp_path):
    p = tmp_path / ".apex" / "dev-history.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not valid json", encoding="utf-8")
    assert DevHistory.load(tmp_path).entries() == []


def test_malformed_run_entries_skipped(tmp_path):
    p = tmp_path / ".apex" / "dev-history.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"runs": [
        {"date": "2026-06-13", "objective": "ok", "moves": 1,
         "grade_before": 1, "grade_after": 2},
        {"date": "2026-06-13"},  # missing fields -> skipped
        "not-a-dict",
    ]}), encoding="utf-8")
    loaded = DevHistory.load(tmp_path)
    assert len(loaded.entries()) == 1
    assert loaded.entries()[0].objective == "ok"


def test_render_history_shows_runs_and_total():
    h = DevHistory()
    h.record(_run(objective="modernize", moves=2, grade_before=70, grade_after=80))
    h.record(_run(objective="harden", moves=3, grade_before=80, grade_after=88))
    md = render_history_markdown(h)
    assert "modernize" in md
    assert "harden" in md
    assert "70→80" in md
    assert "+18" in md  # total gain headline
    assert "+8" in md   # per-run deltas
    assert "+10" in md


def test_render_history_empty_is_clean():
    md = render_history_markdown(DevHistory())
    assert "no development campaigns recorded yet" in md.lower()
    assert "|" not in md  # no table


def test_render_history_negative_total():
    h = DevHistory()
    h.record(_run(grade_before=80, grade_after=70))  # -10
    md = render_history_markdown(h)
    assert "-10" in md


def test_determinism_identical_sequences(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    seq = [("modernize", 2, 70, 78), ("harden", 1, 78, 80)]
    for obj, moves, gb, ga in seq:
        record_run(root_a, obj, moves, gb, ga)
        record_run(root_b, obj, moves, gb, ga)
    assert DevHistory.load(root_a).to_dict() == DevHistory.load(root_b).to_dict()
