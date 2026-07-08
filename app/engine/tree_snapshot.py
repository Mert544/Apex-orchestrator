"""Byte-level ``.py`` tree snapshot + restore — the rollback backstops' shared floor.

Extracted VERBATIM from :mod:`app.engine.develop_session` (its ``_snapshot`` /
``_restore_snapshot`` helpers) so the END-OF-CAMPAIGN regression backstop in
:mod:`app.engine.objective_compiler` can reuse the exact same capture/restore
semantics WITHOUT importing ``develop_session`` — which imports
``objective_compiler`` at module level, so a back-edge there would form an
import cycle. This is a LEAF: stdlib-only, imports nothing from the engine, and
deterministic (sorted walks, no clock, no randomness) — same tree in, same
snapshot out; same snapshot in, same restored bytes out.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["SKIP_DIRS", "restore_py_tree", "snapshot_py_tree"]

# Directories never worth snapshotting for a diff/restore (caches, vcs, venvs,
# the .apex memory store). Skipping them keeps a snapshot — and so any backstop
# verdict derived from it — a stable function of the project's own source, not
# its incidental tooling state.
SKIP_DIRS = {".git", ".hg", ".svn", ".apex", ".venv", "venv", "__pycache__",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules",
             ".tox", "build", "dist", ".eggs"}


def snapshot_py_tree(root: Path) -> dict[str, str]:
    """Map of ``rel_posix_path -> source`` for every ``.py`` file under ``root``.

    Skips caches/vcs/venv dirs (:data:`SKIP_DIRS`) so the snapshot is a stable
    function of the project's own source. Walked in sorted order for a
    deterministic file set; an unreadable file is simply omitted."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            try:
                out[path.relative_to(root).as_posix()] = path.read_text(
                    encoding="utf-8")
            except OSError:
                continue
    return out


def restore_py_tree(root: Path, before: dict[str, str],
                    after: dict[str, str]) -> None:
    """Roll the tree back to the ``before`` snapshot, byte-for-byte.

    Mirrors ``apply_rename``'s rollback semantics: every file MODIFIED since the
    ``before`` capture is rewritten to its exact pre-change bytes, and every file
    CREATED since (present in ``after`` but absent from ``before``) is deleted.
    Walked in sorted order for determinism; a file deleted since the capture is
    recreated from ``before``. Best-effort per path (an unwritable path is
    skipped) but the common case restores the whole working tree to its captured
    baseline state."""
    for rel in sorted(set(before) | set(after)):
        path = root / rel
        if rel in before:
            if after.get(rel) == before[rel]:
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(before[rel], encoding="utf-8")
            except OSError:
                continue
        else:
            # Created since the capture — remove it to restore the baseline tree.
            try:
                path.unlink()
            except OSError:
                continue
