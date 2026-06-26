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
from app.engine.objective_value import objective_value_weight

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
    payoff: float = 0.0     # learned health-gain per move from past campaigns
    reliability: float = 1.0  # the organism's DREAMED land-rate for this objective
    expensive: bool = False  # a heavy fitness scan (only on the --concrete board)
    value_weight: float = 1.0  # buyer-value lead on the --concrete board; neutral 1.0 keeps the default fast board byte-identical
    # A PURELY DISPLAY-ONLY buyer-value lens for the read-only preview path
    # (``value_weight_preview``). It is NEVER read by ``priority`` — the
    # apply-driving order stays byte-identical whether or not the preview lens is
    # on (the round-21 safety: only the read-only PREVIEW may change, never the
    # applied set). Default 0.0 ⇒ ``to_dict`` omits it (additive, like
    # ``CompileStep.value``), so ``apex plan --json`` is byte-identical when off.
    preview_value: float = 0.0

    @property
    def priority(self) -> float:
        """The score the climb ranks by: pending work AMPLIFIED by learned
        payoff, DAMPED by the objective's proven land-rate, and LED by its buyer
        value on the --concrete board.

        ``reliability`` is what the organism learned in its own runs (the same
        signal its nightly dream reads): an objective that reliably LANDS keeps
        its priority, while one that mostly blocks/rolls back is pushed down — so
        the climb stops wasting rounds on a proven blocker. ``value_weight`` is
        the buyer-value lens (``objective_value_weight``) populated ONLY on the
        --concrete board, so Tier-1 concrete leads there; it is a neutral 1.0 on
        the default fast board AND as the field default. With no track record all
        three factors are neutral (payoff 0, reliability 1, value_weight 1), so a
        fresh project's default board ranks purely on pending work, exactly as
        before."""
        return (self.pending * (1.0 + max(0.0, self.payoff))
                * self.reliability * self.value_weight)

    def to_dict(self) -> dict[str, Any]:
        d = {"objective": self.objective, "pending": self.pending,
             "goal": self.goal, "payoff": round(self.payoff, 3),
             "reliability": round(self.reliability, 3),
             "value_weight": round(self.value_weight, 3),
             "priority": round(self.priority, 3)}
        # ``preview_value`` is a PURELY ADDITIVE display disclosure: it appears
        # ONLY when the read-only preview lens populated it (default 0.0 ⇒ key
        # omitted ⇒ ``apex plan --json`` is byte-identical to before), exactly
        # mirroring ``CompileStep.to_dict``'s additive ``value`` omission.
        if self.preview_value:
            d["preview_value"] = round(self.preview_value, 3)
        return d


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


def payoff_weights(project_root: str | Path) -> dict[str, float]:
    """What the organism has LEARNED: health-gain per move for each objective,
    from its own recorded campaigns (``.apex/dev-history.json``).

    For each objective the weight is total grade-delta divided by total moves
    across every past campaign that pursued it (the ``ascend:`` prefix is
    stripped, so a climb's own rounds feed back in). Negative or absent history
    yields no weight, so learning can only ever PROMOTE a proven-profitable
    objective — never bury one that simply hasn't run yet."""
    from app.engine.dev_history import DevHistory

    gain: dict[str, float] = {}
    moves: dict[str, float] = {}
    for run in DevHistory.load(project_root).entries():
        name = run.objective.split("ascend:", 1)[-1]
        gain[name] = gain.get(name, 0.0) + run.delta
        moves[name] = moves.get(name, 0.0) + run.moves
    weights: dict[str, float] = {}
    for name, total_moves in moves.items():
        if total_moves > 0 and gain.get(name, 0.0) > 0:
            weights[name] = gain[name] / total_moves
    return weights


_RELIABILITY_FLOOR = 0.15  # a proven blocker is heavily damped, never fully erased.


