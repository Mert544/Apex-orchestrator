from app.engine.rollback_journal import RollbackJournal


def _journal(tmp_path):
    return RollbackJournal(project_root=str(tmp_path), log_dir=str(tmp_path / ".apex"))


def _record(j, tmp_path, name="f.py", old="old\n", new="new\n"):
    (tmp_path / name).write_text(new)
    return j.record_patch(name, old_content=old, new_content=new, run_id="r1", issue="x")


def test_record_patch_returns_id_and_persists(tmp_path):
    j = _journal(tmp_path)
    pid = _record(j, tmp_path)
    assert pid
    # Reload from disk -> persisted.
    j2 = _journal(tmp_path)
    assert len(j2.records) == 1
    assert j2.records[0].patch_id == pid


def test_rollback_restores_old_content(tmp_path):
    j = _journal(tmp_path)
    pid = _record(j, tmp_path)
    assert (tmp_path / "f.py").read_text() == "new\n"
    assert j.rollback(pid) is True
    assert (tmp_path / "f.py").read_text() == "old\n"
    # Second rollback of same id is a no-op (already reverted).
    assert j.rollback(pid) is False


def test_rollback_unknown_id(tmp_path):
    assert _journal(tmp_path).rollback("nope") is False


def test_rollback_last(tmp_path):
    j = _journal(tmp_path)
    _record(j, tmp_path, name="a.py")
    _record(j, tmp_path, name="b.py", new="b-new\n")
    assert j.rollback_last() is True
    assert (tmp_path / "b.py").read_text() == "old\n"


def test_rollback_all(tmp_path):
    j = _journal(tmp_path)
    _record(j, tmp_path, name="a.py")
    _record(j, tmp_path, name="b.py")
    count = j.rollback_all()
    assert count == 2
    assert j.rollback_all() == 0  # nothing left


def test_mark_promoted_and_active(tmp_path):
    j = _journal(tmp_path)
    pid = _record(j, tmp_path)
    assert len(j.get_active_patches()) == 1
    assert j.mark_promoted(pid) is True
    assert j.get_active_patches() == []
    assert j.mark_promoted("missing") is False


def test_get_patch_history_filter(tmp_path):
    j = _journal(tmp_path)
    _record(j, tmp_path, name="a.py")
    _record(j, tmp_path, name="b.py")
    assert len(j.get_patch_history()) == 2
    assert len(j.get_patch_history(file_path="a.py")) == 1


def test_statistics(tmp_path):
    j = _journal(tmp_path)
    p1 = _record(j, tmp_path, name="a.py")
    _record(j, tmp_path, name="b.py")
    j.mark_promoted(p1)
    stats = j.get_statistics()
    assert stats["total_patches"] == 2
    assert stats["promoted"] == 1
    assert stats["active"] == 1


def test_cleanup_old_records(tmp_path):
    j = _journal(tmp_path)
    for i in range(5):
        _record(j, tmp_path, name=f"f{i}.py")
    removed = j.cleanup_old_records(keep_last=2)
    assert removed == 3
    assert len(j.records) == 2
    assert j.cleanup_old_records(keep_last=10) == 0


def test_journal_anchored_under_project_root(tmp_path):
    # Regression: the journal must live under project_root, not a cwd-relative
    # .apex (which caused cross-project contamination). Absolute log_dir wins.
    # Use writable tmp_path dirs — __init__ mkdir's the journal's parent, so a
    # hardcoded system path (e.g. /abs) fails on non-root CI runners.
    from app.engine.rollback_journal import RollbackJournal

    proj = tmp_path / "projX"
    j = RollbackJournal(project_root=str(proj))
    assert j.journal_path == proj / ".apex" / "patch_journal.json"

    abs_dir = tmp_path / "elsewhere" / ".apex"
    j2 = RollbackJournal(project_root=str(proj), log_dir=str(abs_dir))
    assert j2.journal_path == abs_dir / "patch_journal.json"  # absolute log_dir wins
