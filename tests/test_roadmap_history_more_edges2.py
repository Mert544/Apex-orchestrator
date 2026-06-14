from __future__ import annotations

from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase
from app.engine.roadmap_history import (
    RoadmapChange,
    diff_roadmaps,
    load_snapshot,
    render_diff_markdown,
    roadmap_to_snapshot,
    snapshot_roadmap,
)


def _item(title, phase, roi, subject="app/x.py", facts=None):
    return RoadmapItem(
        branch_path="x.a", title=title, subject=subject, phase=phase,
        impact=0.8, effort=round(0.8 / roi, 4), roi=roi, value=0.6,
        kind="permutation", rationale="r", source_facts=facts or [],
    )


def _roadmap(items_by_phase):
    phases = [RoadmapPhase(name=p, theme=p, items=its) for p, its in items_by_phase.items()]
    return Roadmap(objective="obj", project_root="/proj", phases=phases)


def test_diff_detects_phase_move():
    prev = _roadmap({"Stabilize": [_item("T: app/a.py", "Stabilize", 5.0)]})
    snap = roadmap_to_snapshot(prev)
    curr = _roadmap({"Evolve": [_item("T: app/a.py", "Evolve", 5.0)]})
    diff = diff_roadmaps(snap, curr)
    assert [c.title for c in diff.phase_moved] == ["T: app/a.py"]
    assert diff.phase_moved[0].prev_phase == "Stabilize"
    assert diff.phase_moved[0].curr_phase == "Evolve"
    assert diff.phase_moved[0].status == "phase_moved"


def test_diff_detects_roi_improved_and_regressed():
    prev = _roadmap({
        "Evolve": [
            _item("Up: app/a.py", "Evolve", 2.0),
            _item("Down: app/b.py", "Evolve", 5.0),
        ]
    })
    snap = roadmap_to_snapshot(prev)
    curr = _roadmap({
        "Evolve": [
            _item("Up: app/a.py", "Evolve", 3.0),    # +1.0 -> improved
            _item("Down: app/b.py", "Evolve", 4.0),  # -1.0 -> regressed
        ]
    })
    diff = diff_roadmaps(snap, curr)
    assert [c.title for c in diff.roi_improved] == ["Up: app/a.py"]
    assert diff.roi_improved[0].status == "roi_up"
    assert diff.roi_improved[0].roi_delta == 1.0
    assert [c.title for c in diff.roi_regressed] == ["Down: app/b.py"]
    assert diff.roi_regressed[0].status == "roi_down"
    assert diff.roi_regressed[0].roi_delta == -1.0


def test_snapshot_roadmap_writes_then_loads_round_trips(tmp_path):
    rm = _roadmap({"Stabilize": [_item("T: app/a.py", "Stabilize", 5.0,
                                        facts=["churn-hotspot: app/a.py"])]})
    path = tmp_path / "sub" / "snap.json"
    written = snapshot_roadmap(rm, path)
    assert written == path
    assert path.exists()
    loaded = load_snapshot(path)
    assert loaded is not None
    assert loaded["project_root"] == "/proj"
    assert loaded["items"][0]["grounded_in"] == "churn-hotspot: app/a.py"


def test_load_snapshot_missing_file_returns_none(tmp_path):
    assert load_snapshot(tmp_path / "nope.json") is None


def test_render_diff_groups_new_and_dropped_signals():
    prev = _roadmap({
        "Stabilize": [_item("Old: app/c.py", "Stabilize", 5.0,
                            facts=["dead-code: app/c.py"])]
    })
    snap = roadmap_to_snapshot(prev)
    curr = _roadmap({
        "Stabilize": [
            _item("New1: app/a.py", "Stabilize", 5.0, facts=["churn-hotspot: app/a.py"]),
            _item("New2: app/b.py", "Stabilize", 4.0, facts=["churn-hotspot: app/b.py"]),
        ]
    })
    diff = diff_roadmaps(snap, curr)
    md = render_diff_markdown(diff)
    # Two new ideas grounded in the same signal -> "×2" grouping.
    assert "`churn-hotspot` ×2" in md
    assert "Signals that stopped firing:" in md
    assert "`dead-code`" in md
    assert "🆕 New ideas" in md
    assert "✅ No longer surfaced" in md


def test_render_diff_no_changes_message():
    prev = _roadmap({"Evolve": [_item("Same: app/a.py", "Evolve", 2.0)]})
    snap = roadmap_to_snapshot(prev)
    curr = _roadmap({"Evolve": [_item("Same: app/a.py", "Evolve", 2.0)]})
    diff = diff_roadmaps(snap, curr)
    assert diff.stable_count == 1
    md = render_diff_markdown(diff)
    assert "_No changes since the last snapshot._" in md


def test_diff_previous_generated_passthrough_and_dropped_signal_line():
    prev = {
        "generated": "2020-01-01 00:00:00 UTC",
        "project_root": "/proj",
        "objective": "obj",
        "items": [{
            "title": "Gone: app/z.py", "subject": "app/z.py", "phase": "Refine",
            "roi": 3.0, "impact": 0.5, "effort": 0.2,
            "grounded_in": "complexity-spike: app/z.py",
        }],
    }
    curr = _roadmap({"Refine": []})
    diff = diff_roadmaps(prev, curr)
    assert diff.previous_generated == "2020-01-01 00:00:00 UTC"
    assert [c.title for c in diff.dropped] == ["Gone: app/z.py"]
    md = render_diff_markdown(diff)
    assert "compared against snapshot from 2020-01-01 00:00:00 UTC" in md
    assert "its `complexity-spike` signal no longer fires" in md


def test_roadmap_change_to_dict_shape():
    c = RoadmapChange(title="t", subject="s", status="new", curr_phase="Evolve",
                      curr_roi=4.0, grounded_in="churn-hotspot: app/a.py")
    d = c.to_dict()
    assert d["title"] == "t"
    assert d["status"] == "new"
    assert d["curr_phase"] == "Evolve"
    assert "grounded_in" in d
