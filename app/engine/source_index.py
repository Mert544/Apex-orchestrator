"""Deterministic source index — parse a project's own modules once, reuse everywhere.

Apex's scans (duplication, security, rename feasibility, …) each re-enumerate,
re-read, and re-parse every project module. On a large repo, running many
candidate scans during ``apex develop`` means parsing the same files dozens of
times. This module builds the parse ONCE: a sorted, deterministic view of the
project's OWN (non-fixture, non-test) ``.py`` modules, each with its source text
and its parsed ``ast.Module`` (or ``None`` when the module doesn't parse).

A memoized factory, :func:`indexed_project`, hands back the same index across
repeated scans, rebuilding only when the project's files actually change (tracked
by a ``(path, mtime)`` fingerprint) or when the caller asks for a ``fresh`` build.
That keeps repeated scans cheap while staying correct after files are edited
mid-campaign.

Deterministic, stdlib-only. mtimes are used ONLY to decide staleness — they are
never part of the index's compared output.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.cross_file_rename import _SKIPPED_DIRS, _py_files


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded — those modules are not the project's
    own production surface. A LOCAL copy (mirroring ``dedup.py``) avoids importing
    it from health_score, which would create a health_score import cycle."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


@dataclass
class IndexedModule:
    """One of the project's own modules: its rel path, source, and parsed tree.

    ``tree`` is ``None`` when the source does not parse (a syntactically broken
    module is indexed, not skipped — callers that need a parse check ``parsed``)."""

    rel: str
    source: str
    tree: ast.Module | None

    @property
    def parsed(self) -> bool:
        """Did this module parse? (Cheap — just a None check on ``tree``.)"""
        return self.tree is not None


@dataclass
class SourceIndex:
    """A parse-once view of a project's own modules, in sorted ``rel`` order."""

    modules: list[IndexedModule] = field(default_factory=list)

    @classmethod
    def build(cls, project_root: str | Path) -> SourceIndex:
        """Enumerate, read, and parse the project's own non-fixture modules once.

        Modules are enumerated via :func:`_py_files` (which already skips agent
        worktrees, ``.git``, virtualenvs, etc.), fixtures/tests are dropped, each
        source is read once and parsed once (``SyntaxError`` → ``tree=None``), and
        the result is stored in deterministic sorted ``rel`` order."""
        modules: list[IndexedModule] = []
        for rel, source in _py_files(Path(project_root)):
            if _is_fixture_path(rel):
                continue
            try:
                tree: ast.Module | None = ast.parse(source)
            except (SyntaxError, ValueError):
                tree = None
            modules.append(IndexedModule(rel=rel, source=source, tree=tree))
        modules.sort(key=lambda m: m.rel)
        return cls(modules=modules)

    def own_sources(self) -> list[tuple[str, str]]:
        """``(rel, source)`` for each indexed module — a drop-in for the common
        pattern of iterating ``_py_files`` and filtering fixtures."""
        return [(m.rel, m.source) for m in self.modules]

    def parsed_modules(self) -> list[IndexedModule]:
        """Only the modules that parsed (``tree is not None``)."""
        return [m for m in self.modules if m.parsed]

    def get(self, rel: str) -> IndexedModule | None:
        """The indexed module for ``rel``, or ``None`` if it isn't indexed."""
        for m in self.modules:
            if m.rel == rel:
                return m
        return None


def _fingerprint(project_root: Path) -> tuple[tuple[str, float], ...]:
    """A staleness fingerprint: the sorted ``(rel, mtime)`` of every project ``.py``
    file (respecting the same skipped dirs as the enumerator). Used ONLY to decide
    whether a cached index is stale — never stored in the index's compared data."""
    out: list[tuple[str, float]] = []
    for path in sorted(project_root.rglob("*.py")):
        rel = path.relative_to(project_root).as_posix()
        if any(part in _SKIPPED_DIRS for part in Path(rel).parts):
            continue
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        out.append((rel, mtime))
    return tuple(out)


# Memoization keyed by resolved project root: (fingerprint, SourceIndex).
_INDEX_CACHE: dict[str, tuple[tuple[tuple[str, float], ...], SourceIndex]] = {}


def indexed_project(project_root: str | Path, *, fresh: bool = False) -> SourceIndex:
    """Return a cached :class:`SourceIndex` for ``project_root``, rebuilding it when
    ``fresh`` is set or when the project's ``(path, mtime)`` fingerprint has changed
    since the cached build. This is what makes repeated scans cheap while staying
    correct after files are edited mid-campaign."""
    root = Path(project_root).resolve()
    key = str(root)
    fingerprint = _fingerprint(root)

    if not fresh:
        cached = _INDEX_CACHE.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

    index = SourceIndex.build(root)
    _INDEX_CACHE[key] = (fingerprint, index)
    return index
