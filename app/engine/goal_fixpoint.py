"""`goal_fixpoint` — a round-based convergence loop over a whole GOAL SET.

Where ``chain_compiler.run_chain`` runs an EXPLICIT, ordered SEQUENCE of
objectives, and ``project_goal_orchestrator.orchestrate_goal`` lands ONE goal's
leaves atomically, this composes both one level up: given an ARBITRARY caller
-supplied SET of goals — ``apex develop --goals A,B,C --fixpoint`` — it lands
them ROUND after round, in a PROVEN dependency order
(:func:`app.engine.objective_dependencies.topological_sort`), until the set
reaches a FIXPOINT (a round that lands nothing) or the round cap is hit.

This is the FIRST real consumer of ``objective_dependencies`` — until now that
module's proven graph was inert (built, tested, never wired to a caller). Each
round asks the SAME topological order (pure, deterministic) to sequence the
LIVE (not-yet-retired) goals, then lands each goal through the EXISTING engine:

  * a goal that decomposes to TWO OR MORE leaves is landed ATOMICALLY via
    :func:`app.engine.project_goal_orchestrator.orchestrate_goal` (the whole
    goal lands together or NEITHER leaf does);
  * a goal that decomposes to exactly ONE leaf (or names an objective directly)
    has nothing to COMPOSE, so it falls back to
    :func:`app.engine.objective_compiler.compile_objective` — the SAME
    single-objective fallback ``orchestrate_goal`` itself declines to run
    (fewer than two landable leaves); the compile path is classified red/landed
    with the SAME :func:`app.engine.chain_compiler._step_is_red` the chain
    compiler uses (imported, not reimplemented).

A goal whose landing ROLLS BACK (a genuine regression, not an honest no-op) is
PERMANENTLY RETIRED — it never runs again in a later round of this fixpoint,
so a goal that cannot land cleanly doesn't churn the tree round after round. A
round that trips too many rollbacks (``max_rollbacks_per_round``) is a
CIRCUIT BREAKER: the round (and the whole loop) stops mid-round, honestly.

This mirrors ``evolution.EvolutionLoop.run`` ONE level up: where evolution's
cycles apply whatever the roadmap ranks highest, a fixpoint round lands a
NAMED, topologically-sequenced goal SET — the SAME round-loop / fixpoint /
circuit-breaker shape (see ``evolution.py:121-194``), generalized from "cycle
over ranked ideas" to "round over an explicit goal set". It is ALSO the SAME
UNATTENDED-forces-``covered_only`` discipline ``cmd_evolve`` applies at the CLI
layer (:func:`app.policies.autonomy_policy.resolve_covered_only`,
``unattended=True``) — a headless multi-round loop is exactly where an
uncovered, weak-verified move is the highest-risk silent regression.

Every byte this module writes goes through the EXISTING gated writers
(``apply_rename`` under ``orchestrate_goal``, and ``compile_objective``'s own
suite-gated apply loop): zero new verification logic, the never-fake-green moat
is inherited per goal. Deterministic: the round order is a pure topological
sort of the caller's goal set, the retirement/circuit-breaker bookkeeping is a
plain fold, and the report body carries no clock/randomness. Stdlib-only;
offline by default."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.chain_compiler import _step_is_red
from app.engine.objective_dependencies import topological_sort

__all__ = [
    "RoundResult", "FixpointRound", "FixpointReport",
    "run_goal_fixpoint", "render_fixpoint_markdown",
]


@dataclass
class RoundResult:
    """One goal's outcome within one round — a normalized projection over
    whichever engine actually landed it (``orchestrate_goal`` for a ≥2-leaf goal,
    ``compile_objective`` for the 1-leaf fallback), so a caller reads ONE shape
    regardless of which path ran.

    ``status`` is the honest per-goal verdict for this round: ``landed`` (at
    least one verified change composed), ``empty`` (attempted, nothing to do),
    ``rolled_back`` (a genuine regression — the goal is now PERMANENTLY
    retired), ``refused`` (the composing engine declined — e.g. an unknown goal,
    or ``compose_plans`` refused an overlap), or ``unknown`` (the goal name
    resolves to no leaves at all — retired immediately, never attempted again).
    ``via`` names which engine landed it (``"orchestrate"`` or ``"compile"``),
    so a report can disclose the dispatch honestly."""
    goal: str
    status: str
    via: str = ""
    reason: str = ""
    files_changed: list[str] = field(default_factory=list)

    @property
    def landed(self) -> bool:
        return self.status == "landed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "status": self.status, "via": self.via,
            "reason": self.reason, "files_changed": self.files_changed,
        }


@dataclass
class FixpointRound:
    """One round's outcome: the topologically-ordered goals it attempted, in the
    order it attempted them, plus whether the round's circuit breaker tripped."""
    order: list[str] = field(default_factory=list)
    results: list[RoundResult] = field(default_factory=list)
    circuit_broken: bool = False

    @property
    def landed_goals(self) -> list[str]:
        return [r.goal for r in self.results if r.landed]

    @property
    def rolled_back_goals(self) -> list[str]:
        return [r.goal for r in self.results if r.status == "rolled_back"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "results": [r.to_dict() for r in self.results],
            "landed_goals": self.landed_goals,
            "rolled_back_goals": self.rolled_back_goals,
            "circuit_broken": self.circuit_broken,
        }


