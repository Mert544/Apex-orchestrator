"""Unit tests for the shared snapshot/restore LEAF (``app.engine.tree_snapshot``).

The pair was extracted VERBATIM from ``develop_session`` (``_snapshot`` /
``_restore_snapshot``) so the objective compiler's end-of-campaign regression
backstop restores with IDENTICAL semantics without an import cycle. These tests
pin the leaf's own contract directly — capture set, skip dirs, restore of
modified/created/deleted files, determinism — plus the empty/edge paths, and
that the develop-session delegators still point here (no drift between the two
backstops' restore semantics).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.tree_snapshot import (
    SKIP_DIRS,
    restore_py_tree,
    snapshot_py_tree,
)


def _tree(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (root / "notes.txt").write_text("not python\n", encoding="utf-8")
    return root


def test_snapshot_captures_only_py_files_sorted(tmp_path: Path):
    _tree(tmp_path)
    snap = snapshot_py_tree(tmp_path)
    assert snap == {"pkg/a.py": "x = 1\n", "pkg/b.py": "y = 2\n"}
    # Deterministic: same tree in -> same mapping out, twice.
    assert snapshot_py_tree(tmp_path) == snap


def test_snapshot_skips_cache_and_vcs_dirs(tmp_path: Path):
    _tree(tmp_path)
    for skip in (".git", "__pycache__", ".apex", "venv"):
        (tmp_path / skip).mkdir()
        (tmp_path / skip / "hidden.py").write_text("z = 3\n", encoding="utf-8")
    snap = snapshot_py_tree(tmp_path)
    assert set(snap) == {"pkg/a.py", "pkg/b.py"}
    # The skip set itself stays the session's historical one.
    assert {".git", ".apex", "__pycache__", "node_modules"} <= SKIP_DIRS


def test_restore_reverts_modified_created_and_deleted(tmp_path: Path):
    _tree(tmp_path)
    before = snapshot_py_tree(tmp_path)
    # Modify one, create one, delete one — the three restore shapes.
    (tmp_path / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    (tmp_path / "pkg" / "new.py").write_text("n = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").unlink()
    after = snapshot_py_tree(tmp_path)

    restore_py_tree(tmp_path, before, after)

    assert (tmp_path / "pkg" / "a.py").read_text() == "x = 1\n"   # reverted
    assert (tmp_path / "pkg" / "b.py").read_text() == "y = 2\n"   # recreated
    assert not (tmp_path / "pkg" / "new.py").exists()             # deleted
    assert snapshot_py_tree(tmp_path) == before  # byte-for-byte round trip


def test_restore_leaves_unchanged_files_untouched(tmp_path: Path):
    # An unchanged file is skipped (never rewritten), so mtimes/bytes of the
    # untouched part of the tree are not churned by a rollback.
    _tree(tmp_path)
    before = snapshot_py_tree(tmp_path)
    mtime = (tmp_path / "pkg" / "b.py").stat().st_mtime_ns
    (tmp_path / "pkg" / "a.py").write_text("x = 7\n", encoding="utf-8")
    restore_py_tree(tmp_path, before, snapshot_py_tree(tmp_path))
    assert (tmp_path / "pkg" / "b.py").stat().st_mtime_ns == mtime


def test_empty_tree_edges(tmp_path: Path):
    # Empty edges: an empty dir snapshots to {}, and restoring two empty
    # snapshots is a clean no-op.
    assert snapshot_py_tree(tmp_path) == {}
    restore_py_tree(tmp_path, {}, {})
    assert snapshot_py_tree(tmp_path) == {}


def test_develop_session_delegators_reuse_the_leaf(tmp_path: Path):
    # The session's historical names must remain thin delegators over THIS leaf,
    # so both backstops (session-level and campaign-level) capture/restore with
    # identical semantics forever.
    from app.engine.develop_session import _restore_snapshot, _snapshot

    _tree(tmp_path)
    before = _snapshot(tmp_path)
    assert before == snapshot_py_tree(tmp_path)
    (tmp_path / "pkg" / "a.py").write_text("x = 42\n", encoding="utf-8")
    _restore_snapshot(tmp_path, before, _snapshot(tmp_path))
    assert (tmp_path / "pkg" / "a.py").read_text() == "x = 1\n"
