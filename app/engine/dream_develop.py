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
    "build_dream_proof", "record_dream_outcomes", "record_dream_chain_memory",
]

# The composed concrete goal: the North-Star LAND-working-code chain. Run
# value-led so the highest-buyer-value concrete objective is attempted first.
CHAIN_GOAL = "ship-value"

# --- Interactivity bound (OPT-IN; default OFF = byte-identical to today) -------
#
# The unbounded chain composes ``compile_objective`` move-GENERATION for every
# ``ship-value`` objective over the whole module tree. That is the right
# exhaustive behaviour for ``apex dream --land`` (it runs overnight), but the
# proactive ``apex assist "what should I build next?"`` surface calls it as a
# DRY-RUN preview and a human is waiting — and one objective dominates the wall
# time by orders of magnitude.
#
# ``strengthen-tests`` GENERATES its candidate directions by MUTATION TESTING:
# it copies the project and runs the suite once per mutant, per module, across
# the whole source index (``app.execution.objectives.strengthen_tests._scan`` →
# ``mutation_tester``). Measured on humanize-4.15.0 (6 src modules) that single
# objective's dry-run is ~405s of a ~412s chain; every OTHER ``ship-value``
# objective's dry-run is sub-second to ~3s (~7s combined). The cost is NOT a
# per-module ``compile_objective`` fan-out (a whole-tree run has ONE scope) — it
# is that one generator's internal whole-tree mutation scan, which neither a
# ``scope_module`` (the generator scans the tree, then filters) nor a tighter
# mutant budget can bring to interactive latency: even scoped to a single module
# it costs ~60s (a full-suite pytest run per mutant is irreducibly seconds).
#
# So the interactivity bound EXCLUDES the un-previewable mutation objective(s)
# from the DRY-RUN preview — a small, explicit, reviewable set (mirroring
# ``soundness_audit._ORACLE_BACKED``), NOT the broad registry ``expensive`` flag:
# that flag also marks ``wire-exports`` / ``implement-stub`` / ``generate-usage-
# doc``, which are the HIGHEST-value directions AND cheap in a dry run (a bounded
# budget of suite runs), so skipping by the flag would drop the LEADING direction
# (``wire-exports``, value 0.90) — exactly what must be preserved. The excluded
# direction (``strengthen-tests``, value 0.88) is disclosed in the bounded
# narrative so the preview stays HONEST about what an interactive run skips.
_PREVIEW_SKIP_OBJECTIVES: frozenset[str] = frozenset({"strengthen-tests"})


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
    def verification_unavailable(self) -> str:
        """The loud "pytest is not importable" decline message a scoped campaign
        carried, or ``""`` when every campaign could be verified. A decline lands
        NOTHING (zero steps) — this exists so the renderer surfaces the honest
        "could not verify => did not touch" message instead of a false "nothing
        landable" empty chain (never-fake-green disclosure parity)."""
        for r in self.results:
            if r.verification_unavailable:
                return r.verification_unavailable
        return ""

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


def _chain_scope(project_root: str | Path,
                 value_ranked: bool = False) -> list[str]:
    """The dream-derived confluence modules to scope the chain to, or ``[]``.

    Reuses ``dream_landing.dream_confluence_modules`` — which already falls back to
    a read-only LIVE derivation under the unchanged ``PROMOTE_STREAK`` /
    ``PROMOTE_CONFIDENCE`` gate — so the scope is the files the organism's own
    multi-night dream flagged. ``[]`` ⇒ run whole-tree.

    ``value_ranked`` (DEFAULT False = the alphabetical order today's chain runs)
    asks ``dream_confluence_modules`` for the value-ranked order, so a chain with
    several confluences leads with the highest-buyer-value file. It re-orders the
    SAME module set (a permutation), so a single-/zero-confluence chain — and every
    default caller — is byte-for-byte unchanged."""
    from app.engine.dream_landing import dream_confluence_modules
    # Default keeps the historical single-argument call EXACTLY (so an existing
    # stub/monkeypatch still binds); only the opted-in path passes the keyword.
    if value_ranked:
        return dream_confluence_modules(project_root, value_ranked=True)
    return dream_confluence_modules(project_root)


