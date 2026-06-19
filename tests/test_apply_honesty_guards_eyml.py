"""Two write outcomes must never be reported as an applied fix (red-team
proof-integrity findings F5 / F6):

  * PARTIAL — a multi-file patch where some files were skipped (their
    expected_old_content no longer matched): a half-applied state is not success;
  * NO-OP — a patch whose written content equals what was already on disk: an
    empty diff is not a fix.

In both cases any file that WAS written is restored to its pre-patch snapshot,
and the result honestly reports ``applied: False`` with a reason. Deterministic.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.engine.idea_action_bridge import IdeaActionBridge


def _applied(ok=True, changed=None, skipped=None):
    return SimpleNamespace(ok=ok, changed_files=changed or [],
                           skipped_files=skipped or [], error=None)


def test_partial_apply_is_blocked_and_restored(tmp_path):
    (tmp_path / "a.py").write_text("written-a\n", encoding="utf-8")  # we "wrote" a
    snapshot = {"a.py": "orig-a\n", "b.py": None}  # a had content, b was new
    patches = [{"path": "a.py", "new_content": "written-a\n"},
               {"path": "b.py", "new_content": "x\n"}]
    applied = _applied(changed=["a.py"], skipped=["b.py"])

    block = IdeaActionBridge._partial_or_noop_block(
        str(tmp_path), snapshot, applied, patches, "demo", "autonomous")
    assert block is not None
    assert block["applied"] is False
    assert block["reason"].startswith("partial apply")
    assert block["skipped_files"] == ["b.py"]
    # the file we wrote is restored to its snapshot
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "orig-a\n"


def test_noop_apply_is_blocked_and_restored(tmp_path):
    (tmp_path / "a.py").write_text("same\n", encoding="utf-8")
    snapshot = {"a.py": "same\n"}  # written content equals the snapshot
    patches = [{"path": "a.py", "new_content": "same\n"}]
    applied = _applied(changed=["a.py"])

    block = IdeaActionBridge._partial_or_noop_block(
        str(tmp_path), snapshot, applied, patches, "demo", "autonomous")
    assert block is not None
    assert block["applied"] is False
    assert block["reason"] == "no change (patch is a no-op)"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "same\n"


def test_new_file_creation_is_not_a_noop(tmp_path):
    # snapshot None (brand-new file) with real content is a genuine change.
    snapshot = {"new.py": None}
    patches = [{"path": "new.py", "new_content": "print(1)\n"}]
    applied = _applied(changed=["new.py"])
    block = IdeaActionBridge._partial_or_noop_block(
        str(tmp_path), snapshot, applied, patches, "demo", "autonomous")
    assert block is None  # proceed — this IS a change


def test_real_change_proceeds(tmp_path):
    snapshot = {"a.py": "old\n"}
    patches = [{"path": "a.py", "new_content": "new\n"}]
    applied = _applied(changed=["a.py"])
    block = IdeaActionBridge._partial_or_noop_block(
        str(tmp_path), snapshot, applied, patches, "demo", "autonomous")
    assert block is None
