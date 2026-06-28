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

from app.execution.cross_file_rename import (
    _SKIPPED_DIRS,
    _is_non_library_file,
    _py_files,
)


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
    """A parse-once view of a project's own modules, in sorted ``rel`` order.

    ``all_sources`` is the FULL, tests+fixtures-INCLUSIVE raw-source map captured in
    the SAME single ``_py_files`` walk that builds ``modules`` (zero extra I/O). It
    exists for the soundness-critical whole-project scans — the ``@typing.final``
    family (add-final / seal-final-method / add-slots / synthesize-dunders) — where a
    class subclassed, or a method overridden, ONLY in a test file is a REAL
    subclass/override that ``@final`` breaks for a type checker (a pure runtime no-op
    a pytest suite can never catch). Those scans MUST see tests, so they read
    ``all_sources`` rather than the own-only ``modules`` (which DROPS tests/fixtures
    — using it would manufacture a false 'final'). Both views come from one walk and
    never diverge; the own-only ``modules`` / ``own_sources`` / ``get`` are
    unchanged."""

    modules: list[IndexedModule] = field(default_factory=list)
    all_sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, project_root: str | Path) -> SourceIndex:
        """Enumerate, read, and parse the project's own non-fixture modules once.

        Modules are enumerated via :func:`_py_files` (which already skips agent
        worktrees, ``.git``, virtualenvs, etc.), fixtures/tests are dropped, and
        NON-LIBRARY files (packaging / config / task / generated scripts —
        ``setup.py``, ``docs/conf.py``, ``noxfile.py``, ``conftest.py``, …) are
        dropped via the shared
        :func:`~app.execution.cross_file_rename._is_non_library_file` denylist gate
        (the same gate the single-file objectives use to refuse them) so a config /
        packaging script is never indexed as project source. Each source is read
        once and parsed once (``SyntaxError`` → ``tree=None``), and the result is
        stored in deterministic sorted ``rel`` order.

        The SAME walk ALSO captures EVERY ``(rel, source)`` pair — tests and
        fixtures INCLUDED, recorded BEFORE the fixture / non-library ``continue`` —
        into ``all_sources``, so the tests-inclusive whole-project scan
        :func:`~app.execution.freeze_dataclass.all_module_sources` gets the full raw
        source set without a SECOND disk walk. This is zero extra I/O (the walk
        already happens); the own-only ``modules`` list and its accessors are
        byte-identical to before.

        The gate is BASENAME-only on purpose (see ``_is_non_library_file``): real
        PEP-420 namespace-package modules with no ``__init__.py`` (``app/intent``,
        ``app/k8s``, ``scripts/*.py``, …) stay indexed, so the duplication /
        complexity / dead-code scans built on this index keep seeing them."""
        root = Path(project_root)
        modules: list[IndexedModule] = []
        all_sources: dict[str, str] = {}
        for rel, source in _py_files(root):
            all_sources[rel] = source  # tests+fixtures INCLUDED — before the gate
            if _is_fixture_path(rel) or _is_non_library_file(rel):
                continue
            try:
                tree: ast.Module | None = ast.parse(source)
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                tree = None
            modules.append(IndexedModule(rel=rel, source=source, tree=tree))
        modules.sort(key=lambda m: m.rel)
        return cls(modules=modules, all_sources=all_sources)

    def all_source_texts(self) -> dict[str, str]:
        """A COPY of the FULL ``{rel: source}`` map — tests and fixtures INCLUDED —
        in deterministic sorted ``rel`` order.

        This is the tests-INCLUSIVE raw-source set the ``@final`` family scans need
        (a test-only subclass/override is a real one ``@final`` breaks). It is a
        fresh copy, so a caller may override one entry (e.g. the in-flight module's
        exact rewritten bytes) without mutating the cache. ``own_sources`` /
        ``parsed_modules`` / ``get`` are unaffected — they stay own-only."""
        return {rel: self.all_sources[rel] for rel in sorted(self.all_sources)}

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
