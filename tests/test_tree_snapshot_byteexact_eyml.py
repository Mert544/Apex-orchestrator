"""Byte-exact rollback + FAIL-CLOSED failure reporting for ``tree_snapshot``.

Two independent waves pin this LEAF's restore contract; both live here.

L3 (Eller) — byte-exact codec boundary. Recorded honest backlog: "rollback
normalizes CRLF to LF (not byte-exact; needs read_bytes/write_bytes)". Before
that fix, ``snapshot_py_tree`` / ``restore_py_tree`` went through
``Path.read_text``/``write_text`` in universal-newline TEXT mode, which
silently collapses ``\\r\\n`` -> ``\\n`` on capture — so a rollback on a
CRLF/BOM project quietly REWROTE the user's line endings even while reporting
"auto-rolled-back". Those tests pin the fix at the byte level: a CRLF file, a
BOM'd file, and a file with no trailing newline all restore to their EXACT
original bytes. The plain-LF regression pin
(``test_tree_snapshot_lf_identity_regression_pin``) guards the other
direction: the existing (LF-only) test population's observed behaviour must
not change now that the leaf is byte-based internally.

W3A-L4 (finding 5) — fail-closed failure reporting. ``restore_py_tree`` is
best-effort per path: a single unwritable/undeletable file must never abort
the rest of the restore. Pre-fix that best-effort behaviour was ALSO silent —
the function returned ``None`` and a caller had no way to know the tree it
just "restored" might not actually be byte-identical to the snapshot. A
durable false-negative followed: both backstop restores
(``objective_compiler._backstop_restore`` and
``develop_session._restore_and_zero``) unconditionally wrote a "rolled_back"
proof-of-fix correction even when the restore was genuinely incomplete — the
organism could learn "avoid this" from a record whose own premise (the tree is
back at baseline) was never actually true. The fix is ADDITIVE:
``restore_py_tree`` now returns the sorted list of rel-posix paths whose
``write_bytes``/``unlink`` FAILED (empty on full success); every existing
caller that ignores the return value is unaffected. These tests pin that
contract directly at the LEAF: a successful restore returns ``[]`` and leaves
the tree byte-identical to the snapshot; a failed path is reported (not
silently skipped) while the REST of the tree still restores.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.tree_snapshot import restore_py_tree, snapshot_py_tree


# --- L3: byte-exact CRLF/BOM/no-trailing-newline round trip -------------------

def test_tree_snapshot_restore_preserves_crlf(tmp_path: Path):
    rel = "pkg/a.py"
    (tmp_path / "pkg").mkdir()
    original = b"x = 1\r\ny = 2\r\n"
    (tmp_path / rel).write_bytes(original)

    before = snapshot_py_tree(tmp_path)
    (tmp_path / rel).write_bytes(b"x = 999\r\n")
    after = snapshot_py_tree(tmp_path)

    restore_py_tree(tmp_path, before, after)

    assert (tmp_path / rel).read_bytes() == original


def test_tree_snapshot_restore_preserves_crlf_no_trailing_newline(tmp_path: Path):
    rel = "pkg/b.py"
    (tmp_path / "pkg").mkdir()
    original = b"a=1\r\nb=2"  # no final newline
    (tmp_path / rel).write_bytes(original)

    before = snapshot_py_tree(tmp_path)
    (tmp_path / rel).write_bytes(b"a=999\r\nb=2\r\n")
    after = snapshot_py_tree(tmp_path)

    restore_py_tree(tmp_path, before, after)

    restored = (tmp_path / rel).read_bytes()
    assert restored == original
    assert not restored.endswith(b"\n\n")
    assert not restored.endswith(b"\r\n\n")


def test_tree_snapshot_restore_preserves_bom(tmp_path: Path):
    rel = "pkg/c.py"
    (tmp_path / "pkg").mkdir()
    original = b"\xef\xbb\xbfx = 1\r\ny = 2\r\n"  # UTF-8 BOM + CRLF body
    (tmp_path / rel).write_bytes(original)

    before = snapshot_py_tree(tmp_path)
    (tmp_path / rel).write_bytes(b"x = 0\r\n")
    after = snapshot_py_tree(tmp_path)

    restore_py_tree(tmp_path, before, after)

    restored = (tmp_path / rel).read_bytes()
    assert restored == original
    assert restored.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in restored


def test_snapshot_feeds_develop_session_diff_without_crashing(tmp_path: Path):
    # RED-FIRST PIN: before this fix, snapshot_py_tree/restore_py_tree had
    # been switched to a dict[str, bytes] contract, but develop_session's
    # _diff_snapshots (the PRIMARY apply-mode consumer, called from every
    # apply=True run_develop_session session via _finalize_apply) still
    # assumes dict[str, str] and feeds the values straight into
    # difflib.unified_diff(..., fromfile=..., tofile=..., lineterm="\n") — a
    # str/bytes mix that raises ``TypeError: lines to compare must be str,
    # not bytes`` the moment ANY changed .py file is diffed. Reproduced
    # directly against the pre-fix code:
    #   before = {'pkg/a.py': b'x = 1\n'}; after = {'pkg/a.py': b'x = 2\n'}
    #   TypeError: lines to compare must be str, not bytes (b'x = 1\n')
    # This test exercises the exact same real consumer (no mocking) and pins
    # that it no longer crashes, and that CRLF content diffs sanely too.
    from app.engine.develop_session import _diff_snapshots

    rel = "pkg/a.py"
    (tmp_path / "pkg").mkdir()
    (tmp_path / rel).write_bytes(b"x = 1\r\n")

    before = snapshot_py_tree(tmp_path)
    (tmp_path / rel).write_bytes(b"x = 2\r\n")
    after = snapshot_py_tree(tmp_path)

    files, added, removed, diff_text = _diff_snapshots(before, after)

    assert files == [rel]
    assert added == 1 and removed == 1
    assert "-x = 1" in diff_text
    assert "+x = 2" in diff_text


def test_tree_snapshot_lf_identity_regression_pin(tmp_path: Path):
    # Plain-LF file: snapshot/restore must still be byte-identical to the
    # pre-fix (text-mode) behaviour for the existing (LF-only) test population.
    rel = "pkg/d.py"
    (tmp_path / "pkg").mkdir()
    original_text = "x = 1\ny = 2\n"
    (tmp_path / rel).write_text(original_text, encoding="utf-8")

    before = snapshot_py_tree(tmp_path)
    (tmp_path / rel).write_text("x = 999\n", encoding="utf-8")
    after = snapshot_py_tree(tmp_path)

    restore_py_tree(tmp_path, before, after)

    assert (tmp_path / rel).read_bytes() == original_text.encode("utf-8")
    assert (tmp_path / rel).read_text(encoding="utf-8") == original_text


# --- W3A-L4 finding 5: the fail-closed failure-reporting contract -------------

def _tree(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    return root


def test_restore_py_tree_success_returns_empty_list_and_is_byte_exact(
        tmp_path: Path):
    _tree(tmp_path)
    before = snapshot_py_tree(tmp_path)
    (tmp_path / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    (tmp_path / "pkg" / "new.py").write_text("n = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").unlink()
    after = snapshot_py_tree(tmp_path)

    failed = restore_py_tree(tmp_path, before, after)

    assert failed == []
    assert snapshot_py_tree(tmp_path) == before  # byte-exact round trip


def test_restore_py_tree_empty_snapshots_return_empty_list(tmp_path: Path):
    assert restore_py_tree(tmp_path, {}, {}) == []


def test_restore_py_tree_reports_a_failed_write_and_still_restores_the_rest(
        tmp_path: Path, monkeypatch):
    # RED-FIRST: pre-fix a write failure was swallowed with no evidence at all
    # (``continue``, ``-> None``) — a caller could not tell a genuinely
    # incomplete restore from a clean one.
    _tree(tmp_path)
    before = snapshot_py_tree(tmp_path)
    (tmp_path / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("y = 999\n", encoding="utf-8")
    after = snapshot_py_tree(tmp_path)

    real_write_bytes = Path.write_bytes

    def _boom(self, *a, **kw):
        if self.name == "a.py":
            raise OSError("disk full")
        return real_write_bytes(self, *a, **kw)

    monkeypatch.setattr(Path, "write_bytes", _boom)
    failed = restore_py_tree(tmp_path, before, after)

    assert failed == ["pkg/a.py"]
    # Best-effort: the OTHER file still restored despite the one failure.
    assert (tmp_path / "pkg" / "b.py").read_text(encoding="utf-8") == "y = 2\n"
    # The failed path is untouched — still holding its un-restored bytes.
    assert (tmp_path / "pkg" / "a.py").read_text(encoding="utf-8") == "x = 999\n"


def test_restore_py_tree_reports_a_failed_unlink_and_still_restores_the_rest(
        tmp_path: Path, monkeypatch):
    _tree(tmp_path)
    before = snapshot_py_tree(tmp_path)
    (tmp_path / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    (tmp_path / "pkg" / "new.py").write_text("n = 1\n", encoding="utf-8")
    after = snapshot_py_tree(tmp_path)

    real_unlink = Path.unlink

    def _boom(self, *a, **kw):
        if self.name == "new.py":
            raise OSError("permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _boom)
    failed = restore_py_tree(tmp_path, before, after)

    assert failed == ["pkg/new.py"]
    # Best-effort: the modified file still restored despite the unlink failure.
    assert (tmp_path / "pkg" / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    # The file that failed to delete is still there.
    assert (tmp_path / "pkg" / "new.py").exists()


def test_restore_py_tree_reports_multiple_failures_sorted(
        tmp_path: Path, monkeypatch):
    _tree(tmp_path)
    before = snapshot_py_tree(tmp_path)
    (tmp_path / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("y = 999\n", encoding="utf-8")
    after = snapshot_py_tree(tmp_path)

    def _boom(self, *a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", _boom)
    failed = restore_py_tree(tmp_path, before, after)

    assert failed == ["pkg/a.py", "pkg/b.py"]  # sorted, deterministic
