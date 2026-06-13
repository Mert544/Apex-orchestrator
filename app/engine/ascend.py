"""Ascend — autonomous, goal-directed self-improvement to a fixpoint.

`apex develop --objective X` runs one campaign; `apex develop --goal G` runs one
goal's fractal decomposition. Ascend is the level above both: it lets the
organism improve ITSELF (or any project) without being told what to do next.

Each round it asks the deterministic question *"which fixable debt is worst
right now?"* — ranking every develop objective by its measured fitness (the
count of pending, fixable items) — then develops the worst one under the full
suite gate, records the climb to the development trajectory, re-grades the
project to PROVE the gain, and repeats. It stops when no objective has fixable
work left (a fixpoint), a target grade is reached, or a round budget is spent.

The organism picks its own next move, does it verified, and shows its work. The
ranking is a fixed function of measured fitness — never an LLM — so the same
project always yields the same climb.

Deterministic, stdlib-only; reuses the Objective-Compiler and the fractal tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.fractal_develop import GOAL_TREE
from app.engine.objective_compiler import (
    available_objectives,
    compile_objective,
)

__all__ = [
    "GoalRanking", "AscendRound", "AscendReport",
    "objective_parent", "rank_objectives", "ascend",
    "render_plan_markdown", "render_ascend_markdown",
]


@dataclass
class GoalRanking:
    """One objective's standing in the priority order for the next move."""
    objective: str
    pending: float          # measured fitness: how many fixable items remain
    goal: str               # the nearest goal in the fractal tree it rolls up to

    def to_dict(self) -> dict[str, Any]:
        return {"objective": self.objective, "pending": self.pending, "goal": self.goal}


@dataclass
class AscendRound:
    """One round of the climb: the chosen objective and the grade it moved."""
    round_no: int
    objective: str
    goal: str
    moves: int
    grade_before: int
    grade_after: int
    pending_before: float

    @property
    def delta(self) -> int:
        return self.grade_after - self.grade_before

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round_no, "objective": self.objective, "goal": self.goal,
                "moves": self.moves, "grade_before": self.grade_before,
                "grade_after": self.grade_after, "delta": self.delta,
                "pending_before": self.pending_before}


@dataclass
class AscendReport:
    rounds: list[AscendRound] = field(default_factory=list)
    grade_start: int = -1
    grade_end: int = -1
    fixpoint: bool = False
    target_score: int | None = None
    applied: bool = True
    # Dry-run preview: the ranking the first round WOULD act on (no work done).
    preview: list[GoalRanking] = field(default_factory=list)

    @property
    def total_moves(self) -> int:
        return sum(r.moves for r in self.rounds)

    @property
    def grade_delta(self) -> int:
        if self.grade_start < 0 or self.grade_end < 0:
            return 0
        return self.grade_end - self.grade_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "rounds": [r.to_dict() for r in self.rounds],
            "grade_start": self.grade_start, "grade_end": self.grade_end,
            "grade_delta": self.grade_delta, "total_moves": self.total_moves,
            "fixpoint": self.fixpoint, "target_score": self.target_score,
            "applied": self.applied,
            "preview": [g.to_dict() for g in self.preview],
        }


def _grade(project_root: str | Path) -> int:
    try:
        from app.engine.health_score import grade
        return grade(str(project_root)).score
    except Exception:
        return -1


def objective_parent(objective: str) -> str:
    """The nearest goal in the fractal tree whose direct children include
    ``objective`` (so the climb can name where each move lives). Falls back to
    the objective's own name when it is not nested under any goal."""
    for goal, children in GOAL_TREE.items():
        if objective in children:
            return goal
    return objective


def rank_objectives(project_root: str | Path,
                    objectives: list[str] | None = None) -> list[GoalRanking]:
    """Every objective ranked by pending fixable debt, worst first.

    Pending is the objective's own fitness (the count of items it could still
    fix). Ties break by the objective's registration order, so the ranking is
    fully deterministic. Objectives with zero pending are included (pending 0)
    so callers can show the whole board; ``ascend`` skips them when choosing."""
    from app.engine.objective_compiler import _objectives_map

    table = _objectives_map()
    names = objectives if objectives is not None else available_objectives()
    order = {name: i for i, name in enumerate(available_objectives())}
    rankings: list[GoalRanking] = []
    for name in names:
        if name not in table:
            continue
        fitness_fn = table[name][0]
        try:
            pending = float(fitness_fn(project_root))
        except Exception:
            pending = 0.0
        rankings.append(GoalRanking(objective=name, pending=pending,
                                    goal=objective_parent(name)))
    rankings.sort(key=lambda r: (-r.pending, order.get(r.objective, 0)))
    return rankings


def _goal_objectives(goal: str) -> list[str] | None:
    """The leaf objectives a ``--goal`` restricts the climb to, or None for the
    whole board. An unknown goal yields an empty restriction (nothing to do)."""
    if not goal:
        return None
    from app.engine.fractal_develop import resolve_goal
    return resolve_goal(goal)


