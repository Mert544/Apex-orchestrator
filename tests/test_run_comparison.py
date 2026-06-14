from __future__ import annotations

import json
from pathlib import Path

from app.engine.run_comparison import RunComparison, RunSnapshot


def _comp(tmp_path: Path) -> RunComparison:
    return RunComparison(project_root=str(tmp_path), log_dir=str(tmp_path / ".apex"))


def test_snapshot_to_dict_roundtrip():
    snap = RunSnapshot(
        run_id="r1",
        timestamp="2020-01-01T00:00:00",
        mode="supervised",
        goal="fix bugs",
        findings_count=3,
        patches_applied=2,
        patches_blocked=1,
        tests_passed=True,
        duration_seconds=4.5,
        safety_gates_passed=True,
        autonomy_level="auto",
        errors=["boom"],
        warnings=["careful"],
    )
    d = snap.to_dict()
    assert d["run_id"] == "r1"
    assert d["errors"] == ["boom"]
    assert d["warnings"] == ["careful"]
    # Reconstructing from the dict yields an equal snapshot.
    assert RunSnapshot(**d) == snap


def test_record_run_persists_and_defaults(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(run_id="run-1", mode="report", goal="scan")

    # File written.
    data = json.loads((tmp_path / ".apex" / "run_history.json").read_text(encoding="utf-8"))
    assert data["version"] == "2.0"
    assert len(data["runs"]) == 1
    rec = data["runs"][0]
    assert rec["run_id"] == "run-1"
    # Defaults applied for optional lists.
    assert rec["errors"] == []
    assert rec["warnings"] == []
    assert rec["tests_passed"] is True


def test_record_run_caps_at_100(tmp_path: Path):
    comp = _comp(tmp_path)
    for i in range(105):
        comp.record_run(run_id=f"run-{i}", mode="report", goal="scan")
    assert len(comp.runs) == 100
    # Oldest five dropped; most recent retained.
    assert comp.runs[0].run_id == "run-5"
    assert comp.runs[-1].run_id == "run-104"


def test_load_existing_history(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(run_id="run-a", mode="report", goal="scan")

    # New instance reading the same file picks up the prior run.
    comp2 = _comp(tmp_path)
    assert len(comp2.runs) == 1
    assert comp2.runs[0].run_id == "run-a"


def test_load_corrupt_history_resets_to_empty(tmp_path: Path):
    log_path = tmp_path / ".apex" / "run_history.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("{ not valid json", encoding="utf-8")

    comp = _comp(tmp_path)
    assert comp.runs == []


def test_compare_recent_empty_returns_error(tmp_path: Path):
    comp = _comp(tmp_path)
    assert comp.compare_recent() == {"error": "No runs to compare"}


def test_compare_recent_aggregates_summary(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(
        run_id="r1", mode="m", goal="g",
        patches_applied=2, patches_blocked=1,
        tests_passed=True, duration_seconds=2.0, safety_gates_passed=True,
    )
    comp.record_run(
        run_id="r2", mode="m", goal="g",
        patches_applied=4, patches_blocked=0,
        tests_passed=False, duration_seconds=4.0, safety_gates_passed=False,
    )
    report = comp.compare_recent(n=5)
    assert report["runs_compared"] == 2
    summary = report["summary"]
    assert summary["avg_duration_seconds"] == 3.0
    assert summary["total_patches_applied"] == 6
    assert summary["total_patches_blocked"] == 1
    assert summary["test_pass_rate"] == 50.0
    assert summary["safety_gate_pass_rate"] == 50.0
    assert len(report["runs"]) == 2
    assert report["date_range"]["start"] == comp.runs[0].timestamp
    assert report["date_range"]["end"] == comp.runs[-1].timestamp


def test_compare_recent_limits_window(tmp_path: Path):
    comp = _comp(tmp_path)
    for i in range(6):
        comp.record_run(run_id=f"r{i}", mode="m", goal="g", patches_applied=1)
    report = comp.compare_recent(n=3)
    assert report["runs_compared"] == 3
    returned_ids = [r["run_id"] for r in report["runs"]]
    assert returned_ids == ["r3", "r4", "r5"]


def test_trend_insufficient_data_single_run(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(run_id="r1", mode="m", goal="g", patches_applied=1)
    report = comp.compare_recent(n=5)
    assert report["trend"] == {
        "patches": "insufficient_data",
        "tests": "insufficient_data",
    }


def test_trend_increasing_and_improving(tmp_path: Path):
    comp = _comp(tmp_path)
    # First half: low patches, failing tests; second half: higher patches, passing tests.
    comp.record_run(run_id="r1", mode="m", goal="g", patches_applied=0, tests_passed=False)
    comp.record_run(run_id="r2", mode="m", goal="g", patches_applied=5, tests_passed=True)
    trend = comp.compare_recent(n=2)["trend"]
    assert trend["patches"] == "increasing"
    assert trend["tests"] == "improving"


def test_trend_decreasing_and_declining(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(run_id="r1", mode="m", goal="g", patches_applied=5, tests_passed=True)
    comp.record_run(run_id="r2", mode="m", goal="g", patches_applied=0, tests_passed=False)
    trend = comp.compare_recent(n=2)["trend"]
    assert trend["patches"] == "decreasing"
    assert trend["tests"] == "declining"


def test_trend_stable_when_equal(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(run_id="r1", mode="m", goal="g", patches_applied=2, tests_passed=True)
    comp.record_run(run_id="r2", mode="m", goal="g", patches_applied=2, tests_passed=True)
    trend = comp.compare_recent(n=2)["trend"]
    assert trend["patches"] == "stable"
    assert trend["tests"] == "stable"


def test_get_last_run(tmp_path: Path):
    comp = _comp(tmp_path)
    assert comp.get_last_run() is None
    comp.record_run(run_id="r1", mode="m", goal="g")
    comp.record_run(run_id="r2", mode="m", goal="g")
    last = comp.get_last_run()
    assert last is not None
    assert last.run_id == "r2"


def test_get_statistics_empty(tmp_path: Path):
    comp = _comp(tmp_path)
    assert comp.get_statistics() == {"total_runs": 0}


def test_get_statistics_counts_modes_and_duration(tmp_path: Path):
    comp = _comp(tmp_path)
    comp.record_run(run_id="r1", mode="report", goal="g", duration_seconds=2.0)
    comp.record_run(run_id="r2", mode="report", goal="g", duration_seconds=4.0)
    comp.record_run(run_id="r3", mode="auto", goal="g", duration_seconds=6.0)
    stats = comp.get_statistics()
    assert stats["total_runs"] == 3
    assert stats["modes"] == {"report": 2, "auto": 1}
    assert stats["avg_duration"] == 4.0
    assert stats["first_run"] == comp.runs[0].timestamp
    assert stats["last_run"] == comp.runs[-1].timestamp