@dataclass
class FixpointReport:
    """The whole convergence loop's deterministic result.

    ``goals`` is the caller's SET verbatim (order as supplied); ``rounds`` is
    each round's outcome in order; ``retired`` is the FINAL retired set (a goal
    that rolled back, or resolved to no leaves) — never attempted again once
    retired; ``reached_fixpoint`` is True iff the loop stopped because a round
    landed nothing (not the round cap, not the circuit breaker)."""
    goals: list[str]
    rounds: list[FixpointRound] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    reached_fixpoint: bool = False
    circuit_broken: bool = False
    max_rounds_hit: bool = False
    grade_before: int = -1
    grade_after: int = -1
    applied: bool = False

    @property
    def rounds_run(self) -> int:
        return len(self.rounds)

    @property
    def total_landed(self) -> int:
        return sum(len(r.landed_goals) for r in self.rounds)

    @property
    def grade_delta(self) -> int:
        if self.grade_before < 0 or self.grade_after < 0:
            return 0
        return self.grade_after - self.grade_before

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": self.goals,
            "rounds": [r.to_dict() for r in self.rounds],
            "rounds_run": self.rounds_run,
            "retired": self.retired,
            "reached_fixpoint": self.reached_fixpoint,
            "circuit_broken": self.circuit_broken,
            "max_rounds_hit": self.max_rounds_hit,
            "total_landed": self.total_landed,
            "grade_before": self.grade_before, "grade_after": self.grade_after,
            "grade_delta": self.grade_delta,
            "applied": self.applied,
        }


def _grade(project_root: str | Path) -> int:
    """The project's health grade, or ``-1`` when it cannot be computed (the same
    best-effort pattern ``chain_compiler._grade`` / ``dream_develop._grade`` /
    ``fractal_develop._grade`` use)."""
    try:
        from app.engine.health_score import grade
        return grade(str(project_root)).score
    except Exception:
        return -1


