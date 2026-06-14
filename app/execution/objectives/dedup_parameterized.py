"""Self-registering objective: dedup-parameterized.

Lift a NEAR-duplicate group — blocks structurally identical but differing at a
few CONSTANT or free-NAME leaves — into one parameterized helper, the part of
dedup's detect>>act gap exact-match extraction can't reach. It pairs the detector
(:func:`app.engine.near_dup.near_duplicates`, memoized) with the reviewed
transform (:func:`app.execution.near_dup_extract.plan_near_dup_extract`).

Once flagged ``expensive`` because the detector templated every window (~100s on
a large repo); after the O(1) segment-slicing rewrite the whole scan is ~1.8s
(memoized to ~1.3s for the fitness), so it now rides the fast ``apex plan`` /
``apex ascend`` board like any other objective — no flag.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _actionable_groups(project_root: str | Path) -> list:
    """Near-duplicate groups the parameterized extraction can actually act on
    (a constant-only, signature-clean group whose plan produces a rewrite)."""
    from app.engine.near_dup import near_duplicates
    from app.execution.near_dup_extract import plan_near_dup_extract

    return [g for g in near_duplicates(project_root)
            if plan_near_dup_extract(project_root, g).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many near-duplicate groups can still be parameterized away."""
    return float(len(_actionable_groups(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.near_dup_extract import plan_near_dup_extract

    out = []
    for i, group in enumerate(_actionable_groups(project_root)):
        loc = group.occurrences[0] if group.occurrences else f"group-{i}"
        out.append(Move(
            operator="dedup_parameterized",
            target=f"{loc}:near-dup-{i}",
            description=(f"parameterize a {group.lines}-statement near-duplicate "
                        f"across {len(group.occurrences)} place(s)"),
            build_plan=lambda g=group: plan_near_dup_extract(project_root, g),
        ))
    return out


register(ObjectiveSpec(name="dedup-parameterized", fitness=fitness, moves=moves))
