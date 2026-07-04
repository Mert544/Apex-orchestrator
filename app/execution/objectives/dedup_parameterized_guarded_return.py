"""Self-registering objective: dedup-parameterized-guarded-return.

The near-dup family's THIRD (and final) control-flow rung, completing the
parameterized x {plain, total, guarded} matrix. ``dedup-parameterized`` lifts
a near-duplicate group whose block is a plain run or a clean single tail
return; ``dedup-parameterized-total-return`` lifts the ALWAYS-RETURNING
complement. This objective lifts the REMAINING shape both refuse — a
near-duplicate group whose block has a guard ``return`` on some path AND a
live fall-through (:mod:`app.execution.dedup_guarded_return`'s own
admissible shape, exact-dup sibling, now parameterized). It pairs the SAME
near-duplicate detector (:func:`app.engine.near_dup.near_duplicates`,
memoized) with the reviewed transform (:func:`app.execution
.near_dup_guarded_return.plan_near_dup_guarded_return`), and by construction
acts ONLY on groups both siblings refuse (the three admissible shapes are
disjoint complements — see :func:`app.execution.dedup_extract._block_reason`
and :func:`app.execution.dedup_total_return._always_returns`), so the three
objectives never contend for the same group.

Not expensive: rides the SAME memoized near-duplicate scan the fast
``apex plan`` / ``apex ascend`` board already runs for ``dedup-parameterized``
— no extra flag.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _actionable_groups(project_root: str | Path) -> list:
    """Near-duplicate groups the parameterized guard-return lift can actually
    act on (a guard-return, Constant-only, signature-clean group whose plan
    produces a rewrite)."""
    from app.engine.near_dup import near_duplicates
    from app.execution.near_dup_guarded_return import (
        plan_near_dup_guarded_return,
    )

    return [g for g in near_duplicates(project_root)
            if plan_near_dup_guarded_return(project_root, g).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many guard-return near-duplicate groups can still be
    parameterized away."""
    return float(len(_actionable_groups(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.near_dup_guarded_return import (
        plan_near_dup_guarded_return,
    )

    out = []
    for i, group in enumerate(_actionable_groups(project_root)):
        occ = list(getattr(group, "occurrences", []) or [])
        mod = occ[0].split(":", 1)[0] if occ else "?"
        out.append(Move(
            operator="dedup_parameterized_guarded_return",
            target=f"{mod}:near-dup-guarded-return-{i}",
            description=(f"parameterize a guard-returning {group.lines}-"
                        f"statement near-duplicate across {len(occ)} "
                        "place(s) into one shared sentinel-projecting helper"),
            build_plan=lambda g=group: plan_near_dup_guarded_return(project_root, g),
        ))
    return out


register(ObjectiveSpec(name="dedup-parameterized-guarded-return",
                       fitness=fitness, moves=moves))
