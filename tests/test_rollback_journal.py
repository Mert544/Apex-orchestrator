from __future__ import annotations

import json
from pathlib import Path

from app.engine.rollback_journal import PatchRecord, RollbackJournal


def _journal(tmp_path: Path) -> RollbackJournal:
    return RollbackJournal(project_root=str(tmp_path), log_dir=str(tmp_path / ".apex"))


def test_record_patch_persists_and_returns_id(tmp_path: Path):
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    journal = _journal(tmp_path)
    pid = journal.record_patch("a.py", "old\n", "new\n", run_id="run-1", issue="bug")

    assert pid.startswith("patch-a-")
    data = json.loads((tmp_path / ".apex" / "patch_journal.json").read_text(encoding="utf-8"))
    assert data["version"] == "2.0"
    assert len(data["records"]) == 1
    rec = data["records"][0]
    assert rec["patch_id"] == pid
    assert rec["run_id"] == "run-1"
    assert rec["issue"] == "bug"
    assert rec["action_type"] == "patch"


def test_generate_diff_added_removed_and_changed(tmp_path: Path):
    journal = _journal(tmp_path)
    # Line 1 changed, line 2 removed compared to a 1-line new file with an added line.
    diff = journal._generate_diff("alpha\nbeta\n", "gamma\n")
    assert "-1: alpha" in diff
    assert "+1: gamma" in diff
    assert "-2: beta" in diff


def test_generate_diff_no_changes(tmp_path: Path):
    journal = _journal(tmp_path)
    assert journal._generate_diff("same\n", "same\n") == "no changes"


def test_generate_diff_added_lines(tmp_path: Path):
    journal = _journal(tmp_path)
    diff = journal._generate_diff("one\n", "one\ntwo\n")
    assert "+2: two" in diff


def test_rollback_restores_old_content(tmp_path: Path):
    target = tmp_path / "a.py"
    target.write_text("NEW\n", encoding="utf-8")
    journal = _journal(tmp_path)
    pid = journal.record_patch("a.py", "OLD\n", "NEW\n")

    assert journal.rollback(pid) is True
    assert target.read_text(encoding="utf-8") == "OLD\n"
    # Record marked reverted, second rollback is a no-op.
    assert journal.records[0].reverted is True
    assert journal.rollback(pid) is False


def test_rollback_unknown_id_returns_false(tmp_path: Path):
    journal = _journal(tmp_path)
    journal.record_patch("a.py", "old\n", "new\n")
    assert journal.rollback("does-not-exist") is False


def test_rollback_write_failure_returns_false(tmp_path: Path):
    # file_path points at a directory -> write_text raises, caught and returns False.
    (tmp_path / "adir").mkdir()
    journal = _journal(tmp_path)
    pid = journal.record_patch("adir", "old\n", "new\n")
    assert journal.rollback(pid) is False
    assert journal.records[0].reverted is False