def _bounded_chain(project_root: str | Path, value_ranked: bool, apply: bool,
                   max_modules: int | None,
                   preview_skip_mutation: bool) -> tuple[list[str], list[str]]:
    """The chain's ``(objectives, modules)`` AFTER the optional interactivity bound.

    Resolves the value-led ``ship-value`` objective order and the dream-derived
    confluence scope, then applies the two opt-in bounds:

    * ``preview_skip_mutation`` (a DRY-RUN-only bound — ``not apply``) drops the
      un-previewable mutation objective(s) (:data:`_PREVIEW_SKIP_OBJECTIVES`), so an
      apply run still lands every objective;
    * ``max_modules`` caps a multi-confluence scope to the top-K by centrality
      (:func:`_centrality_capped`), a no-op on a whole-tree / single-confluence run.

    With both bounds off (``None`` / ``False``) the result is the unbounded chain
    EXACTLY — the off-by-default byte-identity ``apex dream --land`` relies on."""
    objectives = _chain_objectives(value_led=True)
    if preview_skip_mutation and not apply:
        objectives = [o for o in objectives if o not in _PREVIEW_SKIP_OBJECTIVES]
    modules = _chain_scope(project_root, value_ranked=value_ranked)
    if max_modules is not None and modules:
        modules = _centrality_capped(modules, project_root, max_modules)
    return objectives, modules


def _centrality_capped(modules: list[str], project_root: str | Path,
                       max_modules: int) -> list[str]:
    """The top ``max_modules`` confluence ``modules`` by FAN-IN centrality —
    the cheap, deterministic pre-rank that bounds a multi-confluence chain's
    per-module ``compile_objective`` fan-out for an interactive preview.

    Reuses ``move_centrality.module_in_degrees`` (the SAME ``module path ->
    number of internal importers`` map the value-aware move loop already trusts —
    a pure full-tree walk, no clock, memoized per root) and keeps the highest-
    fan-in modules first, every tie broken by the existing alphabetical key, so
    the kept SET is total and fully deterministic (two runs on the same tree keep
    the identical modules). A module the centrality map does not name scores 0 and
    sorts by its path, so the bound never drops a module non-deterministically.

    Ordering+truncation ONLY: the result is a deterministic top-K SUBSET of the
    input — a real subset of the dream's own graduated confluences, never a
    different membership — so a bounded run can only land FEWER of the same
    confluences, never a fabricated one. ``max_modules <= 0`` or a list already at
    or under the cap is returned unchanged (nothing to bound)."""
    if max_modules <= 0 or len(modules) <= max_modules:
        return list(modules)
    from app.engine.move_centrality import module_in_degrees
    degrees = module_in_degrees(project_root)
    ranked = sorted(modules, key=lambda m: (-degrees.get(m, 0), m))
    return ranked[:max_modules]


