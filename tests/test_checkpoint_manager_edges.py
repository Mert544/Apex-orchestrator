"""Edge paths for CheckpointManager: custom dirs, round-trips, git skip-when-clean."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.engine.checkpoint_manager import CheckpointManager


def _mgr(tmp_path: Path) -> CheckpointManager:
    return CheckpointManager(project_root=str(tmp_path))


def test_custom_checkpoint_dir_is_created(tmp_path: Path):
    mgr = CheckpointManager(project_root=str(tmp_path), checkpoint_dir="cp/nested")
    assert mgr.checkpoint_dir == tmp_path / "cp/nested"
    assert mgr.checkpoint_dir.exists()


def test_save_then_get_round_trips_stats(tmp_path: Path):
    mgr = _mgr(tmp_path)
    stats = {"patches_applied": 2, "findings_count": 1, "tests_passed": True}
    mgr.save_checkpoint(run_id="rt", mode="auto", goal="g", stats=stats)
    cp = mgr.get_checkpoint("rt")
    assert cp is not None
    assert cp["stats"] == stats
    assert cp["mode"] == "auto"
    # latest mirrors the same checkpoint.
    assert mgr.load_latest_checkpoint()["run_id"] == "rt"


def test_findings_count_boundary_six_saves_five_does_not(tmp_path: Path):
    mgr = _mgr(tmp_path)
    skipped = mgr.save_checkpoint(run_id="five", mode="m", goal="g",
                                  stats={"findings_count": 5})
    saved = mgr.save_checkpoint(run_id="six", mode="m", goal="g",
                                stats={"findings_count": 6})
    assert skipped["saved"] is False
    assert saved["saved"] is True


def test_tests_passed_false_triggers_save(tmp_path: Path):
    mgr = _mgr(tmp_path)
    result = mgr.save_checkpoint(run_id="failrun", mode="m", goal="g",
                                 stats={"tests_passed": False})
    assert result["saved"] is True


def test_git_commit_skipped_when_tree_clean(tmp_path: Path):
    # A committed-clean repo: git status --porcelain is empty -> no add/commit.
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path,
                   capture_output=True)
    (tmp_path / "seed.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "seed"],
                   cwd=tmp_path, capture_output=True)
    log_before = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path,
                                capture_output=True, text=True).stdout
    # Clean tree -> _try_git_commit takes the empty-stdout branch (no commit).
    mgr = _mgr(tmp_path)
    mgr._try_git_commit("r", "2020-01-01", "m", {"patches_applied": 1})
    log_after = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path,
                               capture_output=True, text=True).stdout
    assert log_before == log_after


def test_list_checkpoints_ignores_latest_json(tmp_path: Path):
    # latest.json is not named checkpoint-*.json, so it never appears in listings.
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="one", mode="m", goal="g", force=True)
    listed = mgr.list_checkpoints()
    assert all(c["run_id"] != "latest" for c in listed)
    assert [c["run_id"] for c in listed] == ["one"]


def test_checkpoint_file_content_is_valid_json(tmp_path: Path):
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="json", mode="m", goal="g", force=True)
    raw = (mgr.checkpoint_dir / "checkpoint-json.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["run_id"] == "json"
    assert "timestamp" in parsed