def test_rollback_last_picks_most_recent_active(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("y", encoding="utf-8")
    journal = _journal(tmp_path)
    journal.record_patch("a.py", "A_OLD\n", "A_NEW\n")
    journal.record_patch("b.py", "B_OLD\n", "B_NEW\n")

    assert journal.rollback_last() is True
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "B_OLD\n"
    # a.py untouched (still the most-recent active was b.py).
    assert journal.records[1].reverted is True
    assert journal.records[0].reverted is False


def test_rollback_last_empty_returns_false(tmp_path: Path):
    journal = _journal(tmp_path)
    assert journal.rollback_last() is False


def test_rollback_all_counts_and_skips_reverted(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("y", encoding="utf-8")
    journal = _journal(tmp_path)
    pid_a = journal.record_patch("a.py", "A_OLD\n", "A_NEW\n")
    journal.record_patch("b.py", "B_OLD\n", "B_NEW\n")

    journal.rollback(pid_a)  # already revert one
    count = journal.rollback_all()
    assert count == 1  # only b.py remained active
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "B_OLD\n"


def test_rollback_all_handles_write_errors(tmp_path: Path):
    (tmp_path / "good.py").write_text("x", encoding="utf-8")
    (tmp_path / "baddir").mkdir()
    journal = _journal(tmp_path)
    journal.record_patch("good.py", "GOOD_OLD\n", "GOOD_NEW\n")
    journal.record_patch("baddir", "old\n", "new\n")

    count = journal.rollback_all()
    assert count == 1
    assert (tmp_path / "good.py").read_text(encoding="utf-8") == "GOOD_OLD\n"


def test_rollback_all_no_active_returns_zero(tmp_path: Path):
    journal = _journal(tmp_path)
    assert journal.rollback_all() == 0


def test_mark_promoted(tmp_path: Path):
    journal = _journal(tmp_path)
    pid = journal.record_patch("a.py", "old\n", "new\n")
    assert journal.mark_promoted(pid) is True
    assert journal.records[0].promoted is True
    assert journal.mark_promoted("missing") is False


def test_get_patch_history_reversed_and_filtered(tmp_path: Path):
    journal = _journal(tmp_path)
    journal.record_patch("a.py", "1\n", "2\n")
    journal.record_patch("b.py", "3\n", "4\n")
    journal.record_patch("a.py", "5\n", "6\n")

    all_hist = journal.get_patch_history()
    # Most recent first.
    assert all_hist[0]["file_path"] == "a.py"
    assert len(all_hist) == 3

    a_hist = journal.get_patch_history("a.py")
    assert len(a_hist) == 2
    assert all(r["file_path"] == "a.py" for r in a_hist)


def test_get_active_patches_excludes_promoted_and_reverted(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    journal = _journal(tmp_path)
    pid1 = journal.record_patch("a.py", "old\n", "new\n")
    pid2 = journal.record_patch("b.py", "old\n", "new\n")
    journal.record_patch("c.py", "old\n", "new\n")

    journal.mark_promoted(pid1)
    journal.rollback(pid2)  # b.py doesn't exist on disk -> reverted may fail; force record

    active = journal.get_active_patches()
    active_files = {r["file_path"] for r in active}
    assert "a.py" not in active_files  # promoted
    assert "c.py" in active_files


def test_get_statistics(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    journal = _journal(tmp_path)
    pid1 = journal.record_patch("a.py", "old\n", "new\n")
    pid2 = journal.record_patch("a.py", "old2\n", "new2\n")
    journal.record_patch("a.py", "old3\n", "new3\n")

    journal.mark_promoted(pid1)
    journal.rollback(pid2)

    stats = journal.get_statistics()
    assert stats["total_patches"] == 3
    assert stats["promoted"] == 1
    assert stats["reverted"] == 1
    assert stats["active"] == 1


def test_cleanup_old_records_below_threshold(tmp_path: Path):
    journal = _journal(tmp_path)
    for i in range(3):
        journal.record_patch(f"f{i}.py", "old\n", "new\n")
    assert journal.cleanup_old_records(keep_last=100) == 0
    assert len(journal.records) == 3


def test_cleanup_old_records_trims(tmp_path: Path):
    journal = _journal(tmp_path)
    for i in range(10):
        journal.record_patch(f"f{i}.py", "old\n", "new\n")
    removed = journal.cleanup_old_records(keep_last=4)
    assert removed == 6
    assert len(journal.records) == 4
    assert journal.records[0].file_path == "f6.py"


def test_load_existing_journal(tmp_path: Path):
    journal = _journal(tmp_path)
    journal.record_patch("a.py", "old\n", "new\n", run_id="run-x")

    journal2 = _journal(tmp_path)
    assert len(journal2.records) == 1
    assert journal2.records[0].run_id == "run-x"


def test_load_corrupt_journal_resets(tmp_path: Path):
    jpath = tmp_path / ".apex" / "patch_journal.json"
    jpath.parent.mkdir(parents=True, exist_ok=True)
    jpath.write_text("not json at all", encoding="utf-8")
    journal = _journal(tmp_path)
    assert journal.records == []


def test_patch_record_to_dict():
    rec = PatchRecord(
        patch_id="p1",
        file_path="a.py",
        old_content="o",
        new_content="n",
        diff="d",
        applied_at="2020-01-01 00:00:00",
        run_id="r",
        issue="i",
        action_type="patch",
    )
    d = rec.to_dict()
    assert d["patch_id"] == "p1"
    assert d["promoted"] is False
    assert d["reverted"] is False
    assert PatchRecord(**d) == rec
