"""Project-goal orchestrator — land a decomposed goal's leaves as ONE gated unit.

``apex develop goal X`` (:mod:`app.engine.fractal_develop`) already decomposes a
GOAL into its leaf objectives and runs each as its OWN suite-gated campaign. That
is correct per objective, but it leaves an INCOMPLETE-STATE gap the North Star
cares about: the leaves land INDEPENDENTLY, so an ``implement-stub`` fill can land
while the ``wire-exports`` that surfaces it does NOT (its own gate vetoed it, or it
found no move that pass) — the tree is left with a body nothing imports, or an
export of a symbol that isn't there yet. Each half was individually verified; the
GOAL as a whole is half-done.

This orchestrator closes that gap. It decomposes the SAME goal to the SAME leaf
objectives (:func:`fractal_develop.resolve_goal`), asks each leaf for its ONE
best single-file plan (the EXISTING per-objective planning — the move generators
:mod:`objective_compiler` already owns), then COMPOSES those single-file plans
into ONE multi-file :class:`~app.execution.cross_file_rename.RenamePlan` via
:func:`~app.execution.compose_plans.compose_plans`, and lands that composed plan
through the ONE legal gated writer,
:func:`~app.execution.cross_file_rename.apply_rename`. The result is atomic:
implement-stub + wire-exports land TOGETHER or NEITHER lands — one gate, and on
RED the whole goal is rolled back to its pre-change bytes.

Why this needs no new machinery — and adds none:
  * DECOMPOSITION is ``resolve_goal`` verbatim (read-only): same goal → same leaves.
  * Each LEAF PLAN is the existing move generator's first landable single-file
    plan (a ``Move.build_plan()`` thunk re-derived against the CURRENT tree) — the
    identical planning the Objective-Compiler runs, just STOPPED at plan
    construction (no per-leaf apply, no per-leaf gate).
  * COMPOSITION is ``compose_plans``: a pure, IO-free dict-union that REFUSES
    (lands nothing) on file-overlap / a blocked or empty sub-plan and NEVER calls
    ``apply_rename`` itself — so the single-gated-writer contract is preserved. The
    orchestrator HONORS that refusal (it reports it and lands nothing) rather than
    forcing a conflicting merge.
  * The SINGLE GATE and WHOLE-GOAL ROLLBACK are entirely ``apply_rename``'s: it
    writes every file in ``new_contents``, runs the suite ONCE, and on any
    regression restores ALL originals and deletes ALL created files byte-for-byte.
    There is NO gate logic here — never-fake-green rides the existing engine.
  * The DELTA-GREEN baseline (the RED-on-checkout tolerance the session/compiler
    already use) is captured ONCE via ``suite_failing_nodes`` and threaded to the
    one gate, so a correct composed landing isn't vetoed by an UNRELATED
    pre-existing failure while a true regression is still rolled back.

This is an ENGINE capability, not a develop objective: it registers nothing, pins
no count, and is never itself a leaf. Deterministic (fixed leaf order, a pure
plan-fold, clock/random-free report), offline, zero-token, LLM-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.compose_plans import compose_plans
from app.execution.cross_file_rename import RenamePlan, apply_rename

__all__ = [
    "LeafPlan", "GoalLanding", "ProjectGoalOrchestrator",
    "orchestrate_goal", "render_goal_landing_markdown",
]


@dataclass
class LeafPlan:
    """One leaf objective's contribution to the composed goal.

    ``target``/``file`` are set when the leaf produced a landable single-file plan;
    ``reason`` is set instead when it had no move to contribute (already satisfied,
    or every candidate was blocked) — an HONEST record of why a leaf did not join
    the composition, never a silent drop."""
    objective: str
    target: str = ""
    file: str = ""
    reason: str = ""

    @property
    def contributed(self) -> bool:
        return bool(self.file)

    def to_dict(self) -> dict[str, Any]:
        return {"objective": self.objective, "target": self.target,
                "file": self.file, "reason": self.reason,
                "contributed": self.contributed}


@dataclass
class GoalLanding:
    """The result of one whole-goal orchestration — a pure projection of the fold.

    ``applied`` is True only when the composed plan LANDED and HELD (the single gate
    passed); on a refusal or a rolled-back gate it is False and NOTHING is on the
    tree. No clock/random anywhere, so the same tree state yields a byte-identical
    result."""
    goal: str
    objectives: list[str] = field(default_factory=list)  # the resolved leaves, in order
    leaves: list[LeafPlan] = field(default_factory=list)
    applied: bool = False
    verified: bool = False        # the single gate ran green AND held (never faked)
    rolled_back: bool = False     # the composed plan regressed → WHOLE goal reverted
    refused: bool = False         # composition refused (overlap / blocked / <2 leaves)
    reason: str = ""              # why it refused / rolled back (honest disclosure)
    files_changed: list[str] = field(default_factory=list)
    diff: str = ""

    @property
    def contributing_leaves(self) -> list[LeafPlan]:
        return [leaf for leaf in self.leaves if leaf.contributed]

    @property
    def composed_files(self) -> int:
        return len(self.files_changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "objectives": self.objectives,
            "leaves": [leaf.to_dict() for leaf in self.leaves],
            "applied": self.applied, "verified": self.verified,
            "rolled_back": self.rolled_back, "refused": self.refused,
            "reason": self.reason, "files_changed": self.files_changed,
            "composed_files": self.composed_files, "diff": self.diff,
        }


def _leaf_single_file_plan(root: str, objective: str,
                           taken: set[str]) -> tuple[RenamePlan | None, str, str]:
    """The FIRST landable single-file plan a leaf objective offers, or a reason.

    Reuses the EXISTING per-objective planning verbatim: the objective's move
    generator (``objective_compiler``'s objectives map) proposes moves against the
    CURRENT tree, and each ``Move.build_plan()`` thunk is materialised in order.
    The first move whose plan is a clean single-file rewrite (exactly one file in
    ``new_contents``, no blockers) — touching a file no earlier leaf already claimed
    — is returned; ``taken`` is the running set of files already spoken for, so the
    fold never even offers ``compose_plans`` an overlapping pair (a distinct-file
    plan per leaf is what makes the union well-defined). Returns
    ``(plan, target, "")`` on success or ``(None, "", reason)`` when the leaf has
    nothing distinct to contribute. Pure plan construction — no writes, no gate."""
    from app.engine.objective_compiler import _objectives_map

    objectives = _objectives_map()
    spec = objectives.get(objective)
    if spec is None:
        return None, "", f"unknown objective '{objective}'"
    _fitness, generate = spec
    for move in generate(root):
        plan = move.build_plan()
        if plan.blockers or len(plan.new_contents) != 1:
            continue  # skip a blocked move or a plan that isn't single-file
        only = next(iter(plan.new_contents))
        if only in taken:
            continue  # another leaf already owns this file — keep the union disjoint
        return plan, move.target, ""
    return None, "", "no landable single-file move (already satisfied or all blocked)"


def _collect_leaf_plans(
    root: str, objectives: list[str],
) -> tuple[list[RenamePlan], list[LeafPlan]]:
    """Build each leaf's single-file plan, recording contributions and skips.

    Walks the leaves IN ORDER, threading the set of files already claimed so every
    contributed plan touches a DISTINCT file (the disjointness ``compose_plans``
    requires). Returns ``(plans, leaves)``: ``plans`` are the contributing
    single-file plans to fold; ``leaves`` is the full per-leaf record (contributed
    or skipped, with an honest reason). Deterministic — the leaf order and each
    generator are deterministic."""
    plans: list[RenamePlan] = []
    leaves: list[LeafPlan] = []
    taken: set[str] = set()
    for objective in objectives:
        plan, target, reason = _leaf_single_file_plan(root, objective, taken)
        if plan is None:
            leaves.append(LeafPlan(objective=objective, reason=reason))
            continue
        only = next(iter(plan.new_contents))
        taken.add(only)
        plans.append(plan)
        leaves.append(LeafPlan(objective=objective, target=target, file=only))
    return plans, leaves


def _compose_all(plans: list[RenamePlan]) -> RenamePlan:
    """Fold contributing single-file plans into ONE multi-file plan.

    A left fold through :func:`compose_plans` — the shared, pure, IO-free union
    that REFUSES (returns a blocked plan) on file-overlap or a blocked/empty
    sub-plan. Because the caller only ever passes DISJOINT single-file plans, the
    overlap branch is not expected here; but the fold still HONORS a refusal (it
    returns whatever ``compose_plans`` returned — a blocked plan lands nothing), so
    the soundness gate is never bypassed. Called only with ``len(plans) >= 2``."""
    merged = plans[0]
    for plan in plans[1:]:
        merged = compose_plans(merged, plan)
        if merged.blockers:
            return merged  # honor the refusal — do not force a conflicting merge
    return merged


def _campaign_baseline(root: str, verify: bool) -> frozenset[str] | None:
    """The DELTA-GREEN baseline failing-node set for the ONE gate, captured once.

    Mirrors the session/compiler policy: on a gated run, probe the suite ONCE
    (:func:`~app.execution._apply_verify.suite_failing_nodes`) so a correct composed
    landing isn't vetoed by an UNRELATED pre-existing failure, while a true
    regression is still rolled back. Returns the failing set on a RED baseline, or
    ``None`` on a green baseline / un-gated run (absolute-green — byte-identical to a
    plain ``apply_rename``). One extra suite run per goal, never per leaf."""
    if not verify:
        return None
    from app.execution._apply_verify import suite_failing_nodes

    _available, failing = suite_failing_nodes(Path(root))
    return failing or None


def _refusal(landing: GoalLanding, reason: str) -> GoalLanding:
    """Mark ``landing`` as a refusal that lands NOTHING and return it."""
    landing.refused = True
    landing.reason = reason
    return landing


def orchestrate_goal(project_root: str | Path, goal: str, *,
                     verify: bool = True, apply: bool = True,
                     value_led: bool = False,
                     covered_only: bool = False) -> GoalLanding:
    """Land a decomposed goal's leaf objectives as ONE gated, atomic unit.

    Decompose ``goal`` to its leaves (:func:`fractal_develop.resolve_goal`), build
    each leaf's ONE best single-file plan, COMPOSE the (distinct-file) plans into a
    single multi-file plan (:func:`compose_plans`), and land it through the ONE
    gated writer (:func:`apply_rename`). The whole goal lands atomically or — on any
    regression the single gate catches — the ENTIRE goal is rolled back to its
    pre-change bytes (implement-stub + wire-exports land together or neither).

    Refuses (lands nothing) when the goal is unknown, when fewer than TWO leaves
    offered a landable distinct-file plan (there is nothing to COMPOSE — the caller
    should use the per-objective path for a single change), or when ``compose_plans``
    refuses. ``apply=False`` is a dry run: it composes and reports the plan without
    writing.

    ``covered_only`` (DEFAULT False = byte-identical to today) is the SAME
    SAFE-by-default policy :func:`app.engine.objective_compiler.compile_objective`
    exposes: threaded to the single ``apply_rename`` gate at Tier 1, a composed
    landing whose green suite cannot VOUCH for the change (no test exercises it)
    is withheld (rolled back, reported honestly) rather than landed silently. Off
    by default so every existing caller (the per-objective ``--goal`` CLI path,
    which leaves a human reviewing the diff) is unchanged byte-for-byte; an
    unattended caller (a headless fixpoint round) opts in. Deterministic,
    offline, zero-token; no new gate logic — the covered-only check lives inside
    ``apply_rename`` itself."""
    from app.engine.fractal_develop import resolve_goal

    root = str(project_root)
    objectives = resolve_goal(goal, value_led=value_led)
    landing = GoalLanding(goal=goal, objectives=objectives)
    if not objectives:
        return _refusal(landing, f"unknown goal '{goal}' — decomposes to nothing")

    plans, landing.leaves = _collect_leaf_plans(root, objectives)
    if len(plans) < 2:
        return _refusal(
            landing, "fewer than two leaves produced a landable plan — nothing to "
                     "compose (use the per-objective develop path for one change)")

    composed = _compose_all(plans)
    if composed.blockers:
        return _refusal(landing, "; ".join(composed.blockers))
    landing.files_changed = sorted(composed.new_contents)
    landing.diff = composed.render_diff()
    if apply:
        _land_composed(landing, root, composed, verify, covered_only)
    return landing


def _land_composed(landing: GoalLanding, root: str, composed: RenamePlan,
                   verify: bool, covered_only: bool = False) -> None:
    """Land the composed plan through the ONE gate, recording the atomic outcome.

    The single gated writer is :func:`apply_rename` with ``impact_scope`` (only the
    tests the changed files touch) and the once-captured delta-green baseline. The
    whole-goal atomicity is ENTIRELY that call's: it writes every composed file,
    gates ONCE, and on regression restores ALL originals / deletes ALL created files
    — so on RED nothing lands (``rolled_back``), and on green the WHOLE goal holds
    (``verified`` iff the suite genuinely ran green). No gate logic here.

    ``covered_only`` forwards to ``apply_rename`` at Tier 1 (a composed goal is a
    multi-file behaviour change, never a Tier-0 semantics-preserving rewrite) —
    default False keeps this call BYTE-IDENTICAL to before covered-only existed."""
    baseline = _campaign_baseline(root, verify)
    result = apply_rename(root, composed, verify=verify, impact_scope=True,
                          baseline_failing=baseline,
                          covered_only=covered_only, tier=1)
    if not result.get("applied"):
        landing.rolled_back = bool(result.get("rolled_back"))
        landing.reason = str(result.get("reason") or "the single gate refused the goal")
        landing.files_changed = []
        landing.diff = ""
        return
    landing.applied = True
    landing.verified = result.get("verified") is True
    landing.files_changed = sorted(result.get("changed_files") or landing.files_changed)


class ProjectGoalOrchestrator:
    """Run a decomposed goal's leaf objectives as ONE composed, once-gated landing.

    A thin, stateful handle over :func:`orchestrate_goal` for callers that hold a
    project root and pursue several goals: it fixes ``project_root`` and forwards
    each :meth:`land` / :meth:`preview` to the pure function. It owns NO gate logic,
    NO registry, and is NEVER itself a develop objective — the composition
    (:func:`compose_plans`), the single gate and the whole-goal rollback
    (:func:`apply_rename`) all live in the existing engine. Deterministic and
    offline; the same root + goal + tree state yields a byte-identical
    :class:`GoalLanding`."""

    def __init__(self, project_root: str | Path):
        self.project_root = str(project_root)

    def land(self, goal: str, *, verify: bool = True,
             value_led: bool = False) -> GoalLanding:
        """Compose the goal's leaves and land them atomically through the one gate."""
        return orchestrate_goal(self.project_root, goal, verify=verify,
                                apply=True, value_led=value_led)

    def preview(self, goal: str, *, value_led: bool = False) -> GoalLanding:
        """Compose the goal's leaves WITHOUT writing — the dry-run composition."""
        return orchestrate_goal(self.project_root, goal, verify=False,
                                apply=False, value_led=value_led)


def _landing_headline(landing: GoalLanding) -> list[str]:
    """The title + one-line verdict. Pure function of ``landing``."""
    head = [f"# Project-goal orchestration — `{landing.goal}`", ""]
    if landing.objectives:
        head += [f"_Decomposes into: {' → '.join(landing.objectives)}_", ""]
    if landing.refused:
        head.append(f"**Refused — nothing landed.** {landing.reason}")
    elif landing.rolled_back:
        head.append(
            "**Whole goal ROLLED BACK.** The composed plan regressed the suite, so "
            f"the ENTIRE goal was reverted to its pre-change bytes — nothing landed "
            f"({landing.reason}).")
    elif landing.applied:
        tag = "verified" if landing.verified else "applied (unverified)"
        head.append(
            f"**Landed {landing.composed_files} file(s) as ONE atomic goal "
            f"({tag}).** All leaves landed together through a single gate.")
    else:
        head.append(
            f"**Composed {landing.composed_files} file(s) — ready to land.** "
            "Run again with apply to gate and write them as one unit.")
    return head


def render_goal_landing_markdown(landing: GoalLanding) -> str:
    """Render a :class:`GoalLanding` as a readable report.

    Pure function of the landing: the decomposition, the atomic verdict (landed /
    rolled back / refused), the per-leaf contribution breakdown, and — when a plan
    was composed — the unified diff of the whole goal. No clock/random, so the same
    landing renders byte-identically every time."""
    lines = _landing_headline(landing)
    lines.append("")
    lines.append("## Leaves")
    for leaf in landing.leaves:
        if leaf.contributed:
            lines.append(f"- `{leaf.objective}` → {leaf.target} (`{leaf.file}`)")
        else:
            lines.append(f"- `{leaf.objective}` — skipped: {leaf.reason}")
    if landing.diff:
        lines.append("")
        lines.append("## The composed goal (one gated diff)")
        lines.append("")
        lines.append("```diff")
        lines.append(landing.diff.rstrip("\n"))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)