def dream_develop(project_root: str | Path, max_steps: int = 25,
                  verify: bool = True, apply: bool = False,
                  fast: bool = False, value_ranked: bool = False,
                  max_modules: int | None = None,
                  preview_skip_mutation: bool = False,
                  covered_only: bool = False) -> DreamChainReport:
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

    ``value_ranked`` (DEFAULT False = today's alphabetical confluence order) leads
    the chain with the highest expected-landable-buyer-value confluence first
    (:func:`_chain_scope`). It re-orders WHICH MODULE the chain visits first, never
    WHICH objectives or moves run, so a single-/zero-confluence chain and every
    default caller stay byte-for-byte unchanged — the value order can only front-
    load value the alphabetical order would have landed anyway, never fake-green.

    ``max_modules`` and ``preview_skip_mutation`` are the INTERACTIVITY BOUND for
    the proactive ``apex assist`` preview (BOTH DEFAULT off ⇒ ``None`` / ``False``
    ⇒ byte-identical to today; ``apex dream --land`` never passes them, so its
    exhaustive path is untouched). They make the DRY-RUN preview answer in seconds
    on a multi-module project while keeping the leading value-led directions:

    * ``max_modules`` (DEFAULT None = every graduated confluence) caps a multi-
      confluence chain's per-module ``compile_objective`` fan-out to the top-K
      confluences by FAN-IN centrality (:func:`_centrality_capped`). A real top-K
      subset of the dream's own confluences, fully deterministic; a no-op on the
      common whole-tree / single-confluence run.
    * ``preview_skip_mutation`` (DEFAULT False) drops the un-previewable MUTATION-
      testing objective(s) (:data:`_PREVIEW_SKIP_OBJECTIVES` — ``strengthen-
      tests``) from the DRY-RUN preview: their generation runs the suite once per
      mutant per module, which is irreducibly seconds-per-module and dominates the
      wall time (measured ~405s of ~412s on humanize), and no scope/budget brings
      it to interactive latency. The skip is REFUSED on an apply run (``apply``
      True), so ``--land --apply`` still lands every objective — only the preview
      is bounded. The displayed directions stay a HONEST subset (the leading
      ``wire-exports`` is preserved; the skipped ``strengthen-tests`` is disclosed
      by the narrative), never fabricated.

    ``covered_only`` (DEFAULT False = byte-identical to today) is threaded
    verbatim into EVERY ``compile_objective`` call — the SAME SAFE-by-default
    autonomous-SWEEP gate ``compile_objective(covered_only=...)`` documents: a
    move whose green suite no test exercises is withheld (previewed, not landed)
    rather than silently landed. ``apex dream --land`` is the project's only
    UNATTENDED landing surface (no human reviews the diff between chain steps),
    so its CLI caller (``_cmd_dream_land``) forces this True via
    ``resolve_covered_only(unattended=True)`` — the SAME single-source-of-truth
    policy ``apex evolve``/the daemon force for their own unattended loops
    (#115's precedent). A direct/programmatic caller (this function's default,
    and ``apex assist``'s DRY-RUN preview) is unaffected: the parameter only
    matters on an ``apply=True`` campaign (a DRY RUN never reaches the gated
    apply loop — see ``compile_objective``), so the preview path is byte-
    identical regardless of this flag. Strictly DEMOTE-direction: it can only
    WITHHOLD a move that would otherwise land, never land one that wouldn't.

    Soundness: a move that fails its gate is rolled back and NOT counted, and a
    project with nothing landable yields an honest EMPTY chain — never a faked
    one. Deterministic: the report body carries no clock or randomness, and both
    bounds select by a stable key (centrality+path / a fixed name set), so the
    SAME (project, bound) preview renders byte-identical run to run."""
    # Resolve the value-led objective order + dream scope, applying the optional
    # interactivity bound (both off ⇒ the unbounded chain, byte-identical to today).
    objectives, modules = _bounded_chain(
        project_root, value_ranked, apply, max_modules, preview_skip_mutation)
    before = _grade(project_root) if apply else -1
    report = DreamChainReport(goal=CHAIN_GOAL, objectives=objectives,
                              modules=modules, applied=apply, grade_before=before)
    # Whole-tree is one None "scope"; a confluence run scopes to each named module.
    scopes: list[str | None] = list(modules) if modules else [None]
    for obj in objectives:
        for scope in scopes:
            campaign = compile_objective(
                project_root, objective=obj, max_steps=max_steps, verify=verify,
                apply=apply, scope_module=scope, scope_verify=fast,
                covered_only=covered_only)
            # Retain a VERIFICATION-UNAVAILABLE decline (fitness 0, no steps) so its
            # loud "pytest can't verify here" message is surfaced rather than dropped
            # as an empty "nothing landable" chain — the chain COULD NOT verify, which
            # is exactly what the buyer must be told (parity with compile_all /
            # compile_goal / _develop_auto). It never makes anything land.
            if (campaign.steps or campaign.fitness_start > 0
                    or campaign.verification_unavailable):
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
    if report.verification_unavailable:
        # A scoped campaign DECLINED up front: pytest is not importable, so NOTHING
        # was verified or landed. Surface ONLY the loud, actionable message (the SAME
        # wording the develop session / compile campaign use) — not the misleading
        # "nothing landable" line, which would read like a clean no-op rather than an
        # honest "could not verify => did not touch".
        lines += [f"⚠️ {report.verification_unavailable}", ""]
        return "\n".join(lines)
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


# --- Proof trail: the dream chain's landings as proof-of-fix evidence ---------
#
# A LANDED ``apex dream --land --apply`` move IS a verified-with-rollback fix, so
# its realized buyer value belongs on the SAME ``.apex/proof-of-fix.json`` trail
# value-landed / the owner-report / the tamper-seal already consume — making the
# dream differentiator's value legible cross-run. These two helpers are PURE and
# READ-ONLY over the report: each landed step (a ``CompileStep`` that ran green
# and HELD — a failed gate was rolled back and never appended) becomes one
# value-grade record matching ``proof_of_fix._fix_record``'s exact output
# contract, so ``value_landed`` / ``proof_hash`` / ``proof_manifest`` score it
# unchanged. We HONESTLY omit diff/changed_files (not threaded up through
# ``CompileStep``; faking them would betray the never-fake-green moat), and never
# fabricate a record for a move that did not hold.


def _dream_proof_records(report: DreamChainReport) -> list[dict]:
    """One value-grade proof record per LANDED step, in chain order.

    Each record matches ``proof_of_fix._fix_record``'s output contract exactly:
    ``finding`` (label/branch/action/operator/target), an empty ``transform_type``
    and ``None`` ``risk_tier``, ``outcome == "applied"`` (only landed-and-held
    steps reach ``report.results[i].steps``), empty ``changed_files``/``diff``
    (the compiler does not thread the diff up — we omit it honestly rather than
    fake it), the ``verification.strength.level`` carried by the step's coverage
    (the SAME ``function``/``module``/``test-change``/``none`` vocabulary
    value-landed reads), and a not-rolled-back ``rollback`` clause. Pure: no clock,
    no random, no I/O — a deterministic projection of the report."""
    records: list[dict] = []
    for r in report.results:
        for s in r.steps:
            records.append({
                "finding": {
                    "label": r.objective,
                    "branch": "",
                    "action": r.objective,
                    "operator": s.operator,
                    "target": s.target,
                },
                "transform_type": "",
                "risk_tier": None,
                "outcome": "applied",
                "changed_files": [],
                "diff": "",
                "verification": {
                    "performed": bool(s.verified),
                    "strength": {"level": s.coverage or "none"},
                },
                "rollback": {"occurred": False, "reason": ""},
            })
    return records


def build_dream_proof(report: DreamChainReport, project_root: str | Path) -> dict:
    """A proof-of-fix artifact for the dream chain, in ``build_proof``'s schema.

    Reuses ``proof_of_fix``'s ``SCHEMA``/``SCHEMA_VERSION``/``tool_version`` and the
    same top-level shape ``build_proof`` emits, with ``mode == "dream-land"``, the
    ``fixes`` list from :func:`_dream_proof_records`, and totals folded from the
    report (every landed step is an applied, never-rolled-back fix). So
    ``value_landed`` / ``proof_hash`` / ``proof_manifest`` / ``write_proof`` all
    consume it UNCHANGED, and the dream's realized value joins the cross-run trail.

    Pure apart from ``build_proof``'s lone clock convention: ``generated_at`` is
    the ONLY wall-clock, and it lives OUTSIDE the tamper seal — so the records,
    ``proof_hash`` and ``value_landed`` are byte-deterministic over the same
    landed moves. Read-only over the report; writes nothing (that is
    ``write_proof``'s job)."""
    from app.engine.proof_of_fix import (
        SCHEMA,
        SCHEMA_VERSION,
        tool_version,
    )
    from datetime import datetime, timezone

    fixes = _dream_proof_records(report)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "Apex Orchestrator", "version": tool_version()},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "objective": report.goal,
        "mode": "dream-land",
        "verify": True,
        "totals": {
            "executable": report.total_moves,
            "applied": len(fixes),
            "rolled_back": 0,
            "blocked": 0,
            "committed": 0,
        },
        "fixes": fixes,
    }


# --- Learn-loop: the dream's OWN landings feed back into outcome memory --------
#
# The dream READS ``IdeaMemory`` land-rates to rank directions, but its OWN
# ``dream --land --apply`` landings never fed back — so it could never learn which
# DREAMED DIRECTIONS (the chain's objectives) actually land on this project. This
# closes that loop: after an apply, the realized outcome of each move is recorded
# into the SAME ``.apex/idea-memory.json`` learn store the ranking already reads,
# keyed by the dreamed direction (the objective) as a ``label``.
#
# HONEST + no-double-count: a LANDED step (one that ran green and HELD — a failed
# gate was rolled back and never appended) is an ``applied`` outcome; a WITHHELD
# move (previewed, not landed) is recorded as not-landed (``blocked``). The
# PER-OPERATOR dimension is deliberately NOT recorded here — the verified-with-
# rollback ``compile_objective`` the chain composes ALREADY credits each landed
# operator to ``by_operator``/``by_sequence`` (its ``_record_composition`` step),
# so re-recording it would inflate the sample count and betray never-fake-green.
# We add ONLY the missing per-label (dreamed-direction) dimension, so the chain's
# operator AND its dreamed direction both reflect the realized outcome.


def _dream_outcome_results(report: DreamChainReport) -> list[dict[str, Any]]:
    """The chain's per-LABEL outcome rows, in ``record_outcomes``' contract.

    One ``applied`` row per LANDED step and one ``blocked`` row per WITHHELD move,
    each keyed by the dreamed direction (``label`` = the chain objective). NO
    ``operator`` key — the compiler already credited landed operators, so we add
    only the per-label dimension (no double-count). Pure projection of the report:
    no clock, no randomness, no I/O — honest over only what actually landed/was
    withheld."""
    rows: list[dict[str, Any]] = []
    for r in report.results:
        for _step in r.steps:
            rows.append({"label": r.objective, "applied": True})
        for _withheld in r.withheld:
            rows.append({"label": r.objective, "blocked": True})
    return rows


def record_dream_outcomes(report: DreamChainReport,
                          project_root: str | Path) -> None:
    """Record the LANDED chain's realized per-direction outcomes into IdeaMemory.

    The one record call the ``dream --land --apply`` path makes AFTER the apply:
    each dreamed direction (chain objective) that LANDED a move is credited as
    ``applied`` and each that WITHHELD a move as not-landed (``blocked``) in the
    SAME ``.apex/idea-memory.json`` store the next-night dream ranking reads — so
    the dream learns which of its OWN dreamed directions actually land here.

    Best-effort and a STRICT no-op unless the chain actually applied AND landed or
    withheld something: a dry run (``applied`` False), an empty chain, or a chain
    that produced no outcome rows writes NOTHING, so the off-by-default tree stays
    byte-identical. Honest: records only ACTUAL landed/withheld outcomes — never a
    fabricated success. A write failure is swallowed (learning never fails a
    successful apply); deterministic and offline."""
    if not report.applied:
        return  # a dry run measured nothing to learn from
    results = _dream_outcome_results(report)
    if not results:
        return  # nothing landed or withheld → nothing to learn (byte-identical)
    from app.engine.idea_memory import IdeaMemory
    try:
        IdeaMemory.learn_from({"results": results}, project_root)
    except OSError:
        pass  # learning is best-effort; never fail a good apply on a memory write


# --- Chain-level learning: per-SCOPE composition + outcome memory -------------
#
# ``record_dream_outcomes`` (above) credits each dreamed DIRECTION (the chain
# objective); this closes the companion gap — the dream's own chain campaigns
# never fed the CHAIN-level learning stores ``chain_compiler`` already writes for
# an explicit, caller-ordered objective sequence (``composition_archive``'s
# MAP-Elites cells + ``idea_memory.by_chain``, see ``chain_compiler._archive_
# chain``/``_record_chain_memory``, chain_compiler.py:292-374). ``dream_develop``
# has no caller-supplied sequence to key by — instead it groups by the SCOPE
# MODULE each landed move actually touched (a dream confluence, or whichever
# file a whole-tree run happened to land on), signature ``dream-chain:<scope>``,
# so the organism learns not just WHICH objectives compose but WHERE (on what
# kind of file) that composition reliably lands.
_DREAM_CHAIN_PREFIX = "dream-chain:"


def _dream_chain_scopes(report: DreamChainReport) -> dict[str, tuple[list[str], int]]:
    """Landed work grouped by SCOPE MODULE: ``{module: (objectives, moves)}``.

    ``objectives`` is the ordered, deduped chain objectives that landed at least
    one move touching ``module`` (chain order preserved — the value-led order
    ``report.objectives`` itself carries); ``moves`` is how many landed steps
    touched it. Uses the SAME module-from-target convention
    ``objective_compiler``'s own ``_move_module``/``_move_module_from_target``
    apply (``target.split(':', 1)[0]``) over every LANDED step — never a
    withheld/blocked one. A scoped confluence campaign's steps all share one
    module by construction (``compile_objective(scope_module=...)`` filters
    candidates to it); a whole-tree run groups by whichever module(s) its moves
    actually touched, so this is honest either way. Pure projection of the
    report: no clock, no randomness, no I/O."""
    objectives: dict[str, list[str]] = {}
    moves: dict[str, int] = {}
    for r in report.results:
        for s in r.steps:
            module = s.target.split(":", 1)[0]
            bucket = objectives.setdefault(module, [])
            if r.objective not in bucket:
                bucket.append(r.objective)
            moves[module] = moves.get(module, 0) + 1
    return {module: (objectives[module], moves[module]) for module in objectives}


def record_dream_chain_memory(report: DreamChainReport,
                              project_root: str | Path) -> None:
    """Archive the landed chain's per-SCOPE recipe into the CHAIN-level learning
    stores — the companion to :func:`record_dream_outcomes`.

    For each scope module :func:`_dream_chain_scopes` names, records ONE
    ``composition_archive.record_campaign`` elite (the landed objectives as the
    recipe, the move count as the fitness gain) and ONE
    ``IdeaMemory.record_chain_outcome`` tally, both under the SAME signature
    ``dream-chain:<module>`` — mirroring ``chain_compiler``'s
    ``_archive_chain``/``_record_chain_memory`` (chain_compiler.py:292-374)
    exactly, keyed by scope module instead of by an explicit caller-ordered
    objective sequence.

    Best-effort and a STRICT no-op unless the chain APPLIED and landed at least
    one move touching some module: a dry run (``applied`` False), an empty
    chain, or a chain that landed/withheld nothing writes NOTHING, so the
    off-by-default tree stays byte-identical. Only genuinely LANDED steps are
    ever grouped (never a withheld/blocked move), so a recorded outcome is
    always the honest ``"applied"`` — never a fabricated success. A write
    failure on either store is swallowed (learning never fails a good apply);
    does NOT touch ``dream_gate_learn``'s tighten-only promote-gate contract."""
    if not report.applied:
        return  # a dry run measured nothing to learn from
    scopes = _dream_chain_scopes(report)
    if not scopes:
        return  # nothing landed anywhere → nothing to learn (byte-identical)
    from app.engine.composition_archive import record_campaign
    from app.engine.idea_memory import IdeaMemory
    try:
        mem = IdeaMemory.load(project_root)
        for module, (objectives, moves) in scopes.items():
            signature = f"{_DREAM_CHAIN_PREFIX}{module}"
            record_campaign(project_root, signature, objectives,
                           float(moves), 0.0, len(objectives))
            mem.record_chain_outcome(signature, "applied")
        mem.save(project_root)
    except OSError:
        pass  # the learn stores are best-effort; never fail a good apply on a write
