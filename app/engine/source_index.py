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
from app.tools.python_structure import parse_cached, parse_cached_text

# The union of source_index's own former except-clause
# (``SyntaxError, ValueError, RecursionError, MemoryError``) and
# ``python_structure._parse_tree``'s (which additionally catches ``OSError`` —
# a read failure mid-parse). Routing the per-file parses below through the
# SHARED ``parse_cached``/``parse_cached_text`` cache (so a file already parsed
# by ``dead-params``'s scan in the same session is not re-parsed here, and vice
# versa) means this module's own degrade-to-``None`` guard must cover the WIDER
# set too, or an exception class the cache itself already tolerates internally
# could still surface here if that internal handling ever changes shape.
# Reconciled once, named once, so the caches can never silently drift apart again.
_PARSE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    SyntaxError, OSError, ValueError, RecursionError, MemoryError,
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

        The parse itself is routed through
        :func:`~app.tools.python_structure.parse_cached_text` — the process-level,
        ``(absolute path, mtime)``-keyed AST cache the ``dead-params`` scan
        (``_collect_dead_param_defs``, via ``parse_cached``) also reads from — so
        a file already parsed by one subsystem in the same session is not parsed
        again by the other, in either order. The ``_text`` entry point parses the
        SOURCE THIS WALK ALREADY READ (never a second disk read), preserving the
        invariant that each ``IndexedModule``'s ``tree`` is the parse of its own
        ``source`` — one read, one parse, one cache. The wider
        :data:`_PARSE_EXCEPTIONS` degrade guard below reconciles the two caches'
        except-clause sets so a file that trips ``OSError`` (a class only
        ``python_structure``'s own parser previously caught) still degrades to
        ``tree=None`` here too, rather than raising.

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
                tree: ast.Module | None = parse_cached_text(root / rel, source)
            except _PARSE_EXCEPTIONS:
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


def all_parsed_trees(project_root: str | Path) -> dict[str, ast.Module]:
    """Every project module's parsed tree — own code PLUS tests/fixtures — built
    with as little duplicate work as the two shared caches allow.

    This is the drop-in replacement for a caller's own uncached ``_py_files`` +
    ``ast.parse`` fallback (e.g. ``inline_function._suggest_trees(None)``): the
    OWN modules' trees are taken straight from :func:`indexed_project` (already
    read and parsed once by :meth:`SourceIndex.build`, itself routed through
    :func:`~app.tools.python_structure.parse_cached` — zero extra I/O or parsing
    here), and every RESIDUAL file — the tests/fixtures/non-library modules the
    own-set gate excludes — is ALSO routed through the same per-file
    ``(absolute path, mtime_ns)``-keyed ``parse_cached``. So the residual set is
    read+parsed at most ONCE per process while its files are unchanged: the
    second and every later call in the same pass/campaign (``suggest_inlines``
    runs at least twice per ``inline-helpers`` pass — fitness + moves) is all
    cache hits, exactly the discipline Stage-1 item 10 applied to the own set.

    The residual POPULATION is unchanged: the same rel set the index's single
    walk captured (``all_sources`` minus the own rels) — never narrowed. A
    module that doesn't parse (own OR residual) is silently ABSENT from the
    returned mapping — ``parse_cached`` degrades unreadable/unparseable files to
    ``None``, which is skipped here, identical to the old fallback's
    ``except ...: continue``; so a caller iterating the result never has to
    special-case a ``None`` tree.

    MID-CAMPAIGN-EDIT WINDOW (deliberate, fail-safe): ``parse_cached`` reads the
    file from DISK itself, so a residual file edited between the index's
    fingerprint walk and this parse yields the NEWER disk bytes here (fresher
    than the index's cached text, never staler), and a file DELETED in that
    window degrades to ``None`` → excluded (the old cached-text parse would have
    kept it). Both divergences point the safe way: a scan population is at worst
    momentarily smaller/fresher, and any plan built against content that no
    longer matches disk is refused downstream by ``apply_rename``'s
    ``_stale_plan_reason`` gate — the standing last line of defense."""
    index = indexed_project(project_root)
    root = Path(project_root)
    trees: dict[str, ast.Module] = {
        m.rel: m.tree for m in index.modules if m.tree is not None
    }
    own_rels = {m.rel for m in index.modules}
    for rel in sorted(index.all_sources):
        if rel in own_rels:
            continue
        try:
            tree = parse_cached(root / rel)
        except _PARSE_EXCEPTIONS:
            continue
        if tree is not None:
            trees[rel] = tree
    return trees
