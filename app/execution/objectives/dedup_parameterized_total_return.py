"""Self-registering objective: dedup-parameterized-total-return.

The near-dup family's SECOND control-flow rung. ``dedup-parameterized`` lifts
a near-duplicate group whose block is a plain run or a clean single tail
return; this objective lifts the complement — a near-duplicate group whose
block is TOTAL-RETURN (every exit path returns/raises: a guard ``return`` on
some path plus a final ``return``, or an ``if``/``elif``/``else`` ladder
where every branch returns) — the shape ``dedup-parameterized`` refuses. It
pairs the SAME near-duplicate detector (:func:`app.engine.near_dup
.near_duplicates`, memoized) with the reviewed transform
(:func:`app.execution.near_dup_total_return.plan_near_dup_total_return`), and
by construction acts ONLY on groups the sibling refuses (their admissibility
shapes are disjoint complements — see
:func:`app.execution.dedup_extract._block_reason`), so the two objectives
never contend for the same group.

Not expensive: rides the SAME memoized near-duplicate scan the fast
``apex plan`` / ``apex ascend`` board already runs for ``dedup-parameterized``
— no extra flag.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _actionable_groups(project_root: str | Path) -> list:
    """Near-duplicate groups the parameterized total-return lift can actually
    act on (an always-returning, Constant-only, signature-clean group whose
    plan produces a rewrite)."""
    from app.engine.near_dup import near_duplicates
    from app.execution.near_dup_total_return import plan_near_dup_total_return

    return [g for g in near_duplicates(project_root)
            if plan_near_dup_total_return(project_root, g).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many always-returning near-duplicate groups can still be
    parameterized away."""
    return float(len(_actionable_groups(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.near_dup_total_return import plan_near_dup_total_return

    out = []
    for i, group in enumerate(_actionable_groups(project_root)):
        occ = list(getattr(group, "occurrences", []) or [])
        mod = occ[0].split(":", 1)[0] if occ else "?"
        out.append(Move(
            operator="dedup_parameterized_total_return",
            target=f"{mod}:near-dup-total-return-{i}",
            description=(f"parameterize an always-returning {group.lines}-"
                        f"statement near-duplicate across {len(occ)} "
                        "place(s) into one shared returning helper"),
            build_plan=lambda g=group: plan_near_dup_total_return(project_root, g),
        ))
    return out


register(ObjectiveSpec(name="dedup-parameterized-total-return",
                       fitness=fitness, moves=moves))
