from app.engine.run_comparison import RunComparison, RunSnapshot


def _comp(tmp_path):
    return RunComparison(project_root=str(tmp_path), log_dir=str(tmp_path / ".apex"))


def test_record_and_persist(tmp_path):
    c = _comp(tmp_path)
    c.record_run("r1", mode="supervised", goal="fix", patches_applied=2, duration_seconds=1.5)
    assert len(c.runs) == 1
    # Reload from disk -> persisted.
    c2 = _comp(tmp_path)
    assert len(c2.runs) == 1
    assert c2.runs[0].run_id == "r1"
    assert c2.runs[0].patches_applied == 2


def test_compare_recent_empty(tmp_path):
    assert _comp(tmp_path).compare_recent() == {"error": "No runs to compare"}


def test_compare_recent_summary(tmp_path):
    c = _comp(tmp_path)
    c.record_run("r1", mode="report", goal="g", patches_applied=1, tests_passed=True)
    c.record_run("r2", mode="report", goal="g", patches_applied=3, tests_passed=False)
    report = c.compare_recent(n=5)
    assert report["runs_compared"] == 2
    assert report["summary"]["total_patches_applied"] == 4


def test_history_capped_at_100(tmp_path):
    c = _comp(tmp_path)
    for i in range(105):
        c.record_run(f"r{i}", mode="report", goal="g")
    assert len(c.runs) == 100
    assert c.runs[-1].run_id == "r104"


def test_get_last_run_and_statistics(tmp_path):
    c = _comp(tmp_path)
    assert c.get_last_run() is None
    assert c.get_statistics() == {"total_runs": 0}
    c.record_run("r1", mode="report", goal="g")
    assert c.get_last_run().run_id == "r1"
    assert c.get_statistics()["total_runs"] == 1


def test_snapshot_roundtrip(tmp_path):
    # Record via the public API, then round-trip the persisted snapshot.
    c = _comp(tmp_path)
    c.record_run("r", mode="report", goal="g", findings_count=4)
    d = c.runs[0].to_dict()
    assert d["run_id"] == "r"
    assert d["findings_count"] == 4
    assert RunSnapshot(**d).run_id == "r"
