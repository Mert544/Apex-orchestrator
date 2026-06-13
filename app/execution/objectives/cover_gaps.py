"""Self-registering objective: cover-gaps.

Turn an UNTESTED module into the ACTION of writing a characterization test for
it. The transform lives in :mod:`app.execution.cover_gaps`; this module selects
the untested modules and registers the objective.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.health_score import _is_fixture_path
    from app.execution.cover_gaps import plan_cover_gaps
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(str(project_root)).profile()
    untested = [m for m in (getattr(profile, "untested_modules", []) or [])
                if isinstance(m, str) and m.endswith(".py") and not _is_fixture_path(m)]
    return [rel for rel in untested
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