def land_factors(project_root: str | Path) -> dict[str, float]:
    """What the organism DREAMED about each objective: its EVIDENCE-DAMPED proven
    land-rate, from the idea memory (the SAME store the nightly dream reads when
    it says "`sort_imports` fixes land 100%" or "`harden` lands only 0%"). An
    objective whose operator landed reliably keeps a factor near 1.0; one that
    mostly blocked/rolled back is damped toward a floor, so the climb stops
    spending rounds on a proven blocker. Too-few-samples / untracked → a neutral
    1.0.

    The reliability term is the Wilson score lower bound (``stat.confidence``),
    not the raw success rate — so among TRACKED operators a thin-but-perfect 2-of-2
    (rate 1.000, lb≈0.34) cannot outrank a well-attested 9-of-10 (rate 0.900,
    lb≈0.60): proven beats lucky. More samples at the same rate strictly raise the
    bound, so accumulated evidence is never penalised. Reads are gated by
    ``_MIN_SAMPLES`` (=2): an operator with fewer samples — including a single
    1-of-1 — is absent here and ranks at the neutral 1.0 (the damping applies only
    once there is enough evidence to trust), so the zero-sample bound (0.0) never
    enters. A proven blocker's low bound is held at ``_RELIABILITY_FLOOR`` so it is
    damped, never fully erased.

    An objective's operator is its name with hyphens as underscores — the
    convention every self-registering objective follows — which is exactly how the
    memory keys its ``by_operator`` stats."""
    from app.engine.idea_memory import _MIN_SAMPLES, IdeaMemory

    mem = IdeaMemory.load(project_root)
    out: dict[str, float] = {}
    for name in available_objectives():
        stat = mem.by_operator.get(name.replace("-", "_"))
        if stat is not None and stat.total >= _MIN_SAMPLES:
            out[name] = max(_RELIABILITY_FLOOR, stat.confidence)
    return out


def rank_objectives(project_root: str | Path,
                    objectives: list[str] | None = None,
                    *, include_expensive: bool = False,
                    exclude: set[str] | None = None,
                    value_weight_preview: bool = False) -> list[GoalRanking]:
    """Every objective ranked by pending fixable debt AMPLIFIED by learned
    payoff, worst-and-most-profitable first.

    Pending is the objective's own fitness (the count of items it could still
    fix). Each objective's ``payoff`` (learned health-gain per move, from
    ``payoff_weights``) boosts its priority, so the organism climbs toward the
    debt that has paid off best before. Ties break by registration order, so the
    ranking is fully deterministic; with no history every payoff is 0 and the
    order is exactly pending-descending (a fresh project is unchanged).

    ``exclude`` is the climb's within-run blocked set: objectives a prior round
    proved cannot move (every candidate blocked) so the board stops re-ranking
    them to the top each round. It only drops names — it never reorders the
    survivors — and an empty/None set leaves the board byte-identical to before.

    ``value_weight_preview`` is a READ-ONLY display lens: when on it stamps each
    ranking's NEW ``preview_value`` field with ``objective_value_weight(name)``
    (a buyer-value annotation the preview can surface). It NEVER feeds
    ``priority`` and NEVER touches the sort key, so the apply-driving order is
    byte-identical whether it is on or off (the round-21 safety — only the
    read-only preview may change). Off (default) ⇒ ``preview_value`` stays 0.0
    ⇒ ``to_dict`` omits it ⇒ ``apex plan --json`` is byte-identical."""
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import _objectives_map

    table = _objectives_map()
    weights = payoff_weights(project_root)
    reliab = land_factors(project_root)
    exp = expensive_names()  # computed once: the skip gate AND the cost-tiebreak stamp
    if objectives is not None:
        names = objectives
    else:
        # The default board skips EXPENSIVE objectives (e.g. the whole-project
        # near-dup scan, and the high-value concrete moves implement-stub /
        # wire-exports / strengthen-tests) so plan/ascend stay fast; they're run
        # explicitly or opted into via include_expensive (the --concrete flag).
        skip = set() if include_expensive else exp
        names = [n for n in available_objectives() if n not in skip]
    if exclude:
        names = [n for n in names if n not in exclude]
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
        # The buyer-value weight ENTERS priority ONLY on the include_expensive
        # (--concrete) board, where expensive concrete is already surfaced; on the
        # default fast board it is held NEUTRAL at 1.0 so priority and ordering are
        # byte-identical to today (the trust property is STRUCTURAL, not a comment).
        rankings.append(GoalRanking(objective=name, pending=pending,
                                    goal=objective_parent(name),
                                    payoff=weights.get(name, 0.0),
                                    reliability=reliab.get(name, 1.0),
                                    expensive=name in exp,
                                    value_weight=(objective_value_weight(name)
                                                  if include_expensive else 1.0),
                                    # Display-only buyer-value annotation for the
                                    # read-only preview; NEVER read by priority or
                                    # the sort key (apply order stays identical).
                                    preview_value=(objective_value_weight(name)
                                                   if value_weight_preview else 0.0)))
    # Highest priority first; among priority ties the higher buyer-value objective
    # leads (so on the --concrete board an equal-priority concrete banks before a
    # cheaper tidy), then the cheaper objective (expensive=False) banks before an
    # expensive rollback-prone scan, then registration index. On the default board
    # value_weight is a constant 1.0 for every survivor, so -r.value_weight is a
    # constant key and the order collapses to exactly the old
    # (-priority, expensive, order) — byte-identical to before.
    rankings.sort(key=lambda r: (-r.priority, -r.value_weight, r.expensive,
                                 order.get(r.objective, 0)))
    return rankings


