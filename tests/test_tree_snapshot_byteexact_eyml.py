"""Byte-exact rollback for ``app.engine.tree_snapshot`` (L3 — Eller).

Recorded honest backlog: "rollback normalizes CRLF to LF (not byte-exact;
needs read_bytes/write_bytes)". Before this fix, ``snapshot_py_tree`` /
``restore_py_tree`` went through ``Path.read_text``/``write_text`` in
universal-newline TEXT mode, which silently collapses ``\\r\\n`` -> ``\\n`` on
capture — so a rollback on a CRLF/BOM project quietly REWROTE the user's line
endings even while reporting "auto-rolled-back". These tests pin the fix at
the byte level: a CRLF file, a BOM'd file, and a file with no trailing
newline all restore to their EXACT original bytes.

The plain-LF regression pin (``test_lf_identity_regression_pin``) guards the
other direction: the existing (LF-only) test population's observed behaviour
must not change now that the leaf is byte-based internally.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.tree_snapshot import restore_py_tree, snapshot_py_tree


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
