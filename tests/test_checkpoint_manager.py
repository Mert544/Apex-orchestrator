from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.engine.checkpoint_manager import CheckpointManager


def _mgr(tmp_path: Path) -> CheckpointManager:
    return CheckpointManager(project_root=str(tmp_path))


def test_init_creates_checkpoint_dir(tmp_path: Path):
    mgr = _mgr(tmp_path)
    assert mgr.checkpoint_dir.exists()
    assert mgr.checkpoint_dir == tmp_path / ".apex/checkpoints"


def test_should_checkpoint_logic(tmp_path: Path):
    mgr = _mgr(tmp_path)
    assert mgr._should_checkpoint(None) is False
    assert mgr._should_checkpoint({}) is False
    assert mgr._should_checkpoint({"patches_applied": 1}) is True
    assert mgr._should_checkpoint({"findings_count": 6}) is True
    assert mgr._should_checkpoint({"findings_count": 5}) is False
    assert mgr._should_checkpoint({"tests_passed": False}) is True
    assert mgr._should_checkpoint({"patches_applied": 0, "findings_count": 0}) is False


def test_save_checkpoint_skipped_when_not_required(tmp_path: Path):
    mgr = _mgr(tmp_path)
    result = mgr.save_checkpoint(run_id="r1", mode="report", goal="scan")
    assert result == {"saved": False, "reason": "checkpoint not required"}
    # No checkpoint file written.
    assert not (mgr.checkpoint_dir / "checkpoint-r1.json").exists()
    assert not (mgr.checkpoint_dir / "latest.json").exists()


def test_save_checkpoint_force_writes_files(tmp_path: Path):
    mgr = _mgr(tmp_path)
    result = mgr.save_checkpoint(
        run_id="r-force", mode="auto", goal="refactor", force=True
    )
    assert result["saved"] is True
    cp_file = mgr.checkpoint_dir / "checkpoint-r-force.json"
    assert cp_file.exists()
    assert result["checkpoint_file"] == str(cp_file)

    data = json.loads(cp_file.read_text(encoding="utf-8"))
    assert data["run_id"] == "r-force"
    assert data["mode"] == "auto"
    assert data["goal"] == "refactor"
    assert data["stats"] == {}

    latest = json.loads((mgr.checkpoint_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "r-force"


def test_save_checkpoint_triggered_by_stats(tmp_path: Path):
    mgr = _mgr(tmp_path)
    result = mgr.save_checkpoint(
        run_id="r-stats", mode="auto", goal="g", stats={"patches_applied": 3}
    )
    assert result["saved"] is True
    data = json.loads(
        (mgr.checkpoint_dir / "checkpoint-r-stats.json").read_text(encoding="utf-8")
    )
    assert data["stats"]["patches_applied"] == 3


def test_load_latest_checkpoint_none_when_absent(tmp_path: Path):
    mgr = _mgr(tmp_path)
    assert mgr.load_latest_checkpoint() is None


def test_load_latest_checkpoint_returns_data(tmp_path: Path):
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="r1", mode="m", goal="g", force=True)
    latest = mgr.load_latest_checkpoint()
    assert latest is not None
    assert latest["run_id"] == "r1"


def test_load_latest_checkpoint_corrupt_returns_none(tmp_path: Path):
    mgr = _mgr(tmp_path)
    (mgr.checkpoint_dir / "latest.json").write_text("{bad", encoding="utf-8")
    assert mgr.load_latest_checkpoint() is None


def test_get_checkpoint_by_run_id(tmp_path: Path):
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="rx", mode="m", goal="g", force=True)
    cp = mgr.get_checkpoint("rx")
    assert cp is not None
    assert cp["run_id"] == "rx"
    assert mgr.get_checkpoint("missing") is None


def test_get_checkpoint_corrupt_returns_none(tmp_path: Path):
    mgr = _mgr(tmp_path)
    (mgr.checkpoint_dir / "checkpoint-bad.json").write_text("not json", encoding="utf-8")
    assert mgr.get_checkpoint("bad") is None


def test_list_checkpoints_orders_by_mtime(tmp_path: Path):
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="r1", mode="m", goal="g", force=True)
    mgr.save_checkpoint(run_id="r2", mode="m", goal="g", force=True)
    mgr.save_checkpoint(run_id="r3", mode="m", goal="g", force=True)
    # Make r1 the most recently modified to assert ordering deterministically.
    (mgr.checkpoint_dir / "checkpoint-r1.json").touch()

    listed = mgr.list_checkpoints()
    run_ids = [c["run_id"] for c in listed]
    assert set(run_ids) == {"r1", "r2", "r3"}
    assert run_ids[0] == "r1"


def test_list_checkpoints_respects_limit(tmp_path: Path):
    mgr = _mgr(tmp_path)
    for i in range(5):
        mgr.save_checkpoint(run_id=f"r{i}", mode="m", goal="g", force=True)
    assert len(mgr.list_checkpoints(limit=2)) == 2


def test_list_checkpoints_skips_corrupt(tmp_path: Path):
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="good", mode="m", goal="g", force=True)
    (mgr.checkpoint_dir / "checkpoint-corrupt.json").write_text("oops", encoding="utf-8")

    listed = mgr.list_checkpoints()
    run_ids = [c["run_id"] for c in listed]
    assert run_ids == ["good"]


def test_list_checkpoints_empty(tmp_path: Path):
    mgr = _mgr(tmp_path)
    assert mgr.list_checkpoints() == []


def test_try_git_commit_non_repo_is_silent(tmp_path: Path):
    # No git repo here -> _try_git_commit should swallow and not raise.
    mgr = _mgr(tmp_path)
    mgr._try_git_commit("r1", "2020-01-01", "m", {"patches_applied": 1})
    # Save still succeeds despite git being a no-op.
    result = mgr.save_checkpoint(run_id="r1", mode="m", goal="g", force=True)
    assert result["saved"] is True


def test_try_git_commit_swallows_subprocess_error(tmp_path: Path, monkeypatch):
    # Force subprocess.run to raise so the except branch is exercised.
    import app.engine.checkpoint_manager as cm

    def boom(*args, **kwargs):
        raise cm.subprocess.TimeoutExpired(cmd="git", timeout=10)

    monkeypatch.setattr(cm.subprocess, "run", boom)
    mgr = _mgr(tmp_path)
    # Should not raise even though git invocation fails.
    mgr._try_git_commit("r1", "2020-01-01", "m", {"patches_applied": 1})
    result = mgr.save_checkpoint(run_id="r1", mode="m", goal="g", force=True)
    assert result["saved"] is True


def test_save_checkpoint_commits_to_real_git(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True
    )

    mgr = _mgr(tmp_path)
    result = mgr.save_checkpoint(run_id="gitrun", mode="auto", goal="g", force=True)
    assert result["saved"] is True

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True
    )
    assert "checkpoint: auto run gitrun" in log.stdout
