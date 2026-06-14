"""Self-registering objective: dedup-total-return.

The control-flow half of the dedup gap. The base ``dedup`` objective
(:func:`app.execution.dedup_extract.plan_dedup_extract`) lifts an exact-duplicate
block into a shared helper only when the run ends in a plain statement or a
single TAIL return; the diagnosis of Apex's own duplicates showed the largest
remaining "detect >> act" gap is blocks that return from the MIDDLE (a guard
return, an all-returning ``if/else``). This objective closes the provably-safe
slice of that gap: an exact-duplicate block whose EVERY exit path returns
(:func:`app.execution.dedup_total_return._always_returns`) lifts verbatim into a
returning helper, each copy becoming ``return _shared_n(...)``.

It pairs the same exact-duplicate detector the base objective uses
(:func:`app.engine.dedup.find_duplicates`) with the reviewed transform
(:func:`app.execution.dedup_total_return.plan_dedup_total_return`), and acts ONLY
on the blocks dedup_extract leaves behind — so the two never contend for the same
move. Not expensive: the exact-dup detector is the same one the fast board
already runs for ``dedup``.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _actionable_blocks(project_root: str | Path) -> list:
    """Exact-duplicate blocks the total-return extraction can act on — a
    total-return block whose plan produces a real rewrite (empty ``new_contents``
    means dedup_extract already covers it, or it is unsafe; either way skip)."""
    from app.engine.dedup import find_duplicates
    from app.execution.dedup_total_return import plan_dedup_total_return

    return [b for b in find_duplicates(str(project_root))
            if plan_dedup_total_return(project_root, b).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many total-return duplicate blocks can still be lifted."""
    return float(len(_actionable_blocks(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.dedup_total_return import plan_dedup_total_return

    out = []
    for i, block in enumerate(_actionable_blocks(project_root)):
        occ = list(getattr(block, "occurrences", []) or [])
        mod = occ[0].split(":", 1)[0] if occ else "?"
        out.append(Move(
            operator="dedup_total_return",
            target=f"{mod}:total-return-dup-{i}",
            description=(f"lift a {block.lines}-statement always-returning block "
                        f"duplicated in {len(occ)} place(s) into a shared helper"),
            build_plan=lambda b=block: plan_dedup_total_return(project_root, b),
        ))
    return out


register(ObjectiveSpec(name="dedup-total-return", fitness=fitness, moves=moves))
