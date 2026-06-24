"""Self-registering objective: cover-gaps.

Turn an UNTESTED module into the ACTION of writing a characterization test for
it. The transform lives in :mod:`app.execution.cover_gaps`; this module selects
the untested modules and registers the objective.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
# Reuse the wave's single source of truth for "importable library module, not a
# packaging/config/generated script" — NOT a copy. A direct objective->objective
# import is safe here (both are leaf objective modules; neither imports the other,
# and wire_module_exports does not import cover_gaps), verified by
# ``python -c "import app.execution.objectives.cover_gaps"``. If a cycle ever
# appears, lift _is_library_module/_SCRIPT_DENYLIST into a shared
# app/execution/library_module.py and import THAT from both.
from app.execution.objectives.wire_module_exports import _is_library_module


def _is_coverable_target(project_root: Path, rel: str) -> bool:
    """True when ``rel`` is a PUBLIC LIBRARY module worth a characterization test.

    Reuses the wire-module-exports library-module eligibility (skips packaging /
    config / generated scripts — ``setup.py``, ``conf.py``, ``conftest.py``,
    ``_version.py``, ``version.py``, ``manage.py``, ``noxfile.py``, ``tasks.py`` —
    and any module whose containing directory has no ``__init__.py``) and
    additionally skips a PRIVATE module (basename starts with ``_``). A generated
    test pinning a private/config/generated module's incidental behaviour is the
    low-value noise the pilot found on mature repos (``docs.conf``,
    ``funcy._inspect``, ``humanize._version``): a maintainer rejects it. A
    non-eligible module is simply not a candidate — an honest no-op, never a
    blocker. The ``_``-prefix test also subsumes the old ``__init__.py`` /
    ``__main__.py`` package-marker skip (covering a package marker is low value)."""
    name = Path(rel).name
    if name.startswith("_"):  # private module OR __init__/__main__/_version etc.
        return False
    return _is_library_module(project_root, rel)


def _test_sources(root: Path) -> str:
    """The concatenated source of every real test file (tests/.. and any
    ``test_*.py``), excluding example/fixture trees. Read once per call — far
    cheaper than a full project profile, which only needed this for linkage."""
    skip = ("examples/", "example/", "fixtures/", ".claude/")
    chunks: list[str] = []
    for path in root.rglob("test_*.py"):
        rel = path.relative_to(root).as_posix().lower()
        if any(rel.startswith(s) or f"/{s}" in f"/{rel}" for s in skip):
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def _untested_own_modules(project_root: str | Path) -> list[str]:
    """Own modules that no real test references — the gaps to cover.

    A lean, index-based replacement for ``ProjectProfiler.profile()`` (which
    shells out to git per module and took ~200s on Apex itself): use the cached
    source index for the own modules, then mark a module *tested* when its dotted
    import path appears (word-bounded, so ``foo`` ≠ ``foobar``) anywhere in the
    test sources. Linkage-by-import, same spirit as the profiler's test linker,
    but without the whole-project scan."""
    from app.engine.source_index import indexed_project

    root = Path(project_root)
    tests = _test_sources(root)
    untested: list[str] = []
    for rel, _src in indexed_project(root).own_sources():
        # Selection policy: only PUBLIC LIBRARY modules are candidates — drop
        # packaging/config/generated scripts, modules with no package __init__,
        # and any `_`-prefixed (private) module (which also covers __init__.py /
        # __main__.py package markers). Done FIRST: an ineligible module is never
        # a candidate (cheaper, intent reads clearly), an honest no-op.
        if not _is_coverable_target(root, rel):
            continue
        dotted = rel[:-3].replace("/", ".") if rel.endswith(".py") else rel
        # Form A: `import a.b.foo` / `from a.b.foo import …` — the dotted path
        # appears verbatim (word-bounded, so `foo` ≠ `foobar`).
        if re.search(re.escape(dotted) + r"(?![A-Za-z0-9_])", tests):
            continue
        # Form B: `from a.b import foo` — the parent package is imported-from and
        # the bare stem is in its (single-line) import list.
        parent, _, stem = dotted.rpartition(".")
        if parent and re.search(
                r"from\s+" + re.escape(parent) + r"\s+import\b[^\n()]*\b"
                + re.escape(stem) + r"\b", tests):
            continue
        untested.append(rel)
    return untested


def _modules(project_root: str | Path) -> list[str]:
    from app.execution.cover_gaps import plan_cover_gaps

    return [rel for rel in _untested_own_modules(project_root)
            if plan_cover_gaps(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still lack a test we can generate."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.cover_gaps import plan_cover_gaps

    return [Move(
        operator="cover_gaps", target=f"{rel}:cover-gaps",
        description=f"write a characterization test for {rel}",
        build_plan=lambda r=rel: plan_cover_gaps(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="cover-gaps", fitness=fitness, moves=moves))
