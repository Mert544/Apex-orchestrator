"""Complexity hotspots — the modules most worth attention.

A hotspot is a module that combines high cyclomatic complexity with a large
blast radius (many other modules import it) and thin test coverage: changing it
is both likely and risky. The risk score makes that explicit:

    risk = complexity * (1 + fan_in) / (1 + tests)

so complexity and importers push it up while linked tests pull it down. Built
from the same deterministic ProjectProfile + CodeMetrics the rest of Apex uses.
"""

from __future__ import annotations

from typing import Any


def hotspot_risk(complexity: int, fan_in: int, tests: int) -> float:
    """The hotspot risk score: complexity × blast-radius ÷ test coverage.

    High cyclomatic complexity and many importers raise it; linked tests lower
    it. Pure and deterministic so both the report and the profiler can share it
    without a circular import (this module's heavier imports are function-local).
    """
    return round(complexity * (1 + fan_in) / (1 + tests), 2)


def build_hotspots(project_root: str, limit: int = 15) -> list[dict[str, Any]]:
    """Rank named modules by a complexity × blast-radius ÷ tests risk score."""
    from app.tools.code_metrics import CodeMetrics
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(project_root).profile()
    coverage = getattr(profile, "module_to_tests", {}) or {}
    modules = [m for m in coverage.keys() if isinstance(m, str) and m.endswith(".py")]
    if not modules:
        return []

    fan_in: dict[str, int] = {}
    for _src, dst in getattr(profile, "dependency_edges", []) or []:
        fan_in[dst] = fan_in.get(dst, 0) + 1

    metrics = CodeMetrics(project_root).for_modules(modules)
    rows: list[dict[str, Any]] = []
    for m in modules:
        mm = metrics.get(m)
        if mm is None:
            continue
        fi = fan_in.get(m, 0)
        tests = len(coverage.get(m, []) or [])
        risk = hotspot_risk(mm.complexity, fi, tests)
        rows.append({
            "module": m,
            "loc": mm.loc,
            "complexity": mm.complexity,
            "fan_in": fi,
            "tests": tests,
            "risk": risk,
        })

    rows.sort(key=lambda r: (-r["risk"], -r["complexity"], r["module"]))
    return rows[:limit]


def render_hotspots_markdown(rows: list[dict[str, Any]]) -> str:
    """Render the hotspot ranking as a markdown table."""
    if not rows:
        return "# Complexity hotspots\n\n_No named modules to analyze._\n"
    lines = [
        "# Complexity hotspots",
        "",
        f"Top {len(rows)} modules by risk = complexity × (1 + fan-in) ÷ (1 + tests).",
        "",
        "| Module | LOC | Complexity | Fan-in | Tests | Risk |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['module']} | {r['loc']} | {r['complexity']} | "
            f"{r['fan_in']} | {r['tests']} | {r['risk']} |"
        )
    lines.append("")
    return "\n".join(lines)
