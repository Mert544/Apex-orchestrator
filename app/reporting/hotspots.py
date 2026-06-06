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


from app.tools.code_metrics import hotspot_risk  # re-export (single source)


def build_hotspots(project_root: str, limit: int = 15) -> list[dict[str, Any]]:
    """Rank named modules by a complexity × blast-radius ÷ tests risk score."""
    from app.tools.code_metrics import CodeMetrics
    from app.tools.project_profile import ProjectProfiler
    from app.tools.test_linker import count_test_functions

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
        # Depth-aware: count linked test *functions*, not files — a single file
        # with many real tests should pull risk down, a lone stub should not.
        tests = count_test_functions(project_root, coverage.get(m, []) or [])
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