def ascend(project_root: str | Path, max_rounds: int = 4,
           target_score: int | None = None, apply: bool = True,
           verify: bool = True, goal: str = "", max_steps: int = 25) -> AscendReport:
    """Climb the project's health by repeatedly developing its worst fixable
    debt, each round suite-gated and grade-proven, to a fixpoint.

    ``goal`` restricts the climb to one fractal goal's objectives. ``apply=False``
    is a preview: it ranks the board and reports the move it WOULD make next,
    changing nothing."""
    from app.engine.dev_history import record_run

    restrict = _goal_objectives(goal)
    report = AscendReport(applied=apply, target_score=target_score)

    if not apply:
        report.preview = [r for r in rank_objectives(project_root, restrict) if r.pending > 0]
        return report

    report.grade_start = _grade(project_root)
    for n in range(1, max_rounds + 1):
        ranked = [r for r in rank_objectives(project_root, restrict) if r.pending > 0]
        if not ranked:
            report.fixpoint = True
            break
        before = _grade(project_root)
        landed: AscendRound | None = None
        # Take the worst fixable debt that can actually MOVE this round. An
        # objective may carry pending debt the compiler can't safely act on
        # (every candidate blocked); rather than spin on it, fall through to the
        # next-worst until one lands a verified move.
        for choice in ranked:
            campaign = compile_objective(project_root, objective=choice.objective,
                                         max_steps=max_steps, verify=verify, apply=True)
            moves = len(campaign.steps)
            if moves == 0:
                continue
            after = _grade(project_root)
            landed = AscendRound(
                round_no=n, objective=choice.objective, goal=choice.goal, moves=moves,
                grade_before=before, grade_after=after, pending_before=choice.pending)
            record_run(project_root, f"ascend:{choice.objective}", moves, before, after)
            break
        if landed is None:
            # Pending debt remains, but nothing the compiler can safely move — a
            # develop fixpoint for this organism's current tools.
            report.fixpoint = True
            break
        report.rounds.append(landed)
        if target_score is not None and landed.grade_after >= target_score:
            break
    report.grade_end = _grade(project_root)
    if not report.rounds and not report.fixpoint:
        report.fixpoint = True
    return report


def _letter(score: int) -> str:
    try:
        from app.engine.health_score import _letter as letter
        return letter(score)
    except Exception:
        return "?"


def render_plan_markdown(rankings: list[GoalRanking]) -> str:
    """Render the priority board — what the organism would work on, worst first."""
    actionable = [r for r in rankings if r.pending > 0]
    lines = ["# Develop plan — what to improve next", ""]
    if not actionable:
        lines += ["_Nothing to do: every objective is already at zero. The project",
                  "is at a develop fixpoint._", ""]
        return "\n".join(lines)
    lines.append(f"**{len(actionable)} objective(s) carry fixable debt.** "
                 "The climb takes the worst first:")
    lines.append("")
    lines.append("| # | Objective | Goal | Pending |")
    lines.append("|---:|---|---|---:|")
    for i, r in enumerate(actionable, 1):
        lines.append(f"| {i} | `{r.objective}` | {r.goal} | {int(r.pending)} |")
    lines.append("")
    lines.append(f"Next move: develop **`{actionable[0].objective}`** "
                 f"(goal _{actionable[0].goal}_).")
    lines.append("")
    return "\n".join(lines)


def render_ascend_markdown(report: AscendReport) -> str:
    """Render the autonomous climb: round-by-round, with the proven grade gain."""
    if not report.applied:
        if not report.preview:
            return ("# Ascend (preview)\n\n_Nothing to do: every objective is at zero "
                    "— the project is at a develop fixpoint._\n")
        nxt = report.preview[0]
        lines = ["# Ascend (preview)", "",
                 f"Would climb **{len(report.preview)} objective(s)** of fixable debt, "
                 f"worst first. Next move: develop `{nxt.objective}` (goal _{nxt.goal}_).",
                 "", "_Dry run — re-run with `--apply` to climb._", ""]
        return "\n".join(lines)

    lines = ["# Ascend — autonomous self-improvement", ""]
    if not report.rounds:
        lines += ["_No fixable debt to develop — the project is already at a develop",
                  "fixpoint. Nothing was changed._", ""]
        return "\n".join(lines)

    verb = "reached a fixpoint" if report.fixpoint else "spent its round budget"
    d = report.grade_delta
    arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
    lines.append(f"Climbed **{len(report.rounds)} round(s)**, "
                 f"**{report.total_moves} verified move(s)**, then {verb}.")
    if report.grade_start >= 0 and report.grade_end >= 0:
        lines.append(f"\n**Health: {report.grade_start} ({_letter(report.grade_start)}) "
                     f"→ {report.grade_end} ({_letter(report.grade_end)}) "
                     f"({'+' if d > 0 else ''}{d} {arrow})** — the proven climb.")
    lines.append("")
    lines.append("| Round | Objective | Goal | Moves | Grade |")
    lines.append("|---:|---|---|---:|---:|")
    for r in report.rounds:
        lines.append(f"| {r.round_no} | `{r.objective}` | {r.goal} | {r.moves} | "
                     f"{r.grade_before}→{r.grade_after} |")
    lines.append("")
    return "\n".join(lines)