def _land_one_goal(project_root: str | Path, goal: str, *, max_steps: int,
                   verify: bool, apply: bool, covered_only: bool) -> RoundResult:
    """Land ONE goal through the RIGHT engine and normalize the outcome.

    Resolves the goal to its leaves (:func:`app.engine.fractal_develop.resolve_goal`
    — the SAME decomposition ``orchestrate_goal`` uses internally): an unknown
    name resolves to ``[]`` (``status="unknown"``, retired by the caller). With
    TWO OR MORE leaves the goal is COMPOSABLE, so it lands atomically via
    :func:`app.engine.project_goal_orchestrator.orchestrate_goal` (``via``
    ``"orchestrate"``). With exactly ONE leaf (or a bare objective name — which
    ``resolve_goal`` also returns as a single-element list) there is nothing to
    COMPOSE, mirroring ``orchestrate_goal``'s OWN <2-leaves refusal — so this
    falls back to :func:`app.engine.objective_compiler.compile_objective`
    directly (``via`` ``"compile"``), classified red/landed with the SAME
    :func:`app.engine.chain_compiler._step_is_red` the chain compiler uses
    (imported, never reimplemented). Pure dispatch — no new gate logic; every
    byte still goes through the existing suite-gated writers."""
    from app.engine.fractal_develop import resolve_goal

    leaves = resolve_goal(goal)
    if not leaves:
        return RoundResult(goal=goal, status="unknown",
                           reason=f"'{goal}' resolves to no leaves (unknown goal "
                                  "or objective)")
    if len(leaves) >= 2:
        return _land_via_orchestrate(project_root, goal, verify=verify,
                                     apply=apply, covered_only=covered_only)
    return _land_via_compile(project_root, goal, max_steps=max_steps,
                             verify=verify, apply=apply, covered_only=covered_only)


def _land_via_orchestrate(project_root: str | Path, goal: str, *, verify: bool,
                          apply: bool, covered_only: bool) -> RoundResult:
    """The ≥2-leaf branch: land ``goal`` atomically via ``orchestrate_goal``."""
    from app.engine.project_goal_orchestrator import orchestrate_goal

    landing = orchestrate_goal(project_root, goal, verify=verify, apply=apply,
                               covered_only=covered_only)
    if landing.rolled_back:
        return RoundResult(goal=goal, status="rolled_back", via="orchestrate",
                           reason=landing.reason)
    if landing.refused:
        return RoundResult(goal=goal, status="refused", via="orchestrate",
                           reason=landing.reason)
    status = "landed" if landing.applied or landing.files_changed else "empty"
    return RoundResult(goal=goal, status=status, via="orchestrate",
                       files_changed=list(landing.files_changed))


def _land_via_compile(project_root: str | Path, goal: str, *, max_steps: int,
                      verify: bool, apply: bool, covered_only: bool) -> RoundResult:
    """The 1-leaf fallback: land ``goal`` (a bare objective) via
    ``compile_objective`` — the SAME single-objective path ``orchestrate_goal``
    itself declines (fewer than two composable leaves), classified with the
    SHARED ``_step_is_red`` the chain compiler uses."""
    from app.engine.objective_compiler import compile_objective

    campaign = compile_objective(project_root, objective=goal, max_steps=max_steps,
                                 verify=verify, apply=apply,
                                 covered_only=covered_only)
    if _step_is_red(campaign):
        return RoundResult(goal=goal, status="rolled_back", via="compile",
                           reason="a move rolled back — the suite went red")
    if campaign.steps:
        files = sorted({s.target for s in campaign.steps if s.target})
        return RoundResult(goal=goal, status="landed", via="compile",
                           files_changed=files)
    if campaign.blocked:
        return RoundResult(goal=goal, status="refused", via="compile",
                           reason="; ".join(campaign.blocked))
    return RoundResult(goal=goal, status="empty", via="compile")


def _run_round(project_root: str | Path, pending: list[str], *, max_steps: int,
               verify: bool, apply: bool, covered_only: bool,
               max_rollbacks_per_round: int) -> FixpointRound:
    """Run ONE round: sequence ``pending`` in proven topological order, land each,
    and stop mid-round the moment the circuit breaker trips.

    ``pending`` is already the live (not-retired) goal set for this round; the
    order is re-derived EVERY round (a goal landed earlier this round may have
    changed what a later goal's proven prerequisite needs — the same
    re-measure-against-the-current-tree discipline ``chain_compiler.run_chain``
    uses across steps). Deterministic: :func:`topological_sort` is a pure,
    stable function of ``pending``."""
    order = topological_sort(pending)
    round_ = FixpointRound(order=order)
    rollbacks = 0
    for goal in order:
        result = _land_one_goal(project_root, goal, max_steps=max_steps,
                                verify=verify, apply=apply,
                                covered_only=covered_only)
        round_.results.append(result)
        if result.status == "rolled_back":
            rollbacks += 1
            if rollbacks >= max_rollbacks_per_round:
                round_.circuit_broken = True
                break
    return round_


