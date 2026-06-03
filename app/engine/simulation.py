"""Risk-free simulation of autonomous improvement.

Autonomy is only adoptable if you can see what it would do *before* it touches
your code. This runs the full self-improvement loop on a throwaway copy of the
project — applying, verifying, and measuring there — then reports the predicted
before/after and discards the copy. Your real working tree is never touched.

It's the honest preview: "here is exactly what `apex evolve` would achieve,
proven by actually doing it on a disposable clone."
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.engine.evolution import EvolutionResult, EvolutionLoop

# Directories/files never worth copying into the sandbox clone.
_IGNORE = shutil.ignore_patterns(
    ".git", ".apex", "__pycache__", "*.pyc", ".venv", "venv",
    ".pytest_cache", ".ruff_cache", "node_modules", ".mypy_cache", "*.egg-info",
)


def simulate_evolution(
    project_root: str | Path,
    max_cycles: int = 3,
    max_apply_per_cycle: int = 5,
    objective: str | None = None,
) -> EvolutionResult:
    """Run the evolve loop on a disposable copy; return the predicted result.

    The original project is never modified. Verification runs against the copy's
    own tests, so the prediction reflects real, test-gated outcomes.
    """
    src = Path(project_root)
    with tempfile.TemporaryDirectory(prefix="apex-sim-") as tmp:
        dest = Path(tmp) / "clone"
        shutil.copytree(src, dest, ignore=_IGNORE, symlinks=False)
        loop = EvolutionLoop(
            dest,
            mode="supervised",          # apply + verify, never commit
            max_cycles=max_cycles,
            max_apply_per_cycle=max_apply_per_cycle,
            verify=True,
            objective=objective,
        )
        return loop.run()


def render_simulation_markdown(result: EvolutionResult, project_root: str) -> str:
    """Render the simulation as a predicted-outcome report."""
    b, a = result.before, result.after
    lines = [f"# Apex — simulated improvement of `{project_root}` (no files changed)", ""]
    lines.append(
        f"_Predicted by running the evolve loop on a disposable copy: "
        f"{result.cycles_run} cycle(s), **{result.applied}** fix(es) would apply, "
        f"{result.rolled_back} rolled back._"
    )
    lines.append("")
    lines.append("## Predicted before → after")
    lines.append(f"- **Security findings:** {b.get('security_findings', 0)} → {a.get('security_findings', 0)}")
    lines.append(f"- **Open safe fixes:** {b.get('executable_fixes', 0)} → {a.get('executable_fixes', 0)}")
    lines.append(f"- **Mean ROI:** {b.get('mean_roi', 0)} → {a.get('mean_roi', 0)}")
    lines.append("")
    resolved = result.roadmap_diff.get("dropped", [])
    if resolved:
        lines.append("## Would resolve")
        for c in resolved[:12]:
            lines.append(f"- {c['title']}")
        lines.append("")
    lines.append("_Nothing above was applied to your project. Run `apex evolve` to do it for real._")
    lines.append("")
    return "\n".join(lines)
