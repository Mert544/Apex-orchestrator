"""Cross-language co-change coupling — the "keep these in sync" seam git reveals
ACROSS the Python / non-Python boundary.

Apex's ``project_profile.change_coupling`` already surfaces temporal coupling, but
only between Python module PAIRS: it can't see that ``app/api.py`` and
``web/client.js`` keep changing in the SAME commit, because the JS side is out of
its Python-only analysis scope. On a polyglot repo that is exactly the relationship
worth naming — Apex can't deep-analyse the non-Python file, but git history still
shows, factually, that the two move together and so must be kept in sync.

This module extracts that one cross-boundary signal and nothing more. It is
deliberately neutral and pure:

  - ONE ``git log --name-only`` pass groups each commit's changed files; for every
    commit we count co-change for each (python_file, non_python_file) pair — never
    one subprocess per file;
  - the non-Python classification reuses ``app.tools.polyglot_facts._LANGUAGE_BY_EXT``
    (the same explicit allow-list the polyglot facts layer uses), so a file is
    "the other side" only when it is recognised non-Python source — never a lockfile
    or an unknown extension;
  - the canonical ``app.engine.skip_dirs.is_skipped`` predicate is the ONLY skip set
    (no rolled-own exclusions), so worktree copies / build output never leak in;
  - SAME-language pairs (py<->py, js<->js) are NEVER emitted — this is the
    cross-boundary signal ``change_coupling`` structurally cannot produce;
  - ranking is deterministic: ``(-cochanges, py, other)`` — same repo state, same
    output, no time/random anywhere; any git error (non-git dir, missing git,
    timeout) degrades to ``[]`` and never raises.

Deterministic, stdlib + git only, no LLM.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from app.engine.skip_dirs import is_skipped
from app.tools.polyglot_facts import _LANGUAGE_BY_EXT

__all__ = ["CrossLink", "cross_language_coupling", "render_cross_language_markdown"]

# Python is the IN-scope side; everything Apex deep-analyses. A pair is only
# cross-boundary when exactly one member is Python, so these never appear as the
# ``other`` file.
_PYTHON_EXTENSIONS = {".py", ".pyi"}

# A sweeping reformat / vendored-tree commit couples everything and means nothing;
# excluding huge commits keeps the signal about genuinely co-evolving files.
_MAX_COMMIT_FILES = 50

# How far back to read. Bounded so the single subprocess stays fast and the
# result is stable for a given repo state.
_COMMIT_WINDOW = 1000


@dataclass(frozen=True)
class CrossLink:
    """One cross-boundary co-change pair: a Python file and a non-Python source
    file that keep changing in the same commits.

    ``py`` is the (root-relative, POSIX) Python file; ``other`` is the
    root-relative non-Python source file; ``other_language`` is its normalised
    language name (from the shared ``_LANGUAGE_BY_EXT`` allow-list); ``cochanges``
    is the number of commits that touched BOTH.
    """

    py: str
    other: str
    other_language: str
    cochanges: int


def _classify(rel: str) -> tuple[bool, str | None]:
    """Classify a root-relative path as ``(is_python, language_or_None)``.

    ``is_python`` is True for ``.py``/``.pyi``. Otherwise ``language`` is the
    normalised non-Python source language when the extension is in the shared
    allow-list, else ``None`` (unknown/binary/data — never part of a pair).
    Pure: a name check only, no I/O.
    """
    ext = Path(rel).suffix.lower()
    if ext in _PYTHON_EXTENSIONS:
        return True, None
    return False, _LANGUAGE_BY_EXT.get(ext)


def cross_language_coupling(
    root: str, *, min_cochanges: int = 3, limit: int = 5
) -> list[CrossLink]:
    """The top ``limit`` cross-boundary co-change pairs in ``root``'s git history.

    ONE ``git log --name-only`` pass groups each commit's changed files. Within a
    commit we split files into Python and recognised non-Python source (skipping
    excluded directories via ``is_skipped``), then count co-change for every
    (python_file, non_python_file) pair — so only CROSS-boundary pairs are ever
    counted (py<->py and js<->js are structurally excluded). Mega-commits
    (> ``_MAX_COMMIT_FILES`` files) are ignored.

    Keep only pairs with ``cochanges >= min_cochanges``, rank deterministically by
    ``(-cochanges, py, other)`` and return the strongest ``limit``.

    Pure and total: any git failure (non-git dir, missing git, timeout, non-zero
    exit) degrades to ``[]`` and never raises; the result is identical for a given
    repo state.
    """
    if min_cochanges <= 0 or limit <= 0:
        return []
    root_path = Path(root)
    if not root_path.exists():
        return []
    try:
        out = subprocess.run(
            ["git", "log", "--format=@commit@%H", "--name-only",
             "-n", str(_COMMIT_WINDOW)],
            cwd=root_path, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return []
    if out.returncode != 0:
        return []

    # Group changed files per commit. A "@commit@<sha>" marker line opens each
    # commit (the marker prefix needs a ``%H`` so git accepts the format string);
    # subsequent non-empty lines are its changed paths.
    commits: list[list[str]] = []
    current: list[str] = []
    started = False
    for raw in out.stdout.splitlines():
        line = raw.strip()
        if line.startswith("@commit@"):
            if started:
                commits.append(current)
            current, started = [], True
        elif line:
            current.append(line)
    if started:
        commits.append(current)

    # (py, other) -> cochanges; (py, other) -> language (stable, from path).
    pair_counts: dict[tuple[str, str], int] = {}
    pair_lang: dict[tuple[str, str], str] = {}
    for files in commits:
        if not 2 <= len(files) <= _MAX_COMMIT_FILES:
            continue
        pys: set[str] = set()
        others: dict[str, str] = {}  # other_path -> language
        for rel in files:
            if is_skipped(rel):
                continue
            is_py, lang = _classify(rel)
            if is_py:
                pys.add(rel)
            elif lang is not None:
                others[rel] = lang
        if not pys or not others:
            continue
        for py, other in product(sorted(pys), sorted(others)):
            key = (py, other)
            pair_counts[key] = pair_counts.get(key, 0) + 1
            pair_lang[key] = others[other]

    links = [
        CrossLink(py=py, other=other, other_language=pair_lang[(py, other)],
                  cochanges=n)
        for (py, other), n in pair_counts.items()
        if n >= min_cochanges
    ]
    links.sort(key=lambda link: (-link.cochanges, link.py, link.other))
    return links[:limit]


def render_cross_language_markdown(links: list[CrossLink]) -> str:
    """A short clause naming the cross-boundary pairs to keep in sync.

    Empty string when there are none, so callers can append it unconditionally and
    an all-Python (or single-commit) repo's output stays byte-identical.
    """
    if not links:
        return ""
    parts = []
    for link in links:
        word = "co-change" if link.cochanges == 1 else "co-changes"
        parts.append(
            f"`{link.py}` ↔ `{link.other}` "
            f"({link.other_language}, {link.cochanges} {word})"
        )
    return "Cross-language coupling (keep in sync): " + "; ".join(parts) + "."
