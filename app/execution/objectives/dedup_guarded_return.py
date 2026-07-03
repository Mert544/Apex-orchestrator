"""Self-registering objective: dedup-guarded-return.

The LAST control-flow rung of the dedup gap. The base ``dedup`` objective lifts
a plain / tail-return exact-duplicate block; ``dedup-total-return`` lifts a
block whose EVERY exit path returns; this objective lifts the shape both leave
behind — a block with a guard ``return`` on some path AND a reachable
fall-through (the guard-prelude idiom: ``if bad: return ...`` then keep
computing). That shape was the witnessed human-handoff of Apex's own A+100
debt block; the sentinel-projection transform
(:func:`app.execution.dedup_guarded_return.plan_dedup_guarded_return`) makes it
autonomous: the run lifts verbatim into a helper marking fall-through with a
fresh module-level sentinel, each copy becoming a call + sentinel guard (+ a
live-out rebind when locals project out).

It pairs the same exact-duplicate detector the base objective uses
(:func:`app.engine.dedup.find_duplicates`) with the reviewed transform, and by
construction acts ONLY on blocks the siblings refuse (their admissibility
shapes are disjoint complements), so the three never contend for the same
move. Not expensive: the exact-dup detector is the same one the fast board
already runs for ``dedup``.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _actionable_blocks(project_root: str | Path) -> list:
    """Exact-duplicate blocks the guarded-return extraction can act on — a
    guarded-return block whose plan produces a real rewrite (empty
    ``new_contents`` means a sibling covers it, or it is unsafe; either way
    skip)."""
    from app.engine.dedup import find_duplicates
    from app.execution.dedup_guarded_return import plan_dedup_guarded_return

    return [b for b in find_duplicates(str(project_root))
            if plan_dedup_guarded_return(project_root, b).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many guarded-return duplicate blocks can still be lifted."""
    return float(len(_actionable_blocks(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.dedup_guarded_return import plan_dedup_guarded_return

    out = []
    for i, block in enumerate(_actionable_blocks(project_root)):
        occ = list(getattr(block, "occurrences", []) or [])
        mod = occ[0].split(":", 1)[0] if occ else "?"
        out.append(Move(
            operator="dedup_guarded_return",
            target=f"{mod}:guarded-return-dup-{i}",
            description=(f"lift a {block.lines}-statement guard-returning block "
                         f"duplicated in {len(occ)} place(s) into a shared helper "
                         "(sentinel projection)"),
            build_plan=lambda b=block: plan_dedup_guarded_return(project_root, b),
        ))
    return out


register(ObjectiveSpec(name="dedup-guarded-return", fitness=fitness, moves=moves))
