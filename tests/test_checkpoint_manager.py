from app.engine.checkpoint_manager import CheckpointManager


def _mgr(tmp_path):
    return CheckpointManager(project_root=str(tmp_path))


def test_should_checkpoint_rules(tmp_path):
    m = _mgr(tmp_path)
    assert m._should_checkpoint(None) is False
    assert m._should_checkpoint({}) is False
    assert m._should_checkpoint({"patches_applied": 1}) is True
    assert m._should_checkpoint({"findings_count": 6}) is True
    assert m._should_checkpoint({"tests_passed": False}) is True
    assert m._should_checkpoint({"findings_count": 2}) is False


def test_save_checkpoint_when_required(tmp_path):
    m = _mgr(tmp_path)
    result = m.save_checkpoint("r1", "supervised", "fix", stats={"patches_applied": 2})
    assert result["saved"] is True
    assert (tmp_path / ".apex" / "checkpoints" / "checkpoint-r1.json").exists()
    assert (tmp_path / ".apex" / "checkpoints" / "latest.json").exists()


def test_save_checkpoint_skipped_when_not_required(tmp_path):
    m = _mgr(tmp_path)
    result = m.save_checkpoint("r2", "report", "scan", stats={})
    assert result["saved"] is False
    assert "not required" in result["reason"]


def test_save_checkpoint_force(tmp_path):
    m = _mgr(tmp_path)
    result = m.save_checkpoint("r3", "report", "scan", stats={}, force=True)
    assert result["saved"] is True


def test_load_latest_checkpoint(tmp_path):
    m = _mgr(tmp_path)
    assert m.load_latest_checkpoint() is None
    m.save_checkpoint("r1", "report", "g", force=True)
    latest = m.load_latest_checkpoint()
    assert latest["run_id"] == "r1"


def test_list_checkpoints(tmp_path):
    m = _mgr(tmp_path)
    m.save_checkpoint("r1", "report", "g", force=True)
    m.save_checkpoint("r2", "report", "g", force=True)
    cps = m.list_checkpoints()
    ids = {c["run_id"] for c in cps}
    assert {"r1", "r2"} <= ids


def test_get_checkpoint(tmp_path):
    m = _mgr(tmp_path)
    assert m.get_checkpoint("missing") is None
    m.save_checkpoint("r1", "report", "g", force=True)
    cp = m.get_checkpoint("r1")
    assert cp["run_id"] == "r1"
    assert cp["mode"] == "report"
