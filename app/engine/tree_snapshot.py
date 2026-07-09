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


# Codec used to move between on-disk bytes and the in-memory ``str`` snapshot.
# ``surrogateescape`` is a LOSSLESS bytes<->str round trip (the same scheme
# ``os.fsdecode``/``os.fsencode`` use for filesystem paths): any byte sequence
# decodes to a ``str`` and ``str.encode(_CODEC, errors=_ERRORS)`` recovers the
# EXACT original bytes, because decoding never performs newline translation —
# only a text-mode *file object* (``Path.read_text``/``write_text``) does
# that, and this module never opens one. So a CRLF byte pair decodes to the
# two literal characters ``"\r\n"`` (not collapsed to ``"\n"``), a UTF-8 BOM
# decodes to the literal ``"﻿"`` character, and a missing trailing
# newline stays missing — all restored byte-for-byte by :func:`restore_py_tree`
# — while the snapshot stays a plain ``dict[str, str]``, so every existing
# consumer that diffs/compares these snapshots as text (``develop_session.
# _diff_snapshots``'s ``difflib.unified_diff``, the objective-compiler
# end-of-campaign backstop's dict equality) keeps working unmodified.
_CODEC = "utf-8"
_ERRORS = "surrogateescape"


def snapshot_py_tree(root: Path) -> dict[str, str]:
    """Map of ``rel_posix_path -> source`` for every ``.py`` file under ``root``.

    Skips caches/vcs/venv dirs (:data:`SKIP_DIRS`) so the snapshot is a stable
    function of the project's own source. Walked in sorted order for a
    deterministic file set; an unreadable file is simply omitted. Captured by
    reading raw bytes and decoding losslessly (see ``_CODEC``/``_ERRORS``
    above) so CRLF line endings, a BOM, and a missing trailing newline all
    round-trip exactly through :func:`restore_py_tree`, without giving up the
    ``str`` contract existing callers rely on."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            out[path.relative_to(root).as_posix()] = raw.decode(_CODEC, _ERRORS)
    return out


def restore_py_tree(root: Path, before: dict[str, str],
                    after: dict[str, str]) -> list[str]:
    """Roll the tree back to the ``before`` snapshot, byte-for-byte.

    Mirrors ``apply_rename``'s rollback semantics: every file MODIFIED since the
    ``before`` capture is rewritten to its exact pre-change bytes, and every file
    CREATED since (present in ``after`` but absent from ``before``) is deleted.
    Walked in sorted order for determinism; a file deleted since the capture is
    recreated from ``before``. Restoration re-encodes with the same lossless
    codec used to capture (``_CODEC``/``_ERRORS``) and writes raw bytes
    (``write_bytes``) so CRLF/BOM/no-trailing-newline originals are restored
    exactly, not normalized. Best-effort per path (an unwritable path is
    skipped, so the rest of the tree still restores) — but a skip is no longer
    silent: this returns the SORTED list of rel-posix paths whose
    ``write_bytes``/``unlink`` FAILED (empty on a full, successful restore), so
    a caller can fail closed on whatever it was about to claim (e.g. a
    "rolled_back" proof-of-fix correction) rather than asserting the tree is
    back at baseline when it provably isn't. ADDITIVE: every existing caller
    that ignores the return value behaves exactly as before."""
    failed: list[str] = []
    for rel in sorted(set(before) | set(after)):
        path = root / rel
        if rel in before:
            if after.get(rel) == before[rel]:
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(before[rel].encode(_CODEC, _ERRORS))
            except OSError:
                failed.append(rel)
        else:
            # Created since the capture — remove it to restore the baseline tree.
            try:
                path.unlink()
            except OSError:
                failed.append(rel)
    return failed
