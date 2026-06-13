"""Self-registering objective: chain-comparison.

The transform lives in :mod:`app.execution.chain_comparison`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective chain-comparison` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.chain_comparison import plan_chain_comparison

    return [rel for rel, _src in _own_modules(project_root)
            if plan_chain_comparison(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still match chain-comparison (lower is better)."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.chain_comparison import plan_chain_comparison

    return [Move(
        operator="chain_comparison",
        target=f"{rel}:chain-comparison",
        description=f"apply chain-comparison in {rel}",
        build_plan=lambda r=rel: plan_chain_comparison(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="chain-comparison", fitness=fitness, moves=moves))
