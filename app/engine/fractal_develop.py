"""Fractal develop — a goal decomposes, self-similarly, into verified campaigns.

`apex develop --objective X` composes verified moves toward ONE metric. This
goes a level up, fractally: a high-level GOAL ("reduce the structural debt")
decomposes into sub-goals ("tidy the surface", "simplify the structure"), each
of which decomposes into leaf OBJECTIVES (modernize, dedup, shrink…), each of
which composes moves. Every node is the same shape — "pursue this, verified" —
whether it fans out into sub-goals or bottoms out in an objective's greedy,
suite-gated loop. That self-similarity is the fractal: the Objective-Compiler is
the leaf, this is the recursive tree above it.

The decomposition is a fixed, deterministic tree (no LLM). Running a goal flattens
it to its leaf objectives in order, runs each as its own campaign, and proves the
whole goal's effect with a single before→after health grade.

Deterministic, stdlib-only; reuses the Objective-Compiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.objective_compiler import (
    CompileResult,
    available_objectives,
    compile_objective,
    render_compile_markdown,
)

__all__ = [
    "GOAL_TREE", "GoalResult", "resolve_goal", "available_goals",
    "compile_goal", "render_goal_markdown",
]

# The fractal goal tree: a goal maps to sub-goals or leaf objectives. A name not
# here but in `available_objectives()` is itself a leaf (so any objective is a
# valid one-node goal). The order encodes the engineering sequence.
GOAL_TREE: dict[str, list[str]] = {
    "reduce-debt": ["tidy", "simplify-structure"],
    "tidy": ["modernize", "simplify-bool-return", "remove-dead-code", "dead-params"],
    "simplify-structure": ["dedup", "shrink-functions", "inline-helpers"],
}


@dataclass
class GoalResult:
    goal: str
    objectives: list[str]                       # the leaf objectives, in order
    results: list[CompileResult] = field(default_factory=list)
    grade_before: int = -1
    grade_after: int = -1
    applied: bool = False

    @property
    def total_moves(self) -> int:
        return sum(len(r.steps) for r in self.results)

    @property
    def grade_delta(self) -> int:
        if self.grade_before < 0 or self.grade_after < 0:
            return 0
        return self.grade_after - self.grade_before

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "objectives": self.objectives,
            "results": [r.to_dict() for r in self.results],
            "grade_before": self.grade_before, "grade_after": self.grade_after,
            "grade_delta": self.grade_delta, "total_moves": self.total_moves,
            "applied": self.applied,
        }


def available_goals() -> list[str]:
    """Every name that names a goal — the composite goals plus every objective
    (each objective is a valid single-node goal)."""
    return sorted(set(GOAL_TREE) | set(available_objectives()))


def resolve_goal(goal: str, _seen: frozenset[str] = frozenset()) -> list[str]:
    """Flatten a goal to its leaf objectives, in order, de-duplicated.

    A goal in the tree expands into its children (recursively); a name that is
    an available objective is a leaf. Cycles/unknown names resolve to nothing."""
    if goal in _seen:
        return []  # guard the (shouldn't-happen) cycle
    if goal in GOAL_TREE:
        out: list[str] = []
        for child in GOAL_TREE[goal]:
            for obj in resolve_goal(child, _seen | {goal}):
                if obj not in out:
                    out.append(obj)
        return out
    return [goal] if goal in available_objectives() else []


def _grade(project_root: str | Path) -> int:
    try:
        from app.engine.health_score import grade
        return grade(str(project_root)).score
    except Exception:
        return -1


def compile_goal(project_root: str | Path, goal: str, max_steps: int = 25,
                 verify: bool = True, apply: bool = True) -> GoalResult:
    """Pursue ``goal`` by running each leaf objective it decomposes into — each
    its own suite-gated campaign — and prove the whole goal's effect with a
    before→after health grade."""
    objectives = resolve_goal(goal)
    before = _grade(project_root) if apply else -1
    result = GoalResult(goal=goal, objectives=objectives, applied=apply,
                        grade_before=before)
    for obj in objectives:
        campaign = compile_objective(project_root, objective=obj, max_steps=max_steps,
                                     verify=verify, apply=apply)
        if campaign.steps or campaign.fitness_start > 0:
            result.results.append(campaign)
    result.grade_after = _grade(project_root) if (apply and before >= 0) else before
    return result


def render_goal_markdown(result: GoalResult) -> str:
    """Render the fractal goal campaign as a tree-shaped report."""
    if not result.objectives:
        known = ", ".join(available_goals())
        return (f"# Develop goal — `{result.goal}`\n\n_Unknown goal. Known goals: "
                f"{known}._\n")
    verb = "Applied" if result.applied else "Would apply"
    lines = [f"# Develop goal — `{result.goal}`", "",
             f"_Decomposes into: {' → '.join(result.objectives)}_", "",
             f"{verb} **{result.total_moves} verified move(s)** across "
             f"{len(result.results)} sub-campaign(s)."]
    if result.applied and result.grade_before >= 0 and result.grade_after >= 0:
        d = result.grade_delta
        arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
        lines.append(f"\n**Health grade: {result.grade_before} → {result.grade_after} "
                     f"({'+' if d > 0 else ''}{d} {arrow})** — the goal's measured effect.")
    lines.append("")
    for r in result.results:
        lines.append(render_compile_markdown(r))
    return "\n".join(lines)
