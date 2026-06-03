from __future__ import annotations

from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase
from app.engine.roadmap_history import (
    diff_roadmaps,
    load_snapshot,
    render_diff_markdown,
    snapshot_roadmap,
)


def _item(title, phase, roi, subject="app/x.py"):
    return RoadmapItem(
        branch_path="x.a", title=title, subject=subject, phase=phase,
        impact=0.8, effort=round(0.8 / roi, 4), roi=roi, value=0.6,
        kind="permutation", rationale="r",
    )


def _roadmap(items_by_phase):
    phases = [RoadmapPhase(name=p, theme=p, items=its) for p, its in items_by_phase.items()]
    return Roadmap(objective="", project_root="/proj", phases=phases)


def test_snapshot_and_load_roundtrip(tmp_path):
    rm = _roadmap({"Stabilize": [_item("Test: app/a.py", "Stabilize", 5.0)]})
    path = tmp_path / ".apex" / "snap.json"
    snapshot_roadmap(rm, path)
    assert path.exists()
    loaded = load_snapshot(path)
    assert loaded and loaded["items"][0]["title"] == "Test: app/a.py"
    assert "generated" in loaded


def test_load_missing_returns_none(tmp_path):
    assert load_snapshot(tmp_path / "nope.json") is None


def test_diff_detects_new_and_dropped(tmp_path):
    prev = _roadmap({"Stabilize": [_item("Test: app/a.py", "Stabilize", 5.0)]})
    path = tmp_path / "snap.json"
    snapshot_roadmap(prev, path)
    previous = load_snapshot(path)

    curr = _roadmap({"Stabilize": [_item("Test: app/b.py", "Stabilize", 4.0)]})
    diff = diff_roadmaps(previous, curr)
    assert [c.title for c in diff.new] == ["Test: app/b.py"]
    assert [c.title for c in diff.dropped] == ["Test: app/a.py"]


def test_diff_detects_phase_move_and_roi_changes(tmp_path):
    prev = _roadmap({
        "Stabilize": [_item("Harden: app/a.py", "Stabilize", 5.0)],
        "Evolve": [_item("Extend: app/b.py", "Evolve", 2.0)],
        "Refine": [_item("Doc: app/c.py", "Refine", 1.0)],
    })
    path = tmp_path / "snap.json"
    snapshot_roadmap(prev, path)
    previous = load_snapshot(path)

    curr = _roadmap({
        "Secure": [_item("Harden: app/a.py", "Secure", 5.0)],     # phase moved
        "Evolve": [_item("Extend: app/b.py", "Evolve", 3.5)],     # ROI up
        "Refine": [_item("Doc: app/c.py", "Refine", 0.5)],        # ROI down
    })
    diff = diff_roadmaps(previous, curr)
    assert [c.title for c in diff.phase_moved] == ["Harden: app/a.py"]
    assert diff.phase_moved[0].prev_phase == "Stabilize"
    assert diff.phase_moved[0].curr_phase == "Secure"
    assert [c.title for c in diff.roi_improved] == ["Extend: app/b.py"]
    assert [c.title for c in diff.roi_regressed] == ["Doc: app/c.py"]


def test_diff_counts_stable(tmp_path):
    prev = _roadmap({"Stabilize": [_item("Test: app/a.py", "Stabilize", 5.0)]})
    path = tmp_path / "snap.json"
    snapshot_roadmap(prev, path)
    # Identical roadmap -> the item is stable, nothing else.
    diff = diff_roadmaps(load_snapshot(path), prev)
    assert diff.stable_count == 1
    assert not (diff.new or diff.dropped or diff.phase_moved)


def test_render_diff_markdown_sections(tmp_path):
    prev = _roadmap({"Stabilize": [_item("Test: app/a.py", "Stabilize", 5.0)]})
    path = tmp_path / "snap.json"
    snapshot_roadmap(prev, path)
    curr = _roadmap({"Stabilize": [_item("Test: app/b.py", "Stabilize", 4.0)]})
    md = render_diff_markdown(diff_roadmaps(load_snapshot(path), curr))
    assert "Roadmap Changes Since Last Run" in md
    assert "New ideas" in md
    assert "No longer surfaced" in md


def test_render_diff_no_changes(tmp_path):
    rm = _roadmap({"Stabilize": [_item("Test: app/a.py", "Stabilize", 5.0)]})
    path = tmp_path / "snap.json"
    snapshot_roadmap(rm, path)
    md = render_diff_markdown(diff_roadmaps(load_snapshot(path), rm))
    assert "No changes since the last snapshot" in md


def test_end_to_end_save_then_diff_via_engine(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def r(e):\n    return eval(e)\n")
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.engine.idea_roadmap import RoadmapSynthesizer

    rep = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run()
    rm = RoadmapSynthesizer().build(rep)
    path = tmp_path / ".apex" / "roadmap-snapshot.json"
    snapshot_roadmap(rm, path)

    # Add a module -> next run surfaces new ideas.
    (tmp_path / "app" / "feature.py").write_text("def feat(x):\n    return x + 1\n")
    rep2 = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run()
    rm2 = RoadmapSynthesizer().build(rep2)
    diff = diff_roadmaps(load_snapshot(path), rm2)
    assert any("feature.py" in c.title for c in diff.new)