def _run_rounds_loop(project_root: str | Path, report: FixpointReport,
                     live: list[str], *, max_rounds: int, max_steps_per_goal: int,
                     verify: bool, apply: bool, covered_only: bool,
                     max_rollbacks_per_round: int) -> set[str]:
    """The round-by-round convergence walk, split out of
    :func:`run_goal_fixpoint` to keep that function under the complexity
    ceiling. Mutates ``report`` in place (appends each round, sets the stop-flag)
    and returns the FINAL retired set. Pure control flow — no gate logic; every
    round's landing runs through :func:`_run_round`."""
    retired: set[str] = set()
    for _round_num in range(1, max_rounds + 1):
        pending = [g for g in live if g not in retired]
        if not pending:
            report.reached_fixpoint = True
            break
        round_ = _run_round(
            project_root, pending, max_steps=max_steps_per_goal, verify=verify,
            apply=apply, covered_only=covered_only,
            max_rollbacks_per_round=max_rollbacks_per_round)
        report.rounds.append(round_)
        retired.update(r.goal for r in round_.results
                       if r.status in ("rolled_back", "unknown"))
        if round_.circuit_broken:
            report.circuit_broken = True
            break
        if not round_.landed_goals:
            report.reached_fixpoint = True
            break
    else:
        report.max_rounds_hit = True
    return retired


def run_goal_fixpoint(project_root: str | Path, goals: list[str], *,
                      max_rounds: int = 10, max_steps_per_goal: int = 25,
                      verify: bool = True, apply: bool = False,
                      covered_only: bool = False,
                      max_rollbacks_per_round: int = 3) -> FixpointReport:
    """Converge a whole GOAL SET to a FIXPOINT — round after round, each round a
    proven topological sweep, until nothing lands or the round cap is hit.

    Each round: ``pending = live goals − retired goals``; the pending set is
    ordered by :func:`app.engine.objective_dependencies.topological_sort` (a
    proven prerequisite lands before its dependent, within THIS caller-supplied
    set); each goal in that order is landed through :func:`_land_one_goal`. A
    goal that ROLLS BACK is PERMANENTLY retired (it never runs again in a LATER
    round of this same fixpoint — a goal that cannot land cleanly doesn't churn
    the tree round after round); an ``unknown`` goal is retired immediately
    (never a wasted repeated attempt). A round that trips
    ``max_rollbacks_per_round`` STOPS MID-ROUND (``circuit_broken=True`` on both
    that round and the report) — an honest early stop, never a forced landing.

    FIXPOINT: a round that lands NOTHING (every goal empty/refused/already
    retired) means there is no further safe, verifiable progress this set can
    make — the loop stops (``reached_fixpoint=True``). ``max_rounds`` is the honest
    cap when the set keeps landing something every round.

    ``apply`` defaults to False (DRY-RUN: reports what each round WOULD land,
    writing nothing — ``orchestrate_goal``/``compile_objective`` are both called
    with ``apply=False``, so this never grades a dry run). ``covered_only``
    threads to BOTH landing engines — the SAFE-by-default sweep policy: a move a
    green suite can't vouch for is withheld, not landed (the CLI layer forces
    this True, unattended, exactly like ``cmd_evolve``).

    Deterministic: the round loop and the topological order are pure functions
    of the goal set and the tree state; the report body carries no clock or
    randomness."""
    report = FixpointReport(goals=list(goals), applied=apply)
    if not goals:
        report.reached_fixpoint = True
        return report
    before = _grade(project_root) if apply else -1
    report.grade_before = before

    live = list(dict.fromkeys(goals))  # de-duplicated, first-seen order
    retired = _run_rounds_loop(
        project_root, report, live, max_rounds=max_rounds,
        max_steps_per_goal=max_steps_per_goal, verify=verify, apply=apply,
        covered_only=covered_only, max_rollbacks_per_round=max_rollbacks_per_round)

    report.retired = sorted(retired)
    report.grade_after = _grade(project_root) if (apply and before >= 0) else before
    return report


