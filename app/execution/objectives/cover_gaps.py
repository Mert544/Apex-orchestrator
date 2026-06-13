"""Self-registering objective: cover-gaps.

Turn an UNTESTED module into the ACTION of writing a characterization test for
it. The transform lives in :mod:`app.execution.cover_gaps`; this module selects
the untested modules and registers the objective.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


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
        if Path(rel).name == "__init__.py":
            continue  # package markers aren't a testable unit
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
