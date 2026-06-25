"""`dream_develop` — the autonomous, value-led, proof-carrying overnight LANDING
CHAIN, wired as ``apex dream --land``.

This is the concrete-dev × dream FUSION: the project's #1 differentiator. Where
``apex develop`` lands ONE objective and ``apex dream`` only *learns*, this
composes them into a single overnight motion that a buyer wakes up to —

  1. **value-led order** — ``resolve_goal("ship-value", value_led=True)`` flattens
     the North-Star concrete chain into a deterministic, hashseed-invariant
     concrete-first leaf order (a function body before a sorted import);
  2. **dream-derived scope** — ``dream_confluence_modules(root)`` names the files
     the organism's multi-night dream graduated as confluences (high churn × hub ×
     co-change). The landing is confined to those files; when the dream graduates
     none (a fresh / never-``--curate``-d project), the chain runs WHOLE-TREE
     (``scope_module=None``) so it still lands;
  3. **verified landing per step** — each objective runs through the EXISTING
     ``compile_objective`` propose→apply→measure→select loop, suite-gated with
     byte-for-byte ``apply_rename`` rollback. A move that fails its gate is rolled
     back and NOT counted — verified-or-refused, never faked;
  4. **one before→after grade** — the whole chain's measured effect, the same
     ``health_score.grade`` proof ``fractal_develop`` reports.

The result is ONE deterministic :class:`DreamChainReport`: the ordered landed
contributions (operator / target / buyer-value / verification-tier), the total
verified moves, and the single health-grade delta.

This module is **pure orchestration over shipped primitives** — it adds ZERO new
write path, reuses the verified-with-rollback compiler for every byte it lands,
and registers NO new develop objective (it COMPOSES the existing ``ship-value``
chain), so there is no Facet-parity obligation. Default is DRY-RUN; ``apply=True``
writes.

DETERMINISM: the report body carries no clock and no randomness — the value-led
order is hashseed-invariant, the confluence derivation is read-only/idempotent,
and the renderer carries NO wall-clock header (unlike ``render_dream_markdown``'s
``datetime.now()``), so two runs on the same tree render byte-identical.
Stdlib-only; offline by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.objective_compiler import CompileResult, compile_objective

__all__ = [
    "LandedContribution", "DreamChainReport",
    "dream_develop", "render_dream_chain_markdown",
]

# The composed concrete goal: the North-Star LAND-working-code chain. Run
# value-led so the highest-buyer-value concrete objective is attempted first.
CHAIN_GOAL = "ship-value"


@dataclass
class LandedContribution:
    """One verified move the chain landed — the buyer-facing unit of the report.

    A flattened view over a :class:`CompileStep`: which ``operator`` ran on which
    ``target``, the buyer ``value`` of that class of change (``move_value``), and
    the honest ``tier`` the suite earned (``verified`` only when a test actually
    EXERCISED the change; ``weak`` for green-but-unreferencing; ``no-suite`` when
    nothing verified it). ``objective`` names the chain step it came from."""
    objective: str
    operator: str
    target: str
    description: str
    value: float
    tier: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective, "operator": self.operator,
            "target": self.target, "description": self.description,
            "value": self.value, "tier": self.tier,
        }


@dataclass
class DreamChainReport:
    """The overnight landing chain's deterministic result — mirrors
    :meth:`GoalResult.to_dict` for a familiar JSON shape.

    ``goal`` is the composed concrete chain (always ``ship-value``); ``objectives``
    is its value-led leaf order; ``modules`` is the dream-derived confluence scope
    (empty ⇒ the chain ran whole-tree); ``results`` is the per-objective
    ``CompileResult`` (the verified-with-rollback campaigns, in chain order);
    ``contributions`` is the flattened buyer view of every landed move;
    ``grade_before``/``grade_after`` is the single health proof (``-1`` on a dry
    run, which writes nothing to measure)."""
    goal: str
    objectives: list[str]
    modules: list[str] = field(default_factory=list)
    results: list[CompileResult] = field(default_factory=list)
    grade_before: int = -1
    grade_after: int = -1
    applied: bool = False

    @property
    def whole_tree(self) -> bool:
        """Did the chain run whole-tree (the dream graduated no confluence)?"""
        return not self.modules

    @property
    def total_moves(self) -> int:
        return sum(len(r.steps) for r in self.results)

    @property
    def verified_moves(self) -> int:
        """Moves a test GENUINELY exercised — the honest never-fake-green count
        (a green-but-unreferencing suite does NOT count as verified)."""
        return sum(1 for r in self.results for s in r.steps if s.coverage_verified)

    @property
    def grade_delta(self) -> int:
        if self.grade_before < 0 or self.grade_after < 0:
            return 0
        return self.grade_after - self.grade_before

    @property
    def contributions(self) -> list[LandedContribution]:
        """Every landed move as a buyer-facing contribution, in chain order."""
        from app.engine.move_value import objective_value
        out: list[LandedContribution] = []
        for r in self.results:
            value = objective_value(r.objective)
            for s in r.steps:
                out.append(LandedContribution(
                    objective=r.objective, operator=s.operator, target=s.target,
                    description=s.description, value=value, tier=_step_tier(s)))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "objectives": self.objectives,
            "modules": self.modules, "whole_tree": self.whole_tree,
            "results": [r.to_dict() for r in self.results],
            "contributions": [c.to_dict() for c in self.contributions],
            "grade_before": self.grade_before, "grade_after": self.grade_after,
            "grade_delta": self.grade_delta, "total_moves": self.total_moves,
            "verified_moves": self.verified_moves, "applied": self.applied,
        }


def _step_tier(step: Any) -> str:
    """The honest verification tier a landed step earned — coverage-aware.

    ``verified`` only when the suite ran green AND a test exercises the change;
    ``weak`` when green but no test references it; ``no-suite`` when nothing ran.
    A move that FAILED its gate was rolled back and never reaches a step, so these
    are the only tiers a reported contribution can hold."""
    if not getattr(step, "verified", False):
        return "no-suite"
    return "verified" if getattr(step, "coverage_verified", False) else "weak"


def _grade(project_root: str | Path) -> int:
    """The project's health grade, or ``-1`` when it cannot be computed (the same
    best-effort pattern ``fractal_develop._grade`` uses)."""
    try:
        from app.engine.health_score import grade
        return grade(str(project_root)).score
    except Exception:
        return -1


def _chain_objectives(value_led: bool = True) -> list[str]:
    """The concrete chain's leaf objectives, value-led (concrete-first) by default.

    Reuses ``fractal_develop.resolve_goal`` — the deterministic, hashseed-invariant
    flatten — so the chain order matches the rest of the develop core."""
    from app.engine.fractal_develop import resolve_goal
    return resolve_goal(CHAIN_GOAL, value_led=value_led)


def _chain_scope(project_root: str | Path) -> list[str]:
    """The dream-derived confluence modules to scope the chain to, or ``[]``.

    Reuses ``dream_landing.dream_confluence_modules`` — which already falls back to
    a read-only LIVE derivation under the unchanged ``PROMOTE_STREAK`` /
    ``PROMOTE_CONFIDENCE`` gate — so the scope is the files the organism's own
    multi-night dream flagged. ``[]`` ⇒ run whole-tree."""
    from app.engine.dream_landing import dream_confluence_modules
    return dream_confluence_modules(project_root)


def dream_develop(project_root: str | Path, max_steps: int = 25,
                  verify: bool = True, apply: bool = False,
                  fast: bool = False) -> DreamChainReport:
    """Land the value-led concrete chain, scoped to the dream's confluences.

    In one motion: derive the concrete-first objective order
    (``ship-value``, value-led), scope it to the dream-graduated confluence
    modules (or whole-tree when the dream names none), run each objective through
    the EXISTING ``compile_objective`` verified-with-rollback loop, and emit one
    :class:`DreamChainReport` — the ordered landed contributions, the verified
    move count, and a single before→after health grade.

    ``apply`` defaults to ``False`` (DRY-RUN: it reports the moves it WOULD land,
    writing nothing); ``apply=True`` writes, every byte gated by the suite with
    auto-rollback. ``fast`` scopes the per-move gate to the changed module
    (``compile_objective(scope_verify=...)``) for a quicker overnight pass.

    Soundness: a move that fails its gate is rolled back and NOT counted, and a
    project with nothing landable yields an honest EMPTY chain — never a faked
    one. Deterministic: the report body carries no clock or randomness."""
    objectives = _chain_objectives(value_led=True)
    modules = _chain_scope(project_root)
    before = _grade(project_root) if apply else -1
    report = DreamChainReport(goal=CHAIN_GOAL, objectives=objectives,
                              modules=modules, applied=apply, grade_before=before)
    # Whole-tree is one None "scope"; a confluence run scopes to each named module.
    scopes: list[str | None] = list(modules) if modules else [None]
    for obj in objectives:
        for scope in scopes:
            campaign = compile_objective(
                project_root, objective=obj, max_steps=max_steps, verify=verify,
                apply=apply, scope_module=scope, scope_verify=fast)
            if campaign.steps or campaign.fitness_start > 0:
                report.results.append(campaign)
    report.grade_after = _grade(project_root) if (apply and before >= 0) else before
    return report


_TIER_TAG = {
    "verified": "✅ verified",
    "weak": "⚠️ weak (suite green but uncovered)",
    "no-suite": "⚠️ no-suite",
}


def render_dream_chain_markdown(report: DreamChainReport) -> str:
    """Render the overnight landing chain as a deterministic, CLOCK-FREE report.

    Headlines the scope (dream confluences vs. whole-tree), then lists each landed
    contribution in value-led chain order with its operator/target/buyer-value and
    honest verification tier, and the single before→after health grade. An empty
    chain renders an honest "nothing landable" refusal — never a faked move.

    NO timestamp anywhere: the header carries no wall-clock (unlike
    ``render_dream_markdown``), so two runs on the same tree render byte-identical."""
    verb = "Landed" if report.applied else "Would land"
    scope = ("whole-tree (the dream graduated no confluence)" if report.whole_tree
             else "dream confluences: " + ", ".join(report.modules))
    lines = ["# Dream-develop — the overnight landing chain", "",
             f"_Composes `{report.goal}` (value-led, concrete-first) · "
             "deterministic · zero tokens_", "",
             f"_Scope: {scope}._", ""]
    contributions = report.contributions
    if not contributions:
        lines += ["_Nothing landable — the chain refused honestly rather than "
                  "faking a move. Run `apex dream` to accrue confluences, or add "
                  "fillable stubs / untested code for the chain to land on._", ""]
        return "\n".join(lines)
    lines.append(f"{verb} **{report.verified_moves} verified move(s)** "
                 f"({report.total_moves} total) across "
                 f"{len(report.objectives)} chain objective(s).")
    if report.applied and report.grade_before >= 0 and report.grade_after >= 0:
        d = report.grade_delta
        arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
        lines.append(f"\n**Health grade: {report.grade_before} → "
                     f"{report.grade_after} ({'+' if d > 0 else ''}{d} {arrow})** "
                     "— the chain's measured effect.")
    lines += ["", "## Landed contributions (value-led order)"]
    for i, c in enumerate(contributions, 1):
        tag = _TIER_TAG.get(c.tier, c.tier)
        lines.append(f"{i}. `{c.objective}` · {c.description} "
                     f"— buyer-value {c.value:.2f} · {tag}")
    lines.append("")
    return "\n".join(lines)