_STATUS_TAG = {
    "landed": "✅ landed",
    "empty": "· nothing to do",
    "refused": "⛔ refused",
    "rolled_back": "🛑 rolled back (retired)",
    "unknown": "❓ unknown goal (retired)",
}


def _grade_line(report: FixpointReport) -> str:
    """The single before→after health-grade line, or ``""`` when there is no
    grade to show (a dry run / uncomputable grade). Mirrors
    ``chain_compiler._grade_line``'s shape."""
    if not (report.applied and report.grade_before >= 0 and report.grade_after >= 0):
        return ""
    d = report.grade_delta
    arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
    return (f"\n**Health grade: {report.grade_before} → {report.grade_after} "
            f"({'+' if d > 0 else ''}{d} {arrow})** — the fixpoint's measured effect.")


def _stop_reason(report: FixpointReport) -> str:
    if report.circuit_broken:
        return "circuit breaker tripped (too many rollbacks in one round)"
    if report.reached_fixpoint:
        return "reached a fixpoint (a round landed nothing)"
    if report.max_rounds_hit:
        return f"hit the round cap ({len(report.rounds)} rounds)"
    return "stopped"


def _render_round_result(r: RoundResult) -> str:
    """One goal's line within a round — split out to keep the rounds loop flat."""
    tag = _STATUS_TAG.get(r.status, r.status)
    via = f" via `{r.via}`" if r.via else ""
    detail = f" — {r.reason}" if r.reason else ""
    return f"- `{r.goal}` · {tag}{via}{detail}"


def _render_rounds(report: FixpointReport) -> list[str]:
    """The ``## Rounds`` section: each round's header plus its per-goal lines,
    split out of :func:`render_fixpoint_markdown` to keep that function under
    the complexity ceiling."""
    lines = ["", "## Rounds"]
    for i, round_ in enumerate(report.rounds, 1):
        lines.append(f"\n### Round {i} — order: {' → '.join(round_.order)}")
        lines.extend(_render_round_result(r) for r in round_.results)
    return lines


def _render_fixpoint_notices(report: FixpointReport) -> list[str]:
    """The optional grade / circuit-breaker / retired-set notice lines, split out
    of :func:`render_fixpoint_markdown` to keep that function under the
    complexity ceiling. Returns only the lines that actually apply."""
    lines: list[str] = []
    grade_line = _grade_line(report)
    if grade_line:
        lines.append(grade_line)
    if report.circuit_broken:
        lines.append("\n**Circuit breaker tripped** — a round rolled back too "
                     "many goals, so the loop stopped mid-round honestly. "
                     "Nothing broken (every rolled-back goal was reverted).")
    if report.retired:
        lines.append(f"\n**Retired: {', '.join(report.retired)}** — rolled back "
                     "or unknown; never re-attempted.")
    return lines


def render_fixpoint_markdown(report: FixpointReport) -> str:
    """Render the goal-set fixpoint run as a deterministic, CLOCK-FREE report.

    Lists each round's topological order and per-goal outcome, the retired set,
    the stop reason, and the single before→after health grade. An empty goal set
    renders an honest refusal. NO timestamp anywhere, so two runs on the same
    tree and goal set render byte-identical."""
    if not report.goals:
        return ("# Develop fixpoint\n\n_Empty goal set — pass one or more goals "
                "(e.g. `--goals reduce-debt,tidy`) for the fixpoint loop to "
                "run._\n")
    verb = "Landed" if report.applied else "Would land"
    reason = _stop_reason(report)
    lines = [f"# Develop fixpoint — {reason}", "",
             f"_Goal set: {', '.join(report.goals)} · round-based · "
             "topologically ordered · deterministic · zero tokens_", "",
             f"{verb} **{report.total_landed} goal-round(s)** across "
             f"{report.rounds_run} round(s)."]
    lines.extend(_render_fixpoint_notices(report))
    lines.extend(_render_rounds(report))
    lines.append("")
    return "\n".join(lines)