def _goal_objectives(goal: str) -> list[str] | None:
    """The leaf objectives a ``--goal`` restricts the climb to, or None for the
    whole board. An unknown goal yields an empty restriction (nothing to do)."""
    if not goal:
        return None
    from app.engine.fractal_develop import resolve_goal
    return resolve_goal(goal)


def _take_first_landing_move(project_root: str | Path, ranked: list[GoalRanking],
                             round_no: int, before: int, *, max_steps: int,
                             verify: bool, scope_verify: bool,
                             blocked_run: set[str]) -> AscendRound | None:
    """Develop the worst fixable debt that can actually MOVE this round, and
    report it as a round. An objective may carry pending debt the compiler can't
    safely act on (every candidate blocked); rather than spin on it, fall through
    to the next-worst until one lands a verified move.

    Each objective that lands NOTHING this round (``moves == 0``) is added to
    ``blocked_run`` — the climb's within-run blocked set — so later rounds stop
    re-ranking a proven-immovable objective to the top and re-paying its
    expensive compile scan. Returns the landed round, or None when nothing in
    ``ranked`` could move (a develop fixpoint for the current tools)."""
    from app.engine.dev_history import record_run

    for choice in ranked:
        campaign = compile_objective(project_root, objective=choice.objective,
                                     max_steps=max_steps, verify=verify, apply=True,
                                     scope_verify=scope_verify)
        moves = len(campaign.steps)
        if moves == 0:
            blocked_run.add(choice.objective)
            continue
        after = _grade(project_root)
        record_run(project_root, f"ascend:{choice.objective}", moves, before, after)
        return AscendRound(
            round_no=round_no, objective=choice.objective, goal=choice.goal,
            moves=moves, grade_before=before, grade_after=after,
            pending_before=choice.pending)
    return None


def ascend(project_root: str | Path, max_rounds: int = 4,
           target_score: int | None = None, apply: bool = True,
           verify: bool = True, goal: str = "", max_steps: int = 25,
           scope_verify: bool = False, include_expensive: bool = False) -> AscendReport:
    """Climb the project's health by repeatedly developing its worst fixable
    debt, each round suite-gated and grade-proven, to a fixpoint.

    ``goal`` restricts the climb to one fractal goal's objectives. ``apply=False``
    is a preview: it ranks the board and reports the move it WOULD make next,
    changing nothing. ``scope_verify`` gates each move against only the impacted
    tests (fast enough to climb a large project's OWN body); run the full suite
    afterwards as the backstop."""
    restrict = _goal_objectives(goal)
    report = AscendReport(applied=apply, target_score=target_score)

    if not apply:
        report.preview = [r for r in rank_objectives(project_root, restrict,
                                                      include_expensive=include_expensive)
                          if r.pending > 0]
        return report

    report.grade_start = _grade(project_root)
    # The climb's within-run blocked set: objectives a round proves cannot move
    # (every candidate blocked) are remembered here and excluded from later
    # rounds' ranking, so the climb never re-pays an expensive compile scan it
    # already proved can't progress. In-memory and per-run — fresh each call.
    blocked_run: set[str] = set()
    for n in range(1, max_rounds + 1):
        ranked = [r for r in rank_objectives(project_root, restrict,
                                              include_expensive=include_expensive,
                                              exclude=blocked_run)
                  if r.pending > 0]
        if not ranked:
            report.fixpoint = True
            break
        before = _grade(project_root)
        landed = _take_first_landing_move(
            project_root, ranked, n, before, max_steps=max_steps, verify=verify,
            scope_verify=scope_verify, blocked_run=blocked_run)
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
    learned = any(r.payoff > 0 for r in actionable)
    note = (" — ordered by pending debt **amplified by learned payoff** "
            "(health gained per move in past runs)") if learned else ""
    lines.append(f"**{len(actionable)} objective(s) carry fixable debt.** "
                 f"The climb takes the worst first{note}:")
    lines.append("")
    if learned:
        lines.append("| # | Objective | Goal | Pending | Learned ↑/move |")
        lines.append("|---:|---|---|---:|---:|")
        for i, r in enumerate(actionable, 1):
            mark = f"+{r.payoff:.2f}" if r.payoff > 0 else "—"
            lines.append(f"| {i} | `{r.objective}` | {r.goal} | {int(r.pending)} | {mark} |")
    else:
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
