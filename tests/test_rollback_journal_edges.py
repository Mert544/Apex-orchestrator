"""Edge paths for RollbackJournal: diff truncation, anchoring, persistence round-trips."""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.rollback_journal import PatchRecord, RollbackJournal


def _journal(tmp_path: Path) -> RollbackJournal:
    return RollbackJournal(project_root=str(tmp_path), log_dir=str(tmp_path / ".apex"))


# -- project-root anchoring -------------------------------------------------

def test_default_log_dir_anchors_under_project_root(tmp_path: Path):
    journal = RollbackJournal(project_root=str(tmp_path))
    # Default log_dir ".apex" is anchored under the project root, not cwd.
    assert journal.journal_path == tmp_path / ".apex" / "patch_journal.json"
    assert journal.journal_path.parent.exists()


def test_absolute_log_dir_overrides_anchoring(tmp_path: Path):
    abs_dir = tmp_path / "elsewhere"
    journal = RollbackJournal(project_root=str(tmp_path / "proj"), log_dir=str(abs_dir))
    # An absolute log_dir wins via Path "/" semantics.
    assert journal.journal_path == abs_dir / "patch_journal.json"


# -- diff truncation at 50 lines -------------------------------------------

def test_generate_diff_truncates_to_fifty_lines(tmp_path: Path):
    journal = _journal(tmp_path)
    # 60 changed lines -> 60 diff lines, but only the first 50 are kept.
    old = "".join(f"o{i}\n" for i in range(60))
    new = "".join(f"n{i}\n" for i in range(60))
    diff = journal._generate_diff(old, new)
    assert len(diff.splitlines()) == 50
    assert "o0" in diff
    # A late line (beyond truncation) is absent.
    assert "n59" not in diff


def test_generate_diff_empty_to_empty_is_no_changes(tmp_path: Path):
    journal = _journal(tmp_path)
    assert journal._generate_diff("", "") == "no changes"


# -- persistence round-trips ------------------------------------------------

def test_mark_promoted_persists_across_reload(tmp_path: Path):
    journal = _journal(tmp_path)
    pid = journal.record_patch("a.py", "old\n", "new\n")
    journal.mark_promoted(pid)
    # A fresh journal reloads the promoted flag from disk.
    reloaded = _journal(tmp_path)
    assert reloaded.records[0].promoted is True


def test_rollback_persists_reverted_flag(tmp_path: Path):
    target = tmp_path / "a.py"
    target.write_text("NEW\n", encoding="utf-8")
    journal = _journal(tmp_path)
    pid = journal.record_patch("a.py", "OLD\n", "NEW\n")
    journal.rollback(pid)
    reloaded = _journal(tmp_path)
    assert reloaded.records[0].reverted is True


def test_cleanup_persists_trim_across_reload(tmp_path: Path):
    journal = _journal(tmp_path)
    for i in range(8):
        journal.record_patch(f"f{i}.py", "old\n", "new\n")
    journal.cleanup_old_records(keep_last=3)
    reloaded = _journal(tmp_path)
    assert len(reloaded.records) == 3
    assert reloaded.records[0].file_path == "f5.py"


# -- _load tolerates a records-less payload --------------------------------

def test_load_missing_records_key_yields_empty(tmp_path: Path):
    jpath = tmp_path / ".apex" / "patch_journal.json"
    jpath.parent.mkdir(parents=True, exist_ok=True)
    # Valid JSON but no "records" key -> .get default -> empty list, no error.
    jpath.write_text(json.dumps({"version": "2.0"}), encoding="utf-8")
    journal = _journal(tmp_path)
    assert journal.records == []


# -- get_patch_history with no records -------------------------------------

def test_get_patch_history_empty_journal(tmp_path: Path):
    journal = _journal(tmp_path)
    assert journal.get_patch_history() == []
    assert journal.get_active_patches() == []


def test_statistics_on_empty_journal(tmp_path: Path):
    journal = _journal(tmp_path)
    stats = journal.get_statistics()
    assert stats == {"total_patches": 0, "promoted": 0, "reverted": 0, "active": 0}


# -- PatchRecord dataclass round-trip with all flags set -------------------

def test_patch_record_round_trip_with_flags():
    rec = PatchRecord(
        patch_id="p", file_path="a.py", old_content="o", new_content="n",
        diff="d", applied_at="2020-01-01 00:00:00", promoted=True, reverted=True,
        run_id="r", issue="i", action_type="refactor",
    )
    assert PatchRecord(**rec.to_dict()) == rec
