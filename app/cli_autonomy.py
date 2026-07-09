"""Autonomy-family commands: maintain, auto, evolve, simulate.

Extracted from the 1900-line `app/cli.py` monolith — the engine's own #1
convergence target (central dependency hub × high churn). Pure mechanical
move: `app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.cli_common import _get_project_root

def _maintain_build_plan(args, target):
    """Scan -> ideate -> plan: the engine + bridge setup shared by every path.

    Returns ``(engine, bridge, plan)`` — the engine is handed back so the apply
    path can record its ``last_profile`` trend baseline."""
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.plugins.registry import PluginRegistry

    plugins = PluginRegistry()
    plugins.load_all()

    engine = IdeaPermutationEngine(
        config={"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
                "breadth": args.breadth},
        project_root=str(target),
        extra_operators=plugins.idea_operators(),
    )
    report = engine.run(objective=args.objective or None)

    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(report, mode=args.mode, top=(args.top or None), project_root=str(target))
    return engine, bridge, plan


def _maintain_scope_recipe(args, plan) -> bool:
    """--recipe: scope the pass to one named intent (typo fails loudly).

    Returns True to continue, False to abort the command with exit code 1."""
    recipe = getattr(args, "recipe", "") or ""
    if not recipe:
        return True
    from app.execution.recipes import filter_plan

    try:
        remaining = filter_plan(plan, recipe)
    except ValueError as exc:
        print(f"⛔ {exc}")
        return False
    print(f"[maintain] scoped to recipe `{recipe}` — "
          f"{remaining} executable step(s) in scope")
    return True


def _maintain_dry_run(args, bridge, plan, target) -> None:
    """Dry-run: preview the diffs without touching anything.

    The console output (markdown or --json) is byte-identical to before. When
    ``--out`` and/or ``--proof`` are ALSO passed, those flags are honored — as a
    clearly-marked PREVIEW, never a real proof: --dry-run applies nothing and
    verifies nothing, so the artifacts are stamped ``mode: dry-run-preview`` with
    ``applied: false`` / ``verified: false`` on every record. They can never be
    mistaken for an applied+verified proof-of-fix. With neither flag set nothing
    extra is written, so a bare dry-run stays exactly as it was."""
    preview = bridge.dry_run_plan(plan, str(target))
    if args.json:
        print(json.dumps(preview, indent=2))
    else:
        print(f"# Apex Maintenance — dry run for `{target}`")
        print(f"\n{preview['applicable']} of {preview['total_executable']} "
              f"executable steps would change files (nothing applied).\n")
        for p in preview["results"]:
            if not p["applicable"]:
                continue
            print(f"## `{p['branch']}` {p['action']} → {p['transform_type']} "
                  f"({', '.join(f for f in p['files'] if f)})")
            print("```diff")
            print(p["diff"].rstrip())
            print("```\n")
    _maintain_write_dry_run_preview(args, preview, target)


def _dry_run_preview_record(p: dict) -> dict:
    """One planned-change record for the dry-run preview artifact, stamped so it
    is unmistakably NOT an applied+verified fix."""
    return {
        "branch": p.get("branch", ""),
        "action": p.get("action", ""),
        "target": p.get("target", ""),
        "applicable": bool(p.get("applicable")),
        "transform_type": p.get("transform_type", ""),
        "files": [f for f in (p.get("files") or []) if f],
        "diff": p.get("diff", ""),
        # The never-mistaken-for-a-proof markers, on EVERY record:
        "applied": False,
        "verified": False,
    }


def _build_dry_run_preview(args, preview: dict, target) -> dict:
    """Assemble the clearly-marked dry-run preview artifact from the diffs the
    dry-run already computed. Deterministic: no clock/random — the content is a
    pure function of the planned changes."""
    return {
        "schema": "apex.maintain.dry-run-preview/v1",
        "mode": "dry-run-preview",
        "applied": False,
        "verified": False,
        "note": ("PREVIEW ONLY — these are the changes `apex maintain` WOULD "
                 "make. Nothing was applied and nothing was verified; this is "
                 "NOT a proof-of-fix. Re-run without --dry-run to apply, verify, "
                 "and produce a real proof."),
        "project_root": str(target),
        "objective": args.objective or "",
        "totals": {
            "executable": preview.get("total_executable", 0),
            "applicable": preview.get("applicable", 0),
            "applied": 0,
            "verified": 0,
        },
        "planned_changes": [
            _dry_run_preview_record(p) for p in preview.get("results", [])
        ],
    }


def _maintain_write_dry_run_preview(args, preview: dict, target) -> None:
    """Honor --out / --proof under --dry-run by emitting a clearly-marked PREVIEW
    artifact (never silently dropped). With neither flag set, write nothing — a
    bare dry-run stays byte-identical to before."""
    out = getattr(args, "out", "") or ""
    proof = getattr(args, "proof", "") or ""
    if not out and not proof:
        return
    artifact = _build_dry_run_preview(args, preview, target)
    text = json.dumps(artifact, indent=2)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        if not args.json:
            print(f"\n[maintain] Dry-run PREVIEW (not applied, not verified) "
                  f"written to {out_path}")
    if proof:
        proof_path = Path(proof)
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(text + "\n", encoding="utf-8")
        if not args.json:
            print(f"\n[maintain] --proof is a PREVIEW under --dry-run: writing "
                  f"planned changes to {proof_path} (not applied, not verified "
                  f"— NOT a proof-of-fix).")


def _maintain_write_out(args, md) -> None:
    """--out: write the Markdown report to the requested path."""
    if not args.out:
        return
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"\n[maintain] Report written to {out_path}")


def _maintain_write_proof(args, summary, target) -> None:
    """Proof-of-fix: the auditable evidence record for everything this pass did."""
    if not summary.get("results"):
        return
    from app.engine.proof_of_fix import build_proof, write_proof

    proof = build_proof(summary, str(target), objective=args.objective or "")
    proof_path = write_proof(proof, str(target), out=getattr(args, "proof", "") or None)
    if not args.json:
        print(f"\n[maintain] Proof-of-fix evidence written to {proof_path}")


def _maintain_avoid_signatures(args, target):
    """OPT-IN: the proof-history failure signatures used to skip predictably-doomed
    fixes BEFORE a wasted apply+rollback. Returns ``None`` when the flag is OFF
    (the default), so nothing is loaded and the apply path stays byte-identical."""
    if not getattr(args, "avoid_learned_failures", False):
        return None
    from app.engine.counterfactual_learning import failure_signatures
    from app.engine.proof_history import load_proof_history

    return failure_signatures(load_proof_history(str(target)))


def _maintain_covered_only(args) -> bool:
    """The effective ``covered_only`` gate ``apex maintain`` feeds ``apply_plan``.

    ``maintain`` is always ATTENDED (a user ran it directly at a terminal — there
    is no daemon/``--evolve`` loop concept here), so this delegates to the SAME
    single-source-of-truth policy the ``auto``/``develop --auto`` sweeps use
    (:func:`resolve_covered_only`) with ``unattended=False`` unconditionally: the
    SAFE default lands only moves a test actually exercises (covered ⇒ verified),
    and a green-but-unreferencing (WEAK) move is previewed/rolled back instead of
    silently landed. ``--allow-weak`` is the explicit, attended opt-out that
    restores the historical land-everything behaviour — mirroring ``develop``'s
    and ``auto``'s attended path exactly (``not allow_weak``)."""
    from app.policies.autonomy_policy import resolve_covered_only

    return resolve_covered_only(
        allow_weak=getattr(args, "allow_weak", False), unattended=False)


def _maintain_apply(args, engine, bridge, plan, target) -> int:
    """Apply the plan (verified, guarded), then learn, record, report, prove."""
    from app.engine.idea_action_bridge import render_maintenance_markdown
    from app.engine.idea_memory import IdeaMemory
    from app.engine.signal_trends import SignalTrends

    avoid = _maintain_avoid_signatures(args, target)
    apply_kwargs = {"avoid_signatures": avoid} if avoid is not None else {}
    # Opt-in (default off, so the default apply order is byte-identical): when
    # set, the executable steps are stably re-ranked low-fix-risk-first before
    # the apply loop, so a --max-apply budget spends on the historically most
    # reliable fixes. Passed only when on, keeping the kwargs identical to today
    # on a default run.
    if getattr(args, "prefer_reliable", False):
        apply_kwargs["prefer_reliable"] = True
    summary = bridge.apply_plan(
        plan, str(target), mode=args.mode,
        verify=not args.no_verify,
        max_apply=(args.max_apply or None) if args.max_apply else None,
        commit=args.commit,
        covered_only=_maintain_covered_only(args),
        **apply_kwargs,
    )
    IdeaMemory.learn_from(summary, str(target))  # learn from this run's outcomes
    SignalTrends(str(target)).record(engine.last_profile)  # trend baseline
    md = render_maintenance_markdown(summary, str(target), objective=args.objective or "")

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(md)
    _maintain_write_out(args, md)
    _maintain_write_proof(args, summary, target)
    return 0


def cmd_maintain(args: argparse.Namespace) -> int:
    """One-shot maintenance: scan -> ideate -> apply -> verify -> commit -> report."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    engine, bridge, plan = _maintain_build_plan(args, target)

    if not _maintain_scope_recipe(args, plan):
        return 1
    if getattr(args, "dry_run", False):
        _maintain_dry_run(args, bridge, plan, target)
        return 0
    return _maintain_apply(args, engine, bridge, plan, target)



def _auto_resolve_mode(args, goal):
    """The user's explicit --mode, or one inferred from a natural-language goal.

    An explicit --mode always wins; otherwise we try the IntentParser on the
    goal (best-effort — a parser failure leaves the mode unset for the policy)."""
    explicit_mode = getattr(args, "mode", None)
    if not explicit_mode and goal:
        try:
            from app.intent.parser import IntentParser

            explicit_mode = IntentParser().parse(goal).mode
        except Exception:
            explicit_mode = None
    return explicit_mode


def _auto_security_counts(target):
    """Best-effort (project, fixture) security-finding counts for the headline.

    A failing scanner must not break auto, and example/fixture code is split out
    with the grade's own predicate so auto and grade tell one consistent story."""
    sec_n = fixture_n = 0
    try:
        from app.agents.skills import SecurityAgent
        from app.engine.health_score import _is_fixture_path

        for finding in SecurityAgent().run(project_root=str(target)).get("findings", []) or []:
            if _is_fixture_path(str(finding.get("file", ""))):
                fixture_n += 1
            else:
                sec_n += 1
    except Exception:
        sec_n = fixture_n = 0
    return sec_n, fixture_n


def _auto_narrative(target, goal, shape, roadmap, sec_n, fixture_n) -> list[str]:
    """The Markdown brief on the state of the project (headline + standouts +
    quick wins + best-effort 'what I've learned'). Pure string assembly."""
    lines = [f"# Apex — autonomous review of `{target}`", ""]
    if goal:
        lines.append(f"_goal: {goal}_\n")
    headline = (
        f"**State:** {shape.total_ideas} development ideas across "
        f"{shape.distinct_subjects} modules · {sec_n} security finding(s)"
    )
    if fixture_n:
        headline += f" (+{fixture_n} in example/fixture code, excluded like the grade does)"
    if shape.heaviest_module:
        headline += f" · heaviest `{shape.heaviest_module}` ({shape.heaviest_loc} LOC)"
    lines += [headline, ""]
    if shape.observations:
        lines.append("**What stands out:**")
        lines += [f"- {o}" for o in shape.observations[:4]]
        lines.append("")
    if roadmap.quick_wins:
        lines.append("**Best next moves (high impact, low effort):**")
        lines += [f"- {i.title}  (ROI {i.roi})" for i in roadmap.quick_wins]
        lines.append("")
    lines += _auto_memory_line(target)
    return lines


def _auto_memory_line(target) -> list[str]:
    """The best-effort 'what I've learned here' line (or nothing).

    A missing/corrupt memory ledger or an unexpected summary shape must never
    break the brief — we simply omit the line rather than fail the command."""
    try:
        from app.engine.idea_memory import IdeaMemory

        mem = IdeaMemory.load(str(target)).summary()
        if mem.get("most_reliable"):
            best = mem["most_reliable"][0]
            return [
                f"_What I've learned here: `{best['key']}` fixes land "
                f"{int(best['success_rate'] * 100)}% of the time "
                f"({best['samples']} samples) — I weight that in._\n"
            ]
    except Exception:
        pass
    return []


# The cheap (AST-only grounding) synthesis opt-ins `apex auto` turns ON
# autonomously: their grounding signals qualify ONLY targets the real lander
# would land, so enabling them surfaces real, landable work without naming a
# flag — honest by construction. The EXPENSIVE opt-ins (they run pytest/mutation
# during grounding) stay behind `--deep` so cost is opt-in and disclosed.
_AUTO_CHEAP_SYNTHESIS = ("modernize", "dedup_total_return",
                         "dedup_guarded_return", "dedup_parameterized",
                         "dedup_parameterized_total_return",
                         "dedup_parameterized_guarded_return")
_AUTO_DEEP_SYNTHESIS = ("cover_gaps", "tdd_implement", "strengthen_tests",
                        "wire_exports", "generate_usage_doc")


def _auto_synthesis_kwargs(args) -> dict:
    """The synthesis opt-in kwargs `apex auto` passes into ``plan_roadmap``.

    The cheap opt-ins are always on (autonomous, AST-only grounding); the
    expensive ones (pytest/mutation grounding) are added ONLY with ``--deep``.
    A pure function of the parsed flags — no clock/random — so the same flags
    always select the same objective set (determinism)."""
    kwargs = {name: True for name in _AUTO_CHEAP_SYNTHESIS}
    if getattr(args, "deep", False):
        kwargs.update({name: True for name in _AUTO_DEEP_SYNTHESIS})
    return kwargs


def _auto_unattended(args) -> bool:
    """True when ``apex auto`` is running UNATTENDED — no human at the diff.

    Two signals: the ``APEX_DAEMON`` env var (the periodic daemon exports it
    before it shells ``apex auto``) OR an active ``--evolve N`` (N>=1) loop. In
    either, Apex applies without a person reviewing each landing, so the SAFE
    verification gate must not be relaxable. Deterministic (a pure read of the
    env + parsed flags — no clock/random); ATTENDED (both absent) ⇒ False, so the
    covered-only decision below is byte-identical to today when attended."""
    import os

    if os.environ.get("APEX_DAEMON"):
        return True
    return int(getattr(args, "evolve", 0) or 0) >= 1


def _auto_covered_only(args) -> bool:
    """The effective ``covered_only`` gate the act path feeds ``apply_plan``.

    Delegates to :func:`resolve_covered_only` (the policy's single source of
    truth — also exposed as ``AutonomyPolicy.resolve_covered_only``): ATTENDED
    honours ``--allow-weak`` (``not allow_weak`` — the historical gate,
    byte-identical); UNATTENDED (daemon / ``--evolve``) forces covered-only and
    REFUSES ``--allow-weak``, so a green suite that merely imports a module can
    never land a Tier-1 behaviour change without a human reviewing it. Calls the
    plain function (not the class) so the gate is decoupled from the
    ``AutonomyPolicy`` symbol the decision path monkeypatches."""
    from app.policies.autonomy_policy import resolve_covered_only

    return resolve_covered_only(
        allow_weak=getattr(args, "allow_weak", False),
        unattended=_auto_unattended(args),
    )


def _auto_dream_boost(target) -> dict:
    """The dream-confluence priority boost `apex auto` threads into
    ``plan_roadmap`` so the value board AMPLIFIES the organism's OWN overnight
    discovery — the file the dream graduated as a confluence leads within its
    phase — instead of ranking on the AST signals alone.

    Reuses ``dream_signal_weight`` (a pure read of the persisted promotion store,
    no LIVE dream, no clock/random, no writes), so it is cheap enough to run every
    auto invocation and deterministic. REFUSAL-SAFE: any failure — or simply no
    persisted confluence — yields an EMPTY map, and an empty ``dream_boost`` leaves
    ``plan_roadmap``'s ranking byte-for-byte identical to the pre-dream AST-only
    order. No dream ⇒ zero behaviour change; the map only ever REORDERS within a
    phase, never changes WHICH steps run, so the suite-gated + auto-rollback
    landings are untouched (never-fake-green is not on this path)."""
    try:
        from app.engine.dream_landing import dream_signal_weight

        return dream_signal_weight(str(target))
    except Exception:
        return {}


# The immune-exposure boost's rank decay: the top-exposed module gets the full
# base boost, each next-most-exposed module a shrinking fraction of it — same
# ballpark as ``DREAM_CONFLUENCE_BOOST`` (1.0) so neither signal dominates the
# other when ``_merge_boosts`` sums them.
_IMMUNE_BOOST_BASE = 1.0
_IMMUNE_BOOST_DECAY = 0.8


def _auto_immune_boost(target) -> dict:
    """The immune-exposure priority boost `apex auto` threads into
    ``plan_roadmap`` so the value board AMPLIFIES the organism's OWN proactive
    blind-spot sense — the modules ``immune_posture`` ranks most mutation-exposed
    (many blindly-callable public functions, no linked test) lead within their
    phase — instead of ranking on the AST signals alone.

    Reuses ``immune_posture`` (a pure, offline read of the project's own module
    ASTs + a test-filename glob — no mutation run, no clock/random, no writes),
    so it is cheap enough to run every auto invocation and deterministic. Only
    the genuinely EXPOSED modules (``has_linked_test`` is False — the strongest,
    cheapest blind-spot signal) earn a boost; a module with a linked test is not
    "exposed" in this sense and gets none, so an all-tested project yields an
    EMPTY map. The boost is RANK-DECAYED — ``_IMMUNE_BOOST_BASE *
    _IMMUNE_BOOST_DECAY ** rank`` — so the single most-exposed module leads every
    other exposed module within its phase, tapering for the rest, never zero and
    never negative.

    REFUSAL-SAFE: any failure — or simply no exposed module — yields an EMPTY
    map, and an empty ``immune_boost`` leaves ``plan_roadmap``'s ranking
    byte-for-byte identical to the pre-immune-boost order. No exposure ⇒ zero
    behaviour change; the map only ever REORDERS within a phase, never changes
    WHICH steps run, so the suite-gated + auto-rollback landings are untouched
    (never-fake-green is not on this path)."""
    try:
        from app.reporting.immune_report import immune_posture

        rows = immune_posture(str(target)).get("top_risk") or []
        exposed = [row["module"] for row in rows
                  if row.get("module") and not row.get("has_linked_test")]
        return {
            module: _IMMUNE_BOOST_BASE * (_IMMUNE_BOOST_DECAY ** rank)
            for rank, module in enumerate(exposed)
        }
    except Exception:
        return {}


def _merge_boosts(*maps) -> dict:
    """Sum per-module priority boosts across any number of boost maps (e.g. the
    dream-confluence boost and the immune-exposure boost) into ONE map a single
    ``plan_roadmap``/``_auto_act`` call can consume.

    A module flagged by MULTIPLE sources earns the SUM of their boosts, so a
    module that is both a dream confluence AND immune-exposed leads every peer
    flagged by only one signal. Deterministic and order-independent: addition is
    commutative, so ``_merge_boosts(a, b) == _merge_boosts(b, a)``. Tolerant of
    ``None``/missing maps (treated as empty) so a caller can pass either boost
    unconditionally. All-empty inputs (or no inputs at all) yield ``{}`` —
    the byte-identical base case."""
    merged: dict = {}
    for boost_map in maps:
        for module, value in (boost_map or {}).items():
            merged[module] = merged.get(module, 0.0) + value
    return merged


def _auto_deep_disclosure(args) -> str:
    """The one-line disclosure shown when ``--deep`` is OFF: deeper (pytest-cost)
    synthesis is available, so the cost stays visible and opt-in (never silent).
    Empty when ``--deep`` is already on (nothing left to disclose)."""
    if getattr(args, "deep", False):
        return ""
    return ("_Deeper synthesis (cover-gaps, tdd-implement, strengthen-tests, "
            "wire-exports, generate-usage-doc) runs pytest during grounding — "
            "add `--deep` to include it._")


# --- Value-ranked PREVIEW (read-only, opt-in-expensive) ---------------------- #
# A buyer sees the high-value work FIRST in the default preview, instead of the
# moat being hidden behind --concrete. STRICTLY read-only AND suite-free: the
# CHEAP main board is built with ``rank_objectives(include_expensive=False)``,
# which EXCLUDES the expensive concrete objectives, so it runs NO pytest. The
# concrete-moat disclosure NAMES the highest-value expensive objective from a
# STATIC frozen-table ranking (``_auto_concrete_unlock``) — it never measures an
# expensive objective's fitness, because doing so would HARVEST the buyer's
# pytest suite on this default path (the round-21 byte-identity violation: every
# expensive gate stays byte-identical, i.e. no new suite execution). No board
# here is fed into ``compile_objective(apply=True)`` — the applied set stays
# byte-identical (the round-21 safety). "Value" answers *what KIND of work* it is
# (the frozen buyer model), kept strictly separate from coverage/"verified"
# (whether a test exercised a landed change), so the annotation never reads as a
# verification claim.


def _module_in_degrees(target) -> dict:
    """Import IN-DEGREE per module (``path -> count of importers``) for the
    blast-radius display lens, via the CHEAP ``DependencyGraphBuilder`` graph walk.

    A pure read of the dependency graph — a structural parse + import resolve, the
    SAME walk ``apex impact``/``blast-radius`` already use. It runs NO pytest, so
    stamping it on the read-only preview keeps that path strictly suite-free (the
    cli_autonomy read-only/suite-free invariant). Best-effort, like the rest of the
    preview: any failure degrades to an empty map (every in-degree then reads 0, so
    the lens is simply inert — never a correctness gate). Deterministic: the graph
    is a pure function of the tree (no clock/random)."""
    try:
        from app.tools.dependency_graph import DependencyGraphBuilder

        graph = DependencyGraphBuilder(str(target)).build()
    except Exception:
        return {}
    return {path: node.in_degree for path, node in graph.items()}


def _objective_top_centrality(objective: str, target, in_degrees: dict) -> int:
    """The blast-radius of an objective's MOST-CENTRAL target: the max import
    in-degree over the modules its moves would touch (0 when it has no resolvable
    central target, or on any error).

    Generates the objective's candidate moves against the current tree — a DRY
    listing (the same ``generate`` thunk ``compile_objective(apply=False)`` lists
    from), which writes nothing and runs NO pytest — and reads each target's module
    in-degree from the pre-built ``in_degrees`` map. A DISPLAY-only signal for the
    read-only value preview; never fed to an apply. Best-effort: a failing
    generator yields 0 (the lens stays inert), never breaking the preview."""
    if not in_degrees:
        return 0
    try:
        from app.engine.objective_compiler import _move_module, _objectives_map

        table = _objectives_map()
        if objective not in table:
            return 0
        generate = table[objective][1]
        modules = {_move_module(mv) for mv in generate(str(target))}
    except Exception:
        return 0
    return max((in_degrees.get(module, 0) for module in modules), default=0)


def _result_top_centrality(result, in_degrees: dict) -> int:
    """The blast-radius of an ALREADY-COMPUTED result's most-central step target:
    the max import in-degree over the modules its previewed steps touch (0 when it
    has no step, or none resolves to a central module).

    Reads ``result.steps[*].target`` (the modules a dry-run preview already listed)
    against the pre-built ``in_degrees`` map — no move regeneration, no writes, no
    pytest. The display-only secondary sort key for ``_develop_auto_value_preview``."""
    if not in_degrees:
        return 0
    from app.engine.objective_compiler import _move_module_from_target

    return max((in_degrees.get(_move_module_from_target(s.target), 0)
                for s in result.steps), default=0)


def _auto_value_board(target, *, concrete: bool) -> list:
    """The default-path objective board, value-RANKED for the read-only preview.

    Reuses the same fitness board ``apex plan``/``apex develop --auto`` select
    from (``rank_objectives``, with the expensive concrete objectives included
    only when ``concrete``), keeps the ones carrying qualifying work right now
    (``pending > 0``), and orders them by buyer value desc, then by the
    BLAST-RADIUS lens (the in-degree of the objective's most-central target, so
    between two equal-buyer-value objectives the one whose top target is more
    central is shown first), with the objective name as the final stable tie-break
    — a total order, no clock/random. The ``value_weight_preview`` lens stamps each
    ranking's display-only ``preview_value``, and ``_objective_top_centrality``
    stamps the display-only ``preview_centrality``, BOTH WITHOUT touching
    ``priority`` (the apply-driving order) — only this read-only DISPLAY is
    reordered (the round-21 safety; ``apex plan``/the applied set are untouched and
    byte-identical, the ``preview_centrality`` field omitted from ``to_dict`` when
    0).

    Best-effort, like ``_auto_memory_line``: a failing board must never break the
    brief — on any error the value preview degrades to empty (it is a read-only
    enrichment, never a correctness gate)."""
    from app.engine.objective_value import objective_value_weight

    try:
        from app.engine.ascend import rank_objectives

        board = [r for r in rank_objectives(str(target), include_expensive=concrete,
                                            value_weight_preview=True)
                 if r.pending > 0]
    except Exception:
        return []
    # Blast-radius DISPLAY lens (cheap graph walk, NO pytest): stamp each ranking's
    # display-only ``preview_centrality`` with its top target's in-degree, then use
    # it as the SECONDARY sort key. Computed once for the whole board.
    in_degrees = _module_in_degrees(target)
    for r in board:
        r.preview_centrality = _objective_top_centrality(r.objective, target, in_degrees)
    board.sort(key=lambda r: (-objective_value_weight(r.objective),
                              -r.preview_centrality, r.objective))
    return board


def _auto_concrete_unlock(target) -> tuple[str, float] | None:
    """The single highest buyer-value EXPENSIVE objective ``--concrete`` would
    unlock, as ``(objective, buyer_value)`` — or None when nothing expensive is
    registered.

    NAMES the concrete moat for the read-only disclosure via a STATIC, zero-cost
    ranking ONLY: ``expensive_names()`` (a registry flag — no fitness) intersected
    with the registered objectives, sorted by ``objective_value_weight`` (a frozen
    -table lookup — no IO) descending with the name as a total-order tie-break. It
    deliberately does NOT measure ``pending``: computing an expensive objective's
    fitness would run the buyer's pytest suite on this default read-only path (the
    round-21 byte-identity violation), and the moat only needs its NAME + static
    buyer-value here. ``target`` is unused (kept for a stable signature across the
    disclosure helpers) — the ranking is identical for every project, so this is
    pure and suite-free. Never fed into ``compile_objective(apply=True)``, so
    expensive work stays opt-in."""
    del target  # static naming only — no per-project fitness, hence no suite run.
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives
    from app.engine.objective_value import objective_value_weight

    registered = set(available_objectives())
    unlockable = sorted(expensive_names() & registered,
                        key=lambda name: (-objective_value_weight(name), name))
    if not unlockable:
        return None
    best = unlockable[0]  # value desc, name tie-break ⇒ a total order.
    return best, objective_value_weight(best)


def _auto_value_lead_line(board: list) -> str:
    """The headline naming the highest buyer-value applicable objective + its
    value, so the default preview LEADS with the moat. Empty when nothing
    applies. "buyer-value" describes the KIND of work, never a verification."""
    if not board:
        return ""
    from app.engine.objective_value import objective_value_weight

    top = board[0]
    return (f"**Highest-value work available:** `{top.objective}` "
            f"(buyer-value {objective_value_weight(top.objective):.2f}, "
            f"{int(top.pending)} pending).")


def _auto_concrete_unlock_line(target, concrete: bool, *, flag: str) -> str:
    """The disclosure NAMING the highest buyer-value concrete/expensive objective
    ``flag`` would unlock, WITHOUT selecting it OR measuring its fitness. Empty
    when concrete is already on or nothing expensive is registered. Mirrors the
    ``_auto_deep_disclosure`` idiom: cost-bearing work stays visible + opt-in,
    framed as POTENTIAL work ("available — add the flag") rather than a "pending
    right now" claim — the name comes from a static buyer-value ranking that runs
    no suite (see ``_auto_concrete_unlock``). ``flag`` is the actual opt-in for the
    calling command (``--concrete`` for ``develop --auto``, ``--deep`` for
    ``auto``), so the message names the right one."""
    if concrete:
        return ""
    unlock = _auto_concrete_unlock(target)
    if unlock is None:
        return ""
    name, value = unlock
    return (f"_Higher-value concrete work is available: `{name}` "
            f"(buyer-value {value:.2f}) — add `{flag}` to include it "
            f"(runs pytest during grounding)._")


def _auto_value_preview_lines(target, concrete: bool, *, flag: str) -> list[str]:
    """The read-only value-ranked preview block for the recommend headline: the
    highest-value applicable objective, then (when ``concrete`` is off) the
    disclosure naming the concrete moat ``flag`` would unlock. Empty list when
    nothing applies, so a clean project's headline is unchanged. Pure string
    assembly over a read-only board — no writes, no suite, no clock/random."""
    board = _auto_value_board(target, concrete=concrete)
    lines: list[str] = []
    lead = _auto_value_lead_line(board)
    if lead:
        lines += [lead, ""]
    unlock = _auto_concrete_unlock_line(target, concrete, flag=flag)
    if unlock:
        lines += [unlock, ""]
    return lines


def _auto_value_ranked_json(target, concrete: bool) -> dict:
    """The ADDITIVE value-preview keys for ``apex auto --json``: the value-ranked
    applicable board and the concrete moves ``--concrete`` would unlock. Purely
    additive — existing keys are untouched, so the payload stays back-compatible.
    Read-only (``rank_objectives``); never drives an apply."""
    from app.engine.objective_value import objective_value_weight

    board = _auto_value_board(target, concrete=concrete)
    value_ranked = [{"objective": r.objective,
                     "value": round(objective_value_weight(r.objective), 3),
                     "pending": r.pending} for r in board]
    unlock = _auto_concrete_unlock(target)
    concrete_available = ([] if unlock is None
                          else [{"objective": unlock[0],
                                 "value": round(unlock[1], 3)}])
    return {"value_ranked": value_ranked, "concrete_available": concrete_available}


def _auto_recommend(args, target, goal, shape, roadmap, sec_n,
                    executable, decision, emit_json) -> int:
    """The recommend path: never touch the tree, report what could be applied.

    Now PREVIEW-FIRST: the default (no-flag) recommend LEADS with the highest
    buyer-value applicable objective and discloses the concrete moat ``--deep``
    would unlock — surfacing the value-ranked work instead of hiding it. The
    value board is strictly read-only (``rank_objectives``); it drives no apply,
    so the recommend path still touches nothing."""
    # ``--deep`` is what unlocks the EXPENSIVE board in the auto path (the
    # --concrete equivalent); the disclosure names that flag.
    concrete = getattr(args, "deep", False)
    if emit_json:
        print(json.dumps({
            "target": str(target), "goal": goal, "ideas": shape.total_ideas,
            "modules": shape.distinct_subjects, "security_findings": sec_n,
            "observations": shape.observations,
            "quick_wins": [{"title": i.title, "roi": i.roi} for i in roadmap.quick_wins],
            "applicable": executable, "applied": False, "decision": decision.to_dict(),
            # ADDITIVE value-preview keys (existing keys untouched).
            **_auto_value_ranked_json(target, concrete),
        }, indent=2))
        return 0
    preview = _auto_value_preview_lines(target, concrete, flag="--deep")
    if preview:
        print("\n".join(preview))
    print(f"_Apex chose not to apply automatically: {decision.reason}._\n")
    cap = (getattr(args, "max_apply", 0) or 8)
    # Disclose the per-run apply cap so the recommend count and what `--apply`
    # would actually land this run tell ONE honest story (the act path applies
    # at most ``cap`` of these per run and you re-run for the rest).
    capped = (f" (this run would apply up to {cap}; re-run to continue)"
              if executable > cap else "")
    print(
        f"I can safely apply **{executable}** of these{capped} (test-verified, "
        "auto-rolled-back). When you're ready:\n\n"
        "  • Apply now:            apex auto --apply\n"
        "  • Preview as diffs:     apex maintain --dry-run\n"
        "  • See the full roadmap: apex ideate --roadmap"
    )
    disclosure = _auto_deep_disclosure(args)
    if disclosure:
        print(f"\n{disclosure}")
    return 0


def _auto_act(args, target, goal, bridge, engine, report, mode,
              commit, decision, emit_json, dream_boost=None) -> int:
    """The act path: roadmap-ordered, verified, capped guarded apply + report.

    SAFE-by-default SWEEP: lands ONLY moves a test actually exercises (covered ⇒
    verified). A green-but-unreferencing move is PREVIEWED but withheld unless
    ``--allow-weak`` restores today's behaviour (byte-identical apply).

    ``dream_boost`` is a generic module -> priority-boost map (the caller may
    merge multiple signals into it, e.g. ``_merge_boosts(dream_boost,
    immune_boost)``); it amplifies dream-graduated confluences AND/OR
    immune-exposed modules in the roadmap ranking (leads within a phase). An
    empty/None map leaves the plan byte-identical, so a project with neither
    signal applies exactly what it would have before either boost existed. The
    boost only REORDERS — the covered-only, suite-gated, auto-rollback landing
    is untouched (never-fake-green is off this path)."""
    from app.engine.idea_action_bridge import render_maintenance_markdown

    plan = bridge.plan_roadmap(report, mode=mode, project_root=str(target), draft=True,
                               dream_boost=dream_boost,
                               **_auto_synthesis_kwargs(args))
    available = plan.stats.get("executable_steps", 0)
    cap = (getattr(args, "max_apply", 0) or 8)
    # SAFE gate: covered-only unless attended + --allow-weak. Forced covered-only
    # (--allow-weak refused) when UNATTENDED (daemon / --evolve). Attended default
    # is byte-identical to the prior ``not getattr(args, "allow_weak", False)``.
    covered_only = _auto_covered_only(args)
    summary = bridge.apply_plan(
        plan, str(target), mode=mode,
        verify=not getattr(args, "no_verify", False),
        max_apply=cap,
        commit=commit,
        covered_only=covered_only,
    )
    from app.engine.idea_memory import IdeaMemory

    IdeaMemory.learn_from(summary, str(target))  # the engine gets wiser each run
    from app.engine.signal_trends import SignalTrends

    SignalTrends(str(target)).record(engine.last_profile)  # trend baseline
    md = render_maintenance_markdown(summary, str(target), objective=goal)
    proof_path = None
    if summary.get("results"):
        from app.engine.proof_of_fix import build_proof, write_proof

        proof_path = write_proof(build_proof(summary, str(target), objective=goal), str(target))
    if emit_json:
        print(json.dumps({**summary, "decision": decision.to_dict()}, indent=2))
    else:
        print(f"_Apex is applying autonomously: {decision.reason}._\n")
        print(md)
        # Disclose the per-run apply cap when there is more applicable work than
        # this run will land (honest about both the cap and the remainder).
        if available > cap:
            print(f"\n_Applying {cap} of {available} this run; re-run for the rest._")
        n_withheld = summary.get("withheld_uncovered", 0)
        if n_withheld:
            print(f"\n_Withheld {n_withheld} uncovered move(s) (suite green but no "
                  "test exercises them — a green suite can't vouch for the change). "
                  "They were PREVIEWED, not landed. Re-run with `--allow-weak` to "
                  "land them too._")
        if proof_path is not None:
            print(f"\n_Proof-of-fix evidence written to `{proof_path}`._")
        if not commit:
            print("\n_Applied to your working tree, not committed — "
                  "review with `git diff`, undo with `git checkout -- .`_")
        disclosure = _auto_deep_disclosure(args)
        if disclosure:
            print(f"\n{disclosure}")
    if getattr(args, "out", ""):
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n[auto] Report written to {out_path}")
    return 0


_AUTO_EVOLVE_MAX_CYCLES = 10


def _auto_evolve_delegate(args: argparse.Namespace) -> int | None:
    """`apex auto --evolve N`: run the self-improvement LOOP for N cycles by
    DELEGATING to the exact same ``EvolutionLoop`` ``apex evolve`` drives — a
    one-command convenience, NOT a second implementation of the loop.

    ``N <= 0`` (the default) returns None → the caller keeps today's one-pass
    ``apex auto`` behaviour, byte-for-byte. ``N >= 1`` clamps N to
    ``[1, _AUTO_EVOLVE_MAX_CYCLES]`` (so a fat-fingered ``--evolve 999`` can't
    launch an unbounded overnight run), stamps it onto ``args.max_cycles``, and
    hands off to :func:`cmd_evolve` — which builds ``EvolutionLoop(max_cycles=N)``
    and calls ``.run()``. The per-cycle verify + auto-rollback and the
    before/after proof are inherited unchanged (never-fake-green is EvolutionLoop's
    own, untouched here); returns its exit code so the loop's report is the output.
    """
    n = int(getattr(args, "evolve", 0) or 0)
    if n <= 0:
        return None
    args.max_cycles = max(1, min(_AUTO_EVOLVE_MAX_CYCLES, n))
    return cmd_evolve(args)


def cmd_auto(args: argparse.Namespace) -> int:
    """One autonomous command — no flags to memorize.

    Assesses the project, decides what matters most (via the roadmap), and either
    recommends the best next moves (default, no changes) or, with ``--apply``,
    safely applies the test-verified, auto-rolled-back fixes in roadmap order.
    An optional natural-language goal focuses the ideas and can hint the mode.

    ``--evolve N`` (N>=1) short-circuits into the multi-cycle self-improvement
    LOOP by delegating to the same ``EvolutionLoop`` as ``apex evolve`` — a
    one-command convenience; N<=0 (default) is the single-pass behaviour below,
    unchanged.
    """
    # --evolve N: delegate to the shared EvolutionLoop (no single-pass work).
    evolved = _auto_evolve_delegate(args)
    if evolved is not None:
        return evolved

    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.engine.idea_roadmap import RoadmapSynthesizer
    from app.engine.idea_tree_shape import analyze_tree_shape
    from app.plugins.registry import PluginRegistry

    target = Path(args.target).resolve() if args.target else _get_project_root()
    goal = (getattr(args, "goal", "") or "").strip()
    explicit_apply = getattr(args, "apply", False)
    explicit_recommend = getattr(args, "recommend", False)
    explicit_mode = _auto_resolve_mode(args, goal)

    plugins = PluginRegistry()
    plugins.load_all()
    # --deep already means "also weigh the EXPENSIVE synthesis objectives
    # (cover-gaps, tdd-implement, strengthen-tests, wire-exports,
    # generate-usage-doc)" for the action plan (``_auto_synthesis_kwargs``
    # below); extend the SAME flag to the idea TREE so a landable opportunity
    # like cover-gaps (a real characterization test for an untested module),
    # otherwise invisible on the idea-tree side, surfaces as a top idea root.
    # HONEST NOTE: this widens BOTH the recommend narrative AND what
    # `apex auto --apply --deep` actually LANDS — those landable roots become
    # roadmap steps ``apply_plan`` processes, so `--deep` can land a cover-gaps
    # move on a module a plain `--apply` would not reach. This is by design
    # (``--deep`` is an explicit opt-in to go deeper); every such landed move
    # still goes through the covered-only, suite-gated, auto-rollback apply
    # path, so never-fake-green is preserved. Off by default, so a plain
    # `apex auto` stays byte-identical.
    deep = getattr(args, "deep", False)
    engine = IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4,
                "landability_aware": deep, "landability_deep": deep},
        project_root=str(target),
        extra_operators=plugins.idea_operators(),
    )
    report = engine.run(objective=goal or None)
    roadmap = RoadmapSynthesizer().build(report)
    shape = analyze_tree_shape(report)
    sec_n, fixture_n = _auto_security_counts(target)

    emit_json = getattr(args, "json", False)
    if not emit_json:
        print("\n".join(_auto_narrative(target, goal, shape, roadmap, sec_n, fixture_n)))

    bridge = IdeaActionBridge()
    commit = getattr(args, "commit", False)

    # The priority boost: `apex auto` AMPLIFIES the organism's OWN signals — both
    # the dream-confluence boost (the modules the dream graduated as confluences
    # lead within their phase) AND the immune-exposure boost (the modules
    # ``immune_posture`` ranks most mutation-exposed — many blindly-callable
    # public functions, no linked test — lead within their phase too) — when
    # ranking the value board, instead of ranking on the AST signals alone.
    # REFUSAL-SAFE — an empty merged map (no persisted dream AND no immune
    # exposure) leaves the ranking byte-for-byte identical to the AST-only
    # order, so a project with neither signal is unchanged. Computed ONCE and
    # shared by the scout and the act path so the recommend count and what
    # `--apply` lands tell one honest story.
    dream_boost = _auto_dream_boost(target)
    immune_boost = _auto_immune_boost(target)
    priority_boost = _merge_boosts(dream_boost, immune_boost)

    # How many safe, executable fixes are available, and is the tree clean? The
    # scout enables the SAME synthesis opt-ins the act path will (cheap always,
    # expensive under --deep), so the recommend count and what `--apply` would
    # land tell one honest story.
    scout = bridge.plan_roadmap(report, mode="report", project_root=str(target),
                                dream_boost=priority_boost,
                                **_auto_synthesis_kwargs(args))
    executable = scout.stats.get("executable_steps", 0)
    tree_clean = _working_tree_clean(target)

    # Apex decides — autonomously — whether to act or recommend. PREVIEW-BY-
    # DEFAULT: ``require_explicit_apply`` makes a bare ``apex auto`` recommend
    # (never edit) unless ``--apply`` is passed — the footgun fix so the
    # one-command entry point can't silently edit a clean tree (it once edited
    # Apex's own repo). ``--apply`` still applies, byte-for-byte as before.
    from app.policies.autonomy_policy import AutonomyPolicy

    decision = AutonomyPolicy().decide(
        executable_steps=executable,
        working_tree_clean=tree_clean,
        explicit_apply=explicit_apply,
        explicit_recommend=explicit_recommend,
        commit=commit,
        require_explicit_apply=True,
    )
    mode = explicit_mode or decision.mode
    if decision.act and mode == "report":
        mode = "supervised"  # acting requires a patch-capable mode

    if not decision.act:
        return _auto_recommend(args, target, goal, shape, roadmap, sec_n,
                               executable, decision, emit_json)
    return _auto_act(args, target, goal, bridge, engine, report, mode,
                     commit, decision, emit_json, priority_boost)



def _working_tree_clean(target: Path) -> bool:
    """True if ``target`` is a git repo with no uncommitted changes.

    A non-repo counts as "not clean" so Apex won't auto-edit a tree it can't
    help the user review/undo via git.
    """
    import subprocess

    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(target), capture_output=True, text=True, timeout=10,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(target), capture_output=True, text=True, timeout=10,
        )
        return status.returncode == 0 and not status.stdout.strip()
    except Exception:
        return False



def cmd_simulate(args: argparse.Namespace) -> int:
    """Preview what autonomous improvement would do — on a disposable copy."""
    from app.engine.simulation import render_simulation_markdown, simulate_evolution

    target = Path(args.target).resolve() if args.target else _get_project_root()
    result = simulate_evolution(
        str(target),
        max_cycles=getattr(args, "max_cycles", 3),
        max_apply_per_cycle=getattr(args, "max_apply", 5) or 5,
        objective=getattr(args, "objective", "") or None,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_simulation_markdown(result, str(target)))
    return 0



def cmd_evolve(args: argparse.Namespace) -> int:
    """Self-improvement loop: apply guarded fixes cycle by cycle to a fixpoint,
    then prove the project's health improved (before/after + roadmap diff)."""
    from app.engine.evolution import (
        EvolutionLoop,
        load_history,
        record_run,
        render_evolution_markdown,
        render_trajectory_markdown,
    )
    from app.engine.idea_action_bridge import IdeaActionBridge

    target = Path(args.target).resolve() if args.target else _get_project_root()

    # --history: show the recorded self-improvement trajectory, run nothing.
    if getattr(args, "history", False):
        history = load_history(str(target))
        if args.json:
            print(json.dumps(history, indent=2))
        else:
            print(render_trajectory_markdown(history))
        return 0

    # Dry run: preview cycle-1 diffs without applying or looping.
    if getattr(args, "dry_run", False):
        from app.engine.idea_permutation import IdeaPermutationEngine

        report = IdeaPermutationEngine(
            config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
            project_root=str(target),
        ).run()
        plan = IdeaActionBridge().plan_roadmap(report, mode="report", project_root=str(target))
        preview = IdeaActionBridge().dry_run_plan(plan, str(target))
        print(f"# Apex evolve — dry run for `{target}`\n")
        print(f"{preview['applicable']} of {preview['total_executable']} fixes would apply "
              "in the first cycle (nothing changed).")
        return 0

    mode = getattr(args, "mode", None) or ("autonomous" if getattr(args, "commit", False) else "supervised")
    # The self-improvement loop is inherently UNATTENDED — no human reviews the
    # diff between cycles — so it FORCES covered-only and REFUSES ``--allow-weak``
    # exactly like the daemon path. Reuse the SAME single-source-of-truth policy
    # (``resolve_covered_only`` — also on ``AutonomyPolicy``) the act path calls,
    # with ``unattended=True`` so a green suite that merely imports a module can
    # never land a Tier-1 behaviour change here without a human in the loop.
    from app.policies.autonomy_policy import resolve_covered_only

    covered_only = resolve_covered_only(
        allow_weak=getattr(args, "allow_weak", False), unattended=True)
    loop = EvolutionLoop(
        project_root=str(target),
        mode=mode,
        max_cycles=getattr(args, "max_cycles", 3),
        max_apply_per_cycle=getattr(args, "max_apply", 5) or 5,
        verify=not getattr(args, "no_verify", False),
        commit=getattr(args, "commit", False),
        objective=getattr(args, "objective", "") or None,
        covered_only=covered_only,
    )
    result = loop.run()
    record_run(result, str(target))  # log to the trajectory (.apex/evolution-history.jsonl)
    md = render_evolution_markdown(result, str(target))
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(md)
    if getattr(args, "out", ""):
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n[evolve] Report written to {out_path}")
    return 0


_APPLIED_TREE_NOTE = ("_Applied to your working tree, not committed — "
                      "review with `git diff`._")


def _develop_playbook(args, target) -> int:
    """`apex develop --playbook`: show the learned composition playbook, run nothing."""
    from app.engine.composition_archive import (
        CompositionArchive, render_playbook_markdown,
    )

    archive = CompositionArchive.load(str(target))
    if args.json:
        print(json.dumps(archive.to_dict(), indent=2))
    else:
        print(render_playbook_markdown(archive))
    return 0


def _develop_history(args, target) -> int:
    """`apex develop --history`: show the development trajectory, run nothing."""
    from app.engine.dev_history import DevHistory, render_history_markdown

    history = DevHistory.load(str(target))
    if args.json:
        print(json.dumps(history.to_dict(), indent=2))
    else:
        print(render_history_markdown(history))
    return 0


def _min_move_value(args) -> float:
    """The buyer's value FLOOR for ``compile_objective`` from ``--min-value``.

    The CLI flag defaults to ``None`` (unset); ``compile_objective`` expects a
    float whose byte-identical default is ``0.0``. Map an unset flag to ``0.0``
    so omitting ``--min-value`` reorders/refuses nothing — every existing
    campaign stays unchanged."""
    floor = getattr(args, "min_value", None)
    return 0.0 if floor is None else float(floor)


def _develop_goal(args, target, goal, max_steps, verify, apply) -> int:
    """`apex develop --goal`: pursue a high-level goal that fractally decomposes."""
    from app.engine.fractal_develop import compile_goal, render_goal_markdown

    gr = compile_goal(str(target), goal, max_steps=max_steps, verify=verify, apply=apply,
                      value_led=getattr(args, "value_led", False))
    if args.json:
        print(json.dumps(gr.to_dict(), indent=2))
    else:
        print(render_goal_markdown(gr))
        if apply and gr.total_moves:
            print(_APPLIED_TREE_NOTE)
    return 0 if gr.objectives else 1


def _develop_all(args, target, grade_before, max_steps, verify, apply) -> int:
    """`apex develop --all`: sweep every objective in order."""
    from app.engine.objective_compiler import compile_all, render_all_markdown

    results = compile_all(str(target), max_steps=max_steps, verify=verify, apply=apply)
    changed = apply and any(r.steps for r in results)
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(render_all_markdown(results))
        if changed:
            print(_APPLIED_TREE_NOTE)
    _print_grade_proof(str(target), grade_before, changed,
                       objective="all", moves=sum(len(r.steps) for r in results))
    return 0


def _auto_selected_objectives(target, concrete: bool,
                              value_lead: bool = False,
                              scope_module: str | None = None) -> list[str]:
    """The objectives the autonomous develop sweep will pursue — chosen by each
    objective's OWN fitness/grounding, not by name. Reuses the same fitness-ranked
    board ``apex plan`` / ``apex ascend`` use (``rank_objectives``), keeping ONLY
    the ones that carry qualifying targets right now (``pending > 0``). Off the
    fast default board are the EXPENSIVE concrete objectives (implement-stub,
    wire-exports, strengthen-tests, …); ``concrete=True`` opts them in, exactly as
    ``--concrete`` does for plan/ascend. ``value_lead=True`` (opt-in) re-orders the
    SAME board by buyer value (a cheap Tier-1 fix leads a high-pending tidy) WITHOUT
    unlocking the expensive objectives — membership stays gated solely by
    ``concrete``.

    ``scope_module`` (opt-in, default None) is the REACH lever: when the user
    pointed the sweep at ONE specific, already-resolved module — a narrowly-named
    target that has already cleared the safety bar — the expensive concrete
    objectives (implement-stub, cover-gaps, wire-exports, the java-*/js-* families)
    are unlocked AUTOMATICALLY (``include_expensive`` OR'd on), because running one
    of them confined to a single named module is bounded + intended (the user
    explicitly asked). This is what lets ``apex assist "implement the missing
    functions in auth.py"`` reach ``implement-stub`` instead of honestly no-op'ing.
    It NEVER widens a broad sweep: with ``scope_module=None`` (the default, a whole-
    project sweep) membership stays gated solely by ``concrete`` — byte-identical.
    ``scope_module`` here only gates MEMBERSHIP; the compiler does the actual
    module-confinement (``compile_objective(scope_module=...)``), so no unrelated
    module is touched. Deterministic: the board's order is a fixed function of
    measured fitness — no clock/random."""
    from app.engine.ascend import rank_objectives

    # A resolved, narrowly-named scope is an explicit, bounded invitation to run
    # the expensive concrete objectives on JUST that module — so it unlocks them
    # even without --concrete. No scope ⇒ membership stays gated solely by concrete.
    include_expensive = concrete or scope_module is not None
    return [r.objective for r in rank_objectives(str(target),
                                                 include_expensive=include_expensive,
                                                 value_lead=value_lead)
            if r.pending > 0]


def _select_for_sweep(target, concrete: bool, value_lead: bool,
                      scope_module: str | None = None) -> list[str]:
    """The autonomous sweep's objective set. ``value_lead`` / ``scope_module`` are
    opt-in: when BOTH are OFF (the default) the selector is called with the SAME
    two-arg signature as before, so the byte-identical default path — and every
    existing 2-arg test stub of ``_auto_selected_objectives`` — is preserved. A
    resolved ``scope_module`` (the user named ONE module) is threaded so the
    selector auto-unlocks the expensive concrete objectives ON THAT MODULE ONLY
    (see ``_auto_selected_objectives``); the extra args only ever appear once the
    user opted in."""
    if scope_module is not None:
        return _auto_selected_objectives(target, concrete, value_lead, scope_module)
    if value_lead:
        return _auto_selected_objectives(target, concrete, value_lead)
    return _auto_selected_objectives(target, concrete)


def _withheld_summary(results: list) -> tuple[int, str]:
    """``(count, message)`` for the moves the covered-only sweep PREVIEWED but did
    NOT land — a green-but-unreferencing change a green suite can't vouch for.

    The message is empty when nothing was withheld (so a fully-covered sweep reads
    exactly as before). When something was withheld it states the count and that
    ``--allow-weak`` lands them too — clear, honest, and actionable. Pure string
    assembly over ``CompileResult.withheld``; no clock/random."""
    withheld = [d for r in results for d in getattr(r, "withheld", [])]
    n = len(withheld)
    if not n:
        return 0, ""
    msg = (f"\n_Withheld {n} uncovered move(s) (suite green but no test exercises "
           "them — a green suite can't vouch for the change). They were PREVIEWED, "
           "not landed. Re-run with `--allow-weak` to land them too._")
    return n, msg


def _auto_scope_module(args, target) -> str | None:
    """Resolve the sweep's named scope HINT (``args.scope``) to a real module path,
    or None for a whole-project sweep.

    Read via ``getattr`` (default ``""``), so a develop namespace WITHOUT a scope
    attribute — every existing ``apex develop --auto`` invocation — yields None and
    the sweep stays byte-identical. When a scope is present it is resolved by the
    SAME best-effort matcher ``apex assist`` uses
    (:func:`app.agent.assist._resolve_scope_module`: exact relative path → unique
    basename → unique stem, else None for an ambiguous/unknown hint), so a
    narrowly-named target unlocks the expensive concrete objectives on JUST that
    module while a vague/ambiguous hint safely falls back to the whole-project
    sweep. Read-only (no writes, no suite)."""
    scope = getattr(args, "scope", "") or ""
    if not scope:
        return None
    from app.agent.assist import _resolve_scope_module

    return _resolve_scope_module(str(target), scope)


def _develop_auto(args, target, grade_before, max_steps, verify, apply) -> int:
    """`apex develop --auto`: AUTONOMOUSLY land everything-applicable — no
    objective-naming. Selects the objectives that carry qualifying targets via the
    fitness-ranked board (``_auto_selected_objectives``), then runs each through
    the EXISTING ``compile_objective`` loop (suite-gated, auto-rollback) and emits
    the same combined report as ``--all``.

    SAFE-by-default sweep: ``--apply`` lands ONLY moves a test actually exercises
    (covered ⇒ verified). A move whose green suite NO test references is PREVIEWED
    but withheld (the broad sweep must never silently land a change a green suite
    can't vouch for — the buyer-proof regression). ``--allow-weak`` opts back into
    today's behaviour (lands weak moves too), byte-identical to before.

    Honest about cost: the EXPENSIVE concrete objectives (implement-stub,
    wire-exports, strengthen-tests, … — they run pytest) are OFF by default and
    only swept with ``--concrete``; either way the chosen objective set is
    surfaced (the report's per-objective breakdown) so the run is never silent
    about what it did. Default is a dry run; ``--apply`` writes."""
    from app.engine.objective_compiler import compile_objective, render_all_markdown

    concrete = getattr(args, "concrete", False)
    # COVERED-ONLY is the sweep default; ``--allow-weak`` restores today's apply.
    covered_only = apply and not getattr(args, "allow_weak", False)
    # REACH: when the sweep was pointed at ONE named module (an already-resolved,
    # narrowly-scoped target), thread it so the selector auto-unlocks the expensive
    # concrete objectives ON THAT MODULE ONLY and the compiler confines every
    # campaign to it. No named scope ⇒ None ⇒ the whole-project sweep is byte-
    # identical (membership still gated solely by ``concrete``).
    scope_module = _auto_scope_module(args, target)
    selected = _select_for_sweep(target, concrete,
                                 getattr(args, "value_lead", False), scope_module)
    results = []
    for objective in selected:
        result = compile_objective(str(target), objective=objective,
                                   max_steps=max_steps, verify=verify, apply=apply,
                                   scope_verify=getattr(args, "fast", False),
                                   min_move_value=_min_move_value(args),
                                   scope_module=scope_module,
                                   covered_only=covered_only,
                                   risk_aware=getattr(args, "risk_aware", False),
                                   manifesto_aware=getattr(args, "manifesto_aware", False))
        if (result.steps or result.fitness_start > 0
                or result.verification_unavailable):
            # Retain a verification-unavailable decline so `apex develop --auto`
            # surfaces the loud "pytest can't verify here" message instead of a
            # false "Nothing to do" (parity with compile_all / compile_goal).
            results.append(result)
    changed = apply and any(r.steps for r in results)
    _n_withheld, withheld_msg = _withheld_summary(results)
    if args.json:
        # BYTE-IDENTICAL apply/dry-run JSON contract: the step contract is
        # untouched; the value-ranked PREVIEW is a CLI-string-layer concern only.
        # ``withheld`` is purely additive (present only when the gate withheld).
        print(json.dumps([r.to_dict() for r in results], indent=2))
    elif apply:
        print(render_all_markdown(results))
        if changed:
            print(_APPLIED_TREE_NOTE)
        if withheld_msg:
            print(withheld_msg)
    else:
        # DEFAULT (dry-run, human-readable): value-rank the DISPLAY so the
        # highest buyer-value work leads, and disclose the concrete moat
        # ``--concrete`` would unlock — read-only string assembly over the SAME
        # results (no re-selection, the step contract is unchanged).
        print(_develop_auto_value_preview(target, results, concrete))
    _print_grade_proof(str(target), grade_before, changed,
                       objective="auto", moves=sum(len(r.steps) for r in results))
    return 0


def _develop_auto_value_preview(target, results: list, concrete: bool) -> str:
    """The DEFAULT-path dry-run preview for ``develop --auto``, value-RANKED:
    render the per-objective breakdowns ordered by buyer value desc, then by the
    BLAST-RADIUS lens (the in-degree of the result's most-central previewed-step
    target, so between two equal-buyer-value objectives the one whose top target is
    more central leads), with the objective name as the final stable tie-break,
    each headed by its buyer-value, then disclose the highest-value concrete
    objective ``--concrete`` would unlock. Pure string assembly over the already
    -computed ``results`` — it reorders/annotates the DISPLAY only, never the
    applied set (which a dry run does not produce anyway), and "buyer-value" names
    the KIND of work, never a verification claim."""
    from app.engine.objective_compiler import (
        render_all_markdown, render_compile_markdown,
    )
    from app.engine.objective_value import objective_value_weight

    unlock = _auto_concrete_unlock_line(target, concrete, flag="--concrete")
    if not results:
        # The cheap board is a fixpoint — keep the canonical empty-sweep message,
        # but STILL surface the concrete moat ``--concrete`` would unlock (the
        # whole point: the high buyer-value work isn't hidden) when it applies.
        body = render_all_markdown(results)
        return f"{body}\n{unlock}\n" if unlock else body
    # Blast-radius DISPLAY lens (cheap graph walk, NO pytest): the SECONDARY sort
    # key is the in-degree of each result's most-central previewed-step target.
    in_degrees = _module_in_degrees(target)
    ordered = sorted(results,
                     key=lambda r: (-objective_value_weight(r.objective),
                                    -_result_top_centrality(r, in_degrees),
                                    r.objective))
    total_moves = sum(len(r.steps) for r in ordered)
    total_gain = sum(r.fitness_start - r.fitness_end for r in ordered)
    lines = [f"# Develop — all objectives ({len(ordered)} with work), value-ranked", "",
             f"**{total_moves} verified move(s)**, total fitness gain "
             f"**{total_gain:g}** across the sweep — highest buyer-value first.", ""]
    for r in ordered:
        lines.append(f"_buyer-value {objective_value_weight(r.objective):.2f}_")
        lines.append(render_compile_markdown(r))
    if unlock:
        lines += [unlock, ""]
    return "\n".join(lines)


def _develop_session(args, target, max_steps, verify, apply) -> int:
    """`apex develop session`: run the FIXED concrete-value-first objective
    sequence on the target in one motion and emit ONE combined verified diff.

    This is the buyer artifact: it OPTS IN the two ``expensive`` concrete
    objectives (``implement-stub``, ``wire-exports``) that the automatic sweeps
    exclude, lands them alongside hint-inference, dataclassify, and the idiom
    modernizers, and prints the combined report — per-objective breakdown, the
    verified/no-suite tier of each landed move, the full-suite backstop verdict,
    and the unified diff. Default is report-only; ``--apply`` writes."""
    from app.engine.develop_session import (
        render_session_markdown, run_develop_session,
    )

    report = run_develop_session(
        str(target), max_steps=max_steps, verify=verify, apply=apply,
        scope_verify=getattr(args, "fast", False))
    _develop_session_write_proof(args, report, target)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_session_markdown(report))
        if report.applied and report.total_moves:
            print(_APPLIED_TREE_NOTE)
    return 0


def _develop_session_write_proof(args, report, target) -> None:
    """Proof-of-fix: persist an `--apply` session's landed-and-held moves onto the
    SHARED ``.apex/proof-of-fix.json`` trail value-landed / owner-report consume.

    The develop-side analog of ``_dream_land_write_proof``: gated on ``--apply``
    AND a real held landing (``report.total_moves``), so a dry run (no writes, no
    moves) and a fully-rolled-back session (the regression backstop emptied
    ``obj.moves`` -> ``total_moves == 0``) each write NOTHING — never-fake-green.
    ``write_proof`` archives the prior pointer (content-addressed), so this merges
    with any maintain/dream history rather than clobbering it."""
    if not (getattr(args, "apply", False) and report.total_moves):
        return
    from app.engine.develop_session import build_session_proof
    from app.engine.proof_of_fix import write_proof

    proof = build_session_proof(report, str(target))
    proof_path = write_proof(proof, str(target))
    if not args.json:
        print(f"\n[develop] Proof-of-fix evidence written to {proof_path}")


def _develop_from_dream(args, target, objective, max_steps, verify, apply) -> int:
    """`apex develop --from-dream`: scope the campaign to dream-flagged confluences."""
    from app.engine.dream_landing import (
        compile_from_dream, dream_confluence_modules,
    )
    from app.engine.objective_compiler import render_from_dream_markdown

    deep = getattr(args, "deep", False)
    modules = dream_confluence_modules(str(target))
    results = compile_from_dream(str(target), objective=objective,
                                 max_steps=max_steps, verify=verify, apply=apply,
                                 sweep=deep)
    if args.json:
        print(json.dumps({"modules": modules,
                          "campaigns": [r.to_dict() for r in results]}, indent=2))
    else:
        print(render_from_dream_markdown(results, modules, sweep=deep))
        if not deep and modules:
            print("\n_`--deep` lands the ranked board of fitness-applicable "
                  "objectives on each confluence (runs more campaigns) — "
                  "default scopes to the single objective only._")
        if apply and any(r.steps for r in results):
            print(_APPLIED_TREE_NOTE)
    return 0


def _develop_multifile(args, target, max_steps, verify, apply) -> int:
    """`apex develop --multifile`: land the COORDINATED multi-file change —
    implement a tested stub in a module AND wire its export in the owning
    package ``__init__.py`` — as ONE verified-or-rolled-back unit.

    Surfaces the shipped composition primitive: ``multifile_moves(target)`` offers
    one composed implement-and-wire :class:`Move` per (stub-module, owning-package)
    pair, and ``run_moves`` drives them through the EXISTING compile loop — the same
    suite-gated, auto-rolled-back ``apply_rename`` engine every objective uses (here
    impact-scoped, since both composed halves are red-baseline objectives). Each move's
    composed plan still flows through the one legal gated-writer call site; a pair whose
    composition refuses (no wireable export, file overlap, unsynthesizable stub) simply
    no-ops. Default is a dry run (lists what would land, no writes); ``--apply`` writes.
    Reuses the develop report (``render_compile_markdown``) so the unified per-move
    breakdown reads exactly like a single-objective campaign."""
    from app.engine.objective_compiler import render_compile_markdown, run_moves
    from app.execution.multifile_landing import multifile_moves

    moves = multifile_moves(str(target))
    result = run_moves(str(target), moves, label="multifile-landing",
                       max_steps=max_steps, verify=verify, apply=apply,
                       scope_verify=True)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_compile_markdown(result))
        if result.applied and result.steps:
            print(_APPLIED_TREE_NOTE)
    return 0


def _parse_chain(raw: str) -> tuple[list[str], str | None]:
    """Split a ``--chain`` value into an ordered objective list, refusing honestly.

    ``raw`` is the comma-separated sequence the user typed (``"implement-stub,
    cover-gaps"``); whitespace around each name is trimmed and empty segments are
    dropped, so ``"a, b,"`` yields ``["a", "b"]``. Returns ``(objectives, error)``:
    ``error`` is ``None`` on success, otherwise a helpful usage message (an empty
    chain, or a name that is NOT a registered objective — the malformed-chain
    refusal, so no partial campaign ever runs on a typo). Pure/deterministic: a
    parse + a frozen-registry membership check, no clock/IO."""
    from app.engine.objective_compiler import available_objectives

    objectives = [seg.strip() for seg in raw.split(",") if seg.strip()]
    if not objectives:
        return [], ("empty --chain — pass an ordered, comma-separated objective "
                    "sequence (e.g. --chain implement-stub,cover-gaps,"
                    "strengthen-tests)")
    known = set(available_objectives())
    unknown = [o for o in objectives if o not in known]
    if unknown:
        hint = ", ".join(sorted(known)[:8])
        return objectives, (
            f"unknown objective(s) in --chain: {', '.join(unknown)} — every step "
            f"must be a registered objective (e.g. {hint}, …). Run `apex develop "
            "--all` to see what the compiler can pursue.")
    return objectives, None


def _develop_chain(args, target, max_steps, verify, apply) -> int:
    """`apex develop --chain a,b,c`: run an EXPLICIT, ordered objective SEQUENCE as
    one proof-carrying campaign via the shipped ``chain_compiler.run_chain`` engine.

    Parses the comma-separated ``--chain`` value into an ordered list (refusing a
    malformed chain — an empty value or an unknown objective — honestly, before any
    work), then hands it VERBATIM to ``run_chain``: each step is precondition-gated
    against the frozen composition grammar, gated through the EXISTING
    ``compile_objective`` verified-with-rollback loop, halts the chain on a
    rolled-back (suite-red) step, and (on an ``--apply`` that landed) is archived +
    recorded to ChainMemory. This handler adds ZERO gate logic — it parses, calls
    the engine, and renders its report (``render_chain_markdown``). Default is a
    dry run; ``--apply`` writes (the same baseline semantics the other develop
    paths use). ``--halt-on-unmet`` opts the chain into halting at the first unmet
    precondition instead of skipping past it."""
    from app.engine.chain_compiler import render_chain_markdown, run_chain

    objectives, error = _parse_chain(getattr(args, "chain", "") or "")
    if error is not None:
        print(f"⛔ {error}", file=sys.stderr)
        return 2
    report = run_chain(
        str(target), objectives, max_steps=max_steps, verify=verify, apply=apply,
        fast=getattr(args, "fast", False),
        halt_on_unmet_precondition=getattr(args, "halt_on_unmet", False))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_chain_markdown(report))
        if report.applied and report.total_moves:
            print(_APPLIED_TREE_NOTE)
    # Non-zero when the chain HALTED on a red (rolled-back) step — an honest,
    # never-faked failure the caller/CI should notice; a green or all-empty chain
    # (nothing to land) is a clean exit.
    return 1 if report.halted else 0


def _parse_goals(raw: str) -> tuple[list[str], str | None]:
    """Split a ``--goals`` value into a goal SET, refusing honestly.

    ``raw`` is the comma-separated set the user typed (``"reduce-debt,tidy"``);
    whitespace around each name is trimmed and empty segments dropped, so
    ``"a, b,"`` yields ``["a", "b"]``. Mirrors ``_parse_chain``'s honest-refusal
    shape: returns ``(goals, error)``, ``error`` is ``None`` on success. Each
    entry is validated via :func:`app.engine.fractal_develop.resolve_goal`'s
    truthiness — a name that resolves to NO leaves (unknown goal AND unknown
    objective) is refused before any work runs, so no partial fixpoint runs on a
    typo. Pure/deterministic: a parse + a resolution check, no clock/IO."""
    from app.engine.fractal_develop import resolve_goal

    goals = [seg.strip() for seg in raw.split(",") if seg.strip()]
    if not goals:
        return [], ("empty --goals — pass a comma-separated goal set (e.g. "
                    "--goals reduce-debt,tidy)")
    unknown = [g for g in goals if not resolve_goal(g)]
    if unknown:
        return goals, (
            f"unknown goal(s) in --goals: {', '.join(unknown)} — every entry "
            "must be a known goal or objective name. Run `apex develop --goal "
            "<name>` to see the goal tree, or `apex develop --all` to see the "
            "objectives.")
    return goals, None


def _develop_fixpoint(args, target, max_steps, verify, apply) -> int:
    """`apex develop --goals A,B,C --fixpoint`: converge a whole goal SET via the
    shipped ``goal_fixpoint.run_goal_fixpoint`` round-based engine.

    Parses the comma-separated ``--goals`` value into a goal set (refusing a
    malformed set — empty or an unknown entry — honestly, before any work), then
    hands it VERBATIM to ``run_goal_fixpoint``: each round sequences the live
    goals by the PROVEN dependency order, lands each atomically (``orchestrate_goal``)
    or via the single-objective fallback (``compile_objective``), and a
    rolled-back goal is permanently retired. Adds ZERO gate logic — it parses,
    forces the SAME unattended covered-only policy ``cmd_evolve`` applies
    (``resolve_covered_only(unattended=True)`` — ``--allow-weak`` is IGNORED here,
    exactly like the evolve loop, because a multi-round headless loop is the
    highest-risk silent-regression surface), calls the engine, and renders its
    report. Default is a dry run; ``--apply`` writes."""
    from app.engine.goal_fixpoint import render_fixpoint_markdown, run_goal_fixpoint
    from app.policies.autonomy_policy import resolve_covered_only

    goals, error = _parse_goals(getattr(args, "goals", "") or "")
    if error is not None:
        print(f"⛔ {error}", file=sys.stderr)
        return 2
    covered_only = resolve_covered_only(
        allow_weak=getattr(args, "allow_weak", False), unattended=True)
    report = run_goal_fixpoint(
        str(target), goals, max_rounds=getattr(args, "max_rounds", 10) or 10,
        max_steps_per_goal=max_steps, verify=verify, apply=apply,
        covered_only=covered_only)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_fixpoint_markdown(report))
        if report.applied and report.total_landed:
            print(_APPLIED_TREE_NOTE)
    # Non-zero when the loop's circuit breaker tripped — an honest, never-faked
    # early stop the caller/CI should notice; a fixpoint / round-cap stop with a
    # clean (or all-empty) run is a clean exit.
    return 1 if report.circuit_broken else 0


def _develop_goal_atomic(args, target, goal, verify, apply) -> int:
    """`apex develop --goal X --atomic`: land the goal's leaves as ONE gated,
    atomic multi-file unit via the shipped ``project_goal_orchestrator`` engine.

    Where the default ``--goal`` path (``compile_goal``) lands each leaf as its own
    independent campaign — so a stub fill can land while its export wiring does not
    — this composes the leaves' single-file plans into ONE plan and lands it through
    the single gated writer: the whole goal lands together or NEITHER, and on a
    regression the ENTIRE goal is rolled back. Adds ZERO gate logic — it calls
    ``orchestrate_goal`` and renders its result (``render_goal_landing_markdown``).
    Default is a dry run; ``--apply`` writes."""
    from app.engine.project_goal_orchestrator import (
        orchestrate_goal, render_goal_landing_markdown,
    )

    landing = orchestrate_goal(str(target), goal, verify=verify, apply=apply,
                               value_led=getattr(args, "value_led", False))
    if args.json:
        print(json.dumps(landing.to_dict(), indent=2))
    else:
        print(render_goal_landing_markdown(landing))
        if landing.applied:
            print(_APPLIED_TREE_NOTE)
    # Non-zero when the goal was UNKNOWN (a usage error) or the composed plan
    # ROLLED BACK (an honest regression); a clean landing / dry-run composition /
    # honest refusal-with-nothing-to-compose exits 0.
    unknown = landing.refused and "unknown goal" in landing.reason
    return 1 if (unknown or landing.rolled_back) else 0


def _develop_objective(args, target, objective, grade_before, max_steps, verify, apply) -> int:
    """`apex develop` default: compose verified transforms toward one objective metric."""
    from app.engine.objective_compiler import compile_objective, render_compile_markdown

    result = compile_objective(
        str(target), objective=objective, max_steps=max_steps,
        verify=verify, apply=apply, scope_verify=getattr(args, "fast", False),
        min_move_value=_min_move_value(args),
        manifesto_aware=getattr(args, "manifesto_aware", False),
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_compile_markdown(result))
        if result.applied and result.steps:
            print(_APPLIED_TREE_NOTE)
    _print_grade_proof(str(target), grade_before, result.applied and bool(result.steps),
                       objective=objective, moves=len(result.steps))
    # Non-zero only when an explicitly named objective is unknown (a usage error).
    return 1 if (result.blocked and not result.steps
                 and any("unknown objective" in b for b in result.blocked)) else 0


def _develop_preview_dispatch(args, target) -> int | None:
    """The read-only preview sub-modes that short-circuit BEFORE any grade read:
    ``--playbook`` / ``--history`` / ``--top``. Returns that helper's exit code,
    or ``None`` when none applies so ``cmd_develop`` falls through to the campaign
    paths. Dispatch order is load-bearing and unchanged."""
    if getattr(args, "playbook", False):
        return _develop_playbook(args, target)
    if getattr(args, "history", False):
        return _develop_history(args, target)
    if getattr(args, "top", False):
        return _develop_top(args, target)
    return None


# Positional `mode_word` values that name a develop MODE rather than an
# objective. `session` runs the combined concrete-objective sequence; the empty
# default is the ordinary single-objective campaign. Every OTHER non-empty word
# is interpreted as an objective name (DWIM) or, if unknown, a usage error — so
# the natural `apex develop <objective>` selects that objective instead of
# silently running the `--objective` default. Keep in sync with cmd_develop's
# `mode_word == "session"` short-circuit.
_DEVELOP_MODE_WORDS: frozenset[str] = frozenset({"session"})


def _resolve_develop_mode_word(args: argparse.Namespace,
                               objective: str) -> tuple[str, str | None]:
    """Interpret the positional ``mode_word`` for the single-objective paths.

    Returns ``(effective_objective, error)``. ``error`` is ``None`` on success;
    otherwise it is a helpful usage message (the caller prints it to stderr and
    exits non-zero).

    The positional swallows a bare objective name (``apex develop
    seal-hashable-eq``), which historically fell through to the ``--objective``
    DEFAULT (``dead-params``) with no warning — the footgun. This resolver makes
    that natural invocation Do What I Mean:

    * empty word, or a recognized MODE word (``session``): objective unchanged;
    * a word that names a registered objective: adopt it as the objective —
      unless the user ALSO passed an explicit ``--objective`` (i.e. something
      other than the ``dead-params`` default), in which case the explicit flag
      wins and the positional is ignored;
    * any other non-empty word: an unknown mode/objective — return an error.
    """
    mode_word = (getattr(args, "mode_word", "") or "").strip()
    if not mode_word or mode_word in _DEVELOP_MODE_WORDS:
        return objective, None
    from app.engine.objective_compiler import available_objectives

    if mode_word in available_objectives():
        # An explicit `--objective X` (anything but the default) wins over the
        # positional, so a deliberate flag is never silently overridden.
        if objective != "dead-params":
            return objective, None
        return mode_word, None
    hint = ", ".join(sorted(_DEVELOP_MODE_WORDS))
    return objective, (
        f"unknown develop mode/objective '{mode_word}' — expected a mode "
        f"({hint}) or an objective name. Run `apex develop --objective "
        f"<name>` (e.g. seal-hashable-eq), or `apex develop --all` to sweep "
        "every objective."
    )


def _develop_goals_dispatch(args, target, max_steps, verify, apply) -> int | None:
    """The ``--goals``/``--fixpoint`` early fork, split out of ``cmd_develop`` to
    keep that function under the complexity ceiling.

    ``--goals`` + ``--fixpoint`` together dispatch to the round-based
    ``goal_fixpoint`` engine (a fixpoint run names its own goals, so it is
    resolved BEFORE the mode-word / ``--atomic`` paths). A ``--goals`` value with
    NO ``--fixpoint`` is a usage error (naming a goal SET only makes sense for
    the round-based loop) — printed to stderr, exit 2. Returns ``None`` when
    neither flag applies, so ``cmd_develop`` falls through to its other
    dispatch paths unchanged."""
    if getattr(args, "goals", "") and getattr(args, "fixpoint", False):
        _warn_manifesto_unsupported(args, "--goals --fixpoint")
        return _develop_fixpoint(args, target, max_steps, verify, apply)
    if getattr(args, "goals", ""):
        print("⛔ --goals requires --fixpoint (a goal SET only runs through the "
             "round-based convergence loop)", file=sys.stderr)
        return 2
    return None


def _warn_manifesto_unsupported(args: argparse.Namespace, mode: str) -> None:
    """``--manifesto`` HARD-ENFORCEs learned laws only through
    ``compile_objective``'s manifesto gate (:func:`_arm_manifesto_skip` /
    :func:`_manifesto_fragile_fired` in ``objective_compiler.py``) — reached
    TODAY by just the default single-objective campaign and ``--auto``. Every
    other ``develop`` mode (``session``, ``--chain``, ``--goals --fixpoint``,
    ``--goal[ --atomic]``, ``--all``, ``--multifile``, ``--from-dream``) routes
    through a DIFFERENT engine (``run_develop_session``, ``run_chain``,
    ``run_goal_fixpoint``, ``compile_goal``/``orchestrate_goal``, ``compile_all``,
    ``run_moves``, ``compile_from_dream``) that does not (yet) accept
    ``manifesto_aware``, so the flag would otherwise be silently dropped — a
    governance flag the user trusted, ignored with no sign of it. Warn honestly
    on stderr, naming the mode that ignored it, instead of pretending to
    enforce. A no-op when ``--manifesto`` was not passed."""
    if getattr(args, "manifesto_aware", False):
        print(f"⚠️  --manifesto is not wired into `develop {mode}` — it "
              "HARD-ENFORCES manifesto laws only for the default single-"
              "objective campaign and --auto. No law was skipped or demoted "
              "this run.", file=sys.stderr)


def cmd_develop(args: argparse.Namespace) -> int:
    """Goal-directed composition: drive an OBJECTIVE metric to its target by
    composing verified transforms, each suite-gated with auto-rollback.

    Where `maintain` applies whatever smell-fix it finds, `develop` pursues a
    measurable goal (e.g. zero dead parameters), composing the moves that reach
    it and proving each step. Default is a dry run; `--apply` writes.

    With `--from-dream`, the campaign is scoped to the modules the nightly dream
    flagged as confluences — the organism acting on its own discovery."""
    objective = getattr(args, "objective", "dead-params") or "dead-params"
    target = Path(args.target).resolve() if args.target else _get_project_root()
    max_steps = getattr(args, "max_steps", 25)
    verify = not getattr(args, "no_verify", False)
    apply = getattr(args, "apply", False)

    preview_rc = _develop_preview_dispatch(args, target)
    if preview_rc is not None:
        return preview_rc

    want_grade = getattr(args, "grade", False)
    grade_before = _grade_score(str(target)) if want_grade else None

    # `apex develop session` (positional) or `apex develop --session`: the
    # combined concrete-objective run. Checked before the single-objective
    # default so the bare-`session` word isn't mistaken for an objective name.
    if (getattr(args, "session", False)
            or getattr(args, "mode_word", "") == "session"):
        _warn_manifesto_unsupported(args, "session")
        return _develop_session(args, target, max_steps, verify, apply)

    # `apex develop --chain a,b,c`: an EXPLICIT ordered objective SEQUENCE via the
    # chain_compiler engine. Checked before the mode-word resolution (a chain names
    # its own objectives) and before the single-objective default. Off unless the
    # flag carries a value, so a bare develop is unaffected.
    if getattr(args, "chain", "") or "":
        _warn_manifesto_unsupported(args, "--chain")
        return _develop_chain(args, target, max_steps, verify, apply)

    # `apex develop --goals A,B,C --fixpoint`: a whole GOAL-SET convergence loop.
    # Checked before the mode-word resolution (a fixpoint run names its own
    # goals) and BEFORE --atomic (--fixpoint wins over --atomic — this early
    # check fires ahead of `_develop_campaign_dispatch`).
    goals_rc = _develop_goals_dispatch(args, target, max_steps, verify, apply)
    if goals_rc is not None:
        return goals_rc

    # DWIM the bare `apex develop <objective>`: a positional mode_word that
    # names a registered objective IS the objective (it used to fall through to
    # the --objective default, silently running the wrong objective). A typo
    # errors helpfully instead of running dead-params.
    objective, mode_word_error = _resolve_develop_mode_word(args, objective)
    if mode_word_error is not None:
        print(mode_word_error, file=sys.stderr)
        return 2

    return _develop_campaign_dispatch(args, target, objective, grade_before,
                                      max_steps, verify, apply)


def _develop_campaign_dispatch(args, target, objective, grade_before,
                               max_steps, verify, apply) -> int:
    """The flag-driven campaign fork, reached after the preview / session /
    mode-word resolution short-circuits. Dispatch order is load-bearing and
    unchanged: ``--goal`` → ``--auto`` → ``--all`` → ``--multifile`` →
    ``--from-dream`` → the default single-objective campaign. ``--goal X --atomic``
    selects the whole-goal ORCHESTRATOR (leaves land as one gated unit) instead of
    the default per-leaf ``compile_goal`` path; without ``--atomic`` the goal path
    is byte-identical to before."""
    goal = getattr(args, "goal", "") or ""
    if goal:
        _warn_manifesto_unsupported(args, "--goal")
        if getattr(args, "atomic", False):
            return _develop_goal_atomic(args, target, goal, verify, apply)
        return _develop_goal(args, target, goal, max_steps, verify, apply)
    if getattr(args, "auto", False):
        return _develop_auto(args, target, grade_before, max_steps, verify, apply)
    if getattr(args, "all_objectives", False):
        _warn_manifesto_unsupported(args, "--all")
        return _develop_all(args, target, grade_before, max_steps, verify, apply)
    if getattr(args, "multifile", False):
        _warn_manifesto_unsupported(args, "--multifile")
        return _develop_multifile(args, target, max_steps, verify, apply)
    if getattr(args, "from_dream", False):
        _warn_manifesto_unsupported(args, "--from-dream")
        return _develop_from_dream(args, target, objective, max_steps, verify, apply)
    return _develop_objective(args, target, objective, grade_before,
                              max_steps, verify, apply)


def _top_runnable_step(plan):
    """The #1 EXECUTABLE step in plan order, or None when the plan is all
    advisory. The plan is already phase-ordered (roadmap) / value-sorted, so the
    first executable step IS the highest-value runnable recommendation — picking
    by plan order keeps the choice deterministic (no time/random tie-break)."""
    for step in plan.steps:
        if step.executable and step.target and str(step.target).endswith(".py"):
            return step
    return None


def _top_proof_lines(step, proof: dict | None) -> list[str]:
    """The chosen step's full proof block: title, concrete anchor focus, and the
    proof line (diff stat + re-parse verdict + impact + coverage verdict)."""
    lines = [
        f"## Top recommendation: `{step.branch_path}` — {step.title}",
        f"- action: **{step.action_type}** on `{step.target}`",
        f"- focus: {step.description}  (value {step.value})",
    ]
    if not proof:
        lines.append("- proof: _(the generator declined to draft a concrete "
                     "diff for this step)_")
        return lines
    verdict = ("re-parses cleanly ✓" if proof.get("reparses")
               else "⚠️ re-parse check failed")
    impact = proof.get("impact") or ""
    impact_clause = f", {impact}" if impact else ""
    coverage = ("your tests reference this module ✓" if proof.get("covered")
                else "⚠️ no test exercises this — add one first")
    lines.append(
        f"- proof: +{proof.get('added', 0)} −{proof.get('removed', 0)}, "
        f"{verdict}{impact_clause} · {coverage}"
    )
    return lines


def _shield_stub_path(step) -> str:
    """The deterministic, repo-relative path for a target's characterization-test
    stub: ``tests/test_<module-stem>_characterization.py``. Pure function of the
    step's target (no time/random), so the same uncovered step always names the
    same file."""
    file_part = (step.target or step.subject.split("::", 1)[0]).split("::", 1)[0]
    stem = file_part.rsplit("/", 1)[-1].removesuffix(".py") or "module"
    slug = "".join(c if (c.isalnum() or c == "_") else "_" for c in stem).strip("_") or "module"
    return f"tests/test_{slug}_characterization.py"


def _write_shield_stub(root: str, step) -> tuple[str, bool]:
    """Write a deterministic characterization-test STUB for the step's uncovered
    target, recommend-only. Reuses the bridge's own ``_test_stub_body`` generator
    (does NOT reimplement it) so the stub names the real symbol(s) + import path.

    Returns ``(repo_relative_path, written)``. Never clobbers an existing
    characterization test for that module — ``written`` is False when the file is
    already there (the caller reports it and skips)."""
    from app.engine.idea_action_bridge import _test_stub_body

    rel = _shield_stub_path(step)
    dest = Path(root) / rel
    if dest.exists():
        return rel, False
    body = _test_stub_body(step, step.target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return rel, True


def _top_no_runnable_step(as_json: bool) -> int:
    """Emit the 'nothing executable' result (advisory-only plan) and return 0."""
    if as_json:
        print(json.dumps({"top": None, "applied": False,
                          "reason": "no-runnable-step"}, indent=2))
    else:
        print("No runnable recommendation right now (the top ideas are advisory).")
    return 0


def _top_emit_shield(payload: dict, proof_lines: list[str], root: str, step,
                     as_json: bool) -> int:
    """CONSTRUCTIVE PATH (--shield): the suite doesn't exercise this target, so a
    green here would be a false green. Instead of (or before) blocking, write a
    deterministic characterization-test STUB for the target — recommend-only, a
    skeleton the user fills in — so the next run's green is REAL. We do NOT
    auto-apply the fix in the same run: the stub is failing by design (it names
    the symbols but has no assertion yet), the point is to make the user write
    the assertion first. Reuses the bridge's own stub-body generator."""
    stub_path, stub_written = _write_shield_stub(root, step)
    payload["shield"] = {"stub_path": stub_path, "written": stub_written}
    if stub_written:
        payload["reason"] = "shield-stub-written"
        message = (
            f"Wrote a characterization-test stub at {stub_path} — fill it in "
            f"so the suite exercises `{step.target}`, then re-run "
            "`apex develop --top --apply`."
        )
    else:
        payload["reason"] = "shield-stub-exists"
        message = (
            f"A characterization test already exists at {stub_path} — fill it "
            f"in so the suite exercises `{step.target}`, then re-run "
            "`apex develop --top --apply`."
        )
    payload["message"] = message
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("\n".join(proof_lines))
        print(f"\n{message}")
    return 0


def _top_emit_false_green(payload: dict, proof_lines: list[str], step,
                          as_json: bool) -> int:
    """THE BLIND-SPOT FIX: a fix on a module NO test references can't be vouched
    for by a green suite — applying it would be a FALSE green. Refuse to
    auto-apply (rc != 0 so automation notices) unless --force overrides."""
    warning = (
        f"⚠️ Your tests don't exercise `{step.target}`. Applying this and "
        "getting a green suite would be a FALSE green — the suite can't see "
        "the change. Add a test first, or re-run with --force to apply anyway."
    )
    payload["reason"] = "false-green-guard"
    payload["warning"] = warning
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("\n".join(proof_lines))
        print(f"\n{warning}")
    return 2


def _top_emit_dry_run(payload: dict, proof_lines: list[str], covered: bool,
                      as_json: bool) -> int:
    """Dry run (default): show the proof, change nothing."""
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("\n".join(proof_lines))
        if not covered:
            print("\n⚠️ Heads up: no test exercises this module — a green "
                  "suite here would be a false green. Add a test first, or "
                  "use --force when applying.")
        print("\nre-run with --apply to land it.")
    return 0


def _top_apply_verdict(result: dict, applied: bool, rolled_back: bool,
                       verified, covered: bool, force: bool) -> str:
    """Honest verdict. A --force apply on an unreferenced module is "weak
    verification" — the suite passed but never looked at the change, so it is
    NOT a plain "verified"."""
    if rolled_back:
        return "↩️ rolled back — tests failed after the patch; tree restored."
    if not applied:
        return f"⛔ not applied — {result.get('reason', 'no applicable patch')}."
    if not covered:
        return ("✅ applied (weak verification — tests don't exercise it; a "
                "green suite here does not prove this change)."
                if force else "✅ applied.")
    if verified:
        return "✅ applied and verified (your tests exercise this module)."
    return "✅ applied (no test command detected — nothing to verify against)."


def _top_emit_apply(args, bridge, plan, step, root: str, payload: dict,
                    proof_lines: list[str], covered: bool, force: bool,
                    as_json: bool) -> int:
    """Apply EXACTLY this one step through the existing guarded loop (single-step,
    verified, auto-rollback). Reuse apply_plan with max_apply=1 over a plan
    holding only the chosen step — no reimplementation of the guarded loop."""
    from app.models.idea import ActionPlan

    one = ActionPlan(objective=plan.objective, project_root=plan.project_root,
                     mode="supervised", steps=[step],
                     stats={"total_steps": 1, "executable_steps": 1})
    summary = bridge.apply_plan(one, root, mode="supervised",
                                verify=not getattr(args, "no_verify", False),
                                max_apply=1)
    result = (summary.get("results") or [{}])[0]
    applied = bool(result.get("applied"))
    rolled_back = bool(result.get("rolled_back"))
    verified = result.get("verified")
    payload.update({"applied": applied, "rolled_back": rolled_back,
                    "verified": verified, "apply_summary": summary})

    verdict = _top_apply_verdict(result, applied, rolled_back, verified,
                                 covered, force)
    payload["verdict"] = verdict

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("\n".join(proof_lines))
        print(f"\n{verdict}")
        if applied and not rolled_back:
            print("_Applied to your working tree, not committed — "
                  "review with `git diff`._")
    # Non-zero when the one step we set out to land did not actually land.
    return 0 if (applied and not rolled_back) else 1


def _top_prove_step(bridge, step, root: str) -> dict | None:
    """The proof the step carries (attach_proofs loaded it onto patch_preview);
    fall back to a fresh draft so a step beyond the proof budget still proves."""
    proof = step.patch_preview if (step.patch_preview and "diff" in step.patch_preview) else None
    if proof is None:
        proof = bridge.prove_step(step, root)
    return proof


def _top_payload(step, covered: bool, proof: dict | None) -> dict:
    """The base JSON payload for the chosen step (mutated as branches resolve)."""
    return {
        "top": {
            "branch": step.branch_path, "title": step.title,
            "action": step.action_type, "target": step.target,
            "value": step.value, "description": step.description,
        },
        "covered": covered,
        "proof": proof,
        "applied": False,
        "verified": None,
    }


def _develop_top(args, target) -> int:
    """`apex develop --top`: close the loop on the SINGLE highest-value proven,
    runnable recommendation through the guarded apply loop, COVERAGE-AWARE so a
    green suite can never claim a false "verified" on a module no test exercises.

    Default is a dry run (show the proof, change nothing). ``--apply`` lands the
    one step via the existing guarded ``apply_plan`` (single-step, verified,
    auto-rollback). The BLIND-SPOT GUARD refuses to auto-apply a fix on an
    unreferenced module (the suite can't see it → false green) and returns
    non-zero so CI notices, UNLESS ``--force`` is passed.
    """
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.engine.verification_strength import module_referenced_by_suite

    root = str(target)
    apply = getattr(args, "apply", False)
    force = getattr(args, "force", False)
    shield = getattr(args, "shield", False)
    as_json = getattr(args, "json", False)

    engine = IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
        project_root=root,
    )
    report = engine.run(objective=getattr(args, "objective", "") or None)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(report, mode="supervised", project_root=root, proof=True)

    step = _top_runnable_step(plan)
    if step is None:
        return _top_no_runnable_step(as_json)

    proof = _top_prove_step(bridge, step, root)
    covered = module_referenced_by_suite(root, step.target)
    payload = _top_payload(step, covered, proof)
    proof_lines = _top_proof_lines(step, proof)
    return _top_dispatch(args, bridge, plan, step, root, payload, proof_lines,
                         covered, apply, force, shield, as_json)


def _top_dispatch(args, bridge, plan, step, root: str, payload: dict,
                  proof_lines: list[str], covered: bool, apply: bool,
                  force: bool, shield: bool, as_json: bool) -> int:
    """Route the chosen step to exactly one emit path: shield-stub, false-green
    guard, dry-run preview, or the guarded single-step apply. Coverage and the
    three flags (apply/force/shield) select the path; each emitter owns its
    payload mutation, output, and exit code."""
    if shield and not covered:
        return _top_emit_shield(payload, proof_lines, root, step, as_json)
    if apply and not covered and not force:
        return _top_emit_false_green(payload, proof_lines, step, as_json)
    if not apply:
        return _top_emit_dry_run(payload, proof_lines, covered, as_json)
    return _top_emit_apply(args, bridge, plan, step, root, payload, proof_lines,
                           covered, force, as_json)


def _grade_score(target: str) -> int:
    """The project's current health score (0–100), or -1 if it can't be read."""
    try:
        from app.engine.health_score import grade
        return grade(target).score
    except Exception:
        return -1


def _print_grade_proof(target: str, before: int | None, applied: bool,
                       objective: str = "", moves: int = 0) -> None:
    """After an applied campaign, prove the gain: re-grade and show before→after,
    and log the run to the development history so the assistant can show its
    trajectory over time. A development tool should show it moved the needle."""
    if before is None or before < 0 or not applied:
        return
    after = _grade_score(target)
    if after < 0:
        return
    arrow = "↑" if after > before else ("↓" if after < before else "→")
    delta = after - before
    sign = "+" if delta > 0 else ""
    print(f"\n**Health grade: {before} → {after} ({sign}{delta} {arrow})** "
          "— the campaign's measured effect on the project.")
    try:
        from app.engine.dev_history import record_run
        record_run(target, objective or "develop", moves, before, after)
    except Exception:
        pass  # history is best-effort; never fail a successful campaign on it


def _untested_own_modules(target: str) -> list[str]:
    """The project's own modules with no linked test (the gaps to shield)."""
    from app.engine.health_score import _is_fixture_path
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(target).profile()
    return [m for m in (getattr(profile, "untested_modules", []) or [])
            if isinstance(m, str) and m.endswith(".py") and not _is_fixture_path(m)]


def _verify_one_test(target: str, test_path: str, timeout: int = 120) -> bool:
    """Run just the generated test file; True when it passes.

    The child gets the TARGET root first on ``PYTHONPATH`` with the inherited
    tail scrubbed of Apex's own repo root (``target_env`` discipline): under
    the proof gate's chunk pin, Apex's regular ``app`` package would otherwise
    shadow a target namespace package of the same name and every generated
    test would be discarded as "failed" on import."""
    import os
    import subprocess

    from app.execution.target_env import inherited_pythonpath
    env = {**os.environ,
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": target + os.pathsep + inherited_pythonpath()}
    try:
        r = subprocess.run(["python", "-m", "pytest", "-q", "-x", test_path],
                           cwd=target, capture_output=True, timeout=timeout,
                           env=env)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _shield_all(target: str, apply: bool, as_json: bool) -> int:
    """Build a characterization test for EVERY untested module — verify each and
    keep only the ones that pass (a written test that fails is worse than none).
    Default previews which modules would be shielded; --apply writes + verifies."""
    import json as _json
    import os

    from app.execution.test_shield import (
        generate_characterization_test, write_shield_test,
    )

    built: list[str] = []
    failed: list[str] = []
    candidates: list[str] = []
    for mod in _untested_own_modules(target):
        shield = generate_characterization_test(target, mod)
        if shield is None:
            continue
        candidates.append(mod)
        if not apply:
            continue
        path = write_shield_test(target, shield)
        if _verify_one_test(target, path):
            built.append(path)
        else:  # a generated test that doesn't pass is removed — never ship red
            try:
                os.remove(Path(target) / path)
            except OSError:
                pass
            failed.append(mod)

    if as_json:
        print(_json.dumps({"candidates": candidates, "built": built,
                           "failed": failed, "applied": apply}, indent=2))
        return 0
    if not candidates:
        print("# Every module already has a test, or none is safely shieldable. 🎉")
        return 0
    if not apply:
        print(f"# `apex shield --all` would build {len(candidates)} test(s) for "
              "untested module(s):\n")
        for m in candidates[:40]:
            print(f"- {m}")
        print("\n_Preview only — pass `--apply` to write and verify them._")
        return 0
    print(f"# Built {len(built)} verified test(s); {len(failed)} skipped (didn't pass).")
    for p in built[:40]:
        print(f"- ✅ {p}")
    for m in failed[:10]:
        print(f"- ↩️ {m} (generated test didn't pass — removed)")
    return 0


def cmd_shield(args: argparse.Namespace) -> int:
    """Build a characterization test for an untested module — Apex develops the
    project's test safety net, not just flags the gap. Default previews the
    generated test; --apply writes it (never clobbers an existing test file).
    ``--all`` shields every untested module at once (each verified)."""
    from app.execution.test_shield import (
        generate_characterization_test, write_shield_test,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    module = getattr(args, "module", "") or ""

    if getattr(args, "all_modules", False):
        return _shield_all(str(target), apply=getattr(args, "apply", False),
                           as_json=args.json)
    if not module:
        print("⛔ shield needs a MODULE (e.g. apex shield app/foo.py), or --all")
        return 1
    shield = generate_characterization_test(str(target), module)
    if shield is None:
        print(f"# No test built for `{module}` — it already has a test, has no "
              "safely-callable public function, or doesn't parse.")
        return 0
    if args.json:
        print(json.dumps({"module": shield.module, "test_path": shield.test_path,
                          "functions": shield.functions, "content": shield.content}, indent=2))
        if getattr(args, "apply", False):
            write_shield_test(str(target), shield)
        return 0
    print(f"# Characterization test for `{shield.module}` → `{shield.test_path}`")
    print(f"_Pins {len(shield.functions)} public function(s): "
          f"{', '.join(shield.functions) or '(import smoke only)'}_\n")
    print("```python")
    print(shield.content.rstrip())
    print("```")
    if getattr(args, "apply", False):
        path = write_shield_test(str(target), shield)
        print(f"\n✅ Wrote {path} — run `python -m pytest {path}` to verify.")
    else:
        print("\n_Preview only — pass `--apply` to write the test._")
    return 0


_LETTER_MIN = {"A+": 97, "A": 93, "A-": 90, "B+": 87, "B": 83, "B-": 80,
               "C+": 77, "C": 73, "C-": 70, "D+": 67, "D": 63, "D-": 60}


def _target_score(value: str) -> int | None:
    """Parse a `--until` target: an integer score, or a letter grade (its floor)."""
    if not value:
        return None
    v = value.strip().upper()
    if v in _LETTER_MIN:
        return _LETTER_MIN[v]
    try:
        return int(v)
    except ValueError:
        return None


def cmd_plan(args: argparse.Namespace) -> int:
    """Show the develop priority board — which objective the organism would
    improve next, worst fixable debt first. Pure preview: changes nothing."""
    from app.engine.ascend import rank_objectives, render_plan_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    goal = getattr(args, "goal", "") or ""
    restrict = None
    if goal:
        from app.engine.fractal_develop import resolve_goal
        restrict = resolve_goal(goal)
    rankings = rank_objectives(str(target), restrict,
                               include_expensive=getattr(args, "concrete", False),
                               value_lead=getattr(args, "value_lead", False))
    if args.json:
        print(json.dumps([r.to_dict() for r in rankings], indent=2))
    else:
        print(render_plan_markdown(rankings))
    return 0


def cmd_ascend(args: argparse.Namespace) -> int:
    """Autonomous self-improvement: each round develop the worst fixable debt,
    suite-gated and grade-proven, to a fixpoint. Default dry run; --apply climbs."""
    from app.engine.ascend import ascend, render_ascend_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    report = ascend(
        str(target), max_rounds=getattr(args, "max_rounds", 4),
        target_score=_target_score(getattr(args, "until", "") or ""),
        apply=getattr(args, "apply", False),
        verify=not getattr(args, "no_verify", False),
        goal=getattr(args, "goal", "") or "",
        max_steps=getattr(args, "max_steps", 25),
        scope_verify=getattr(args, "fast", False),
        include_expensive=getattr(args, "concrete", False),
        value_lead=getattr(args, "value_lead", False))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_ascend_markdown(report))
        if not getattr(args, "apply", False):
            print("[ascend] Dry run — re-run with --apply to climb.")
    return 0


def register_parsers(subparsers) -> None:
    """Register the autonomy family's subcommands: auto, simulate, evolve, maintain."""
    # plan — the develop priority board (what to improve next; changes nothing)
    plan_parser = subparsers.add_parser(
        "plan",
        help="Show the develop priority board: which objective to improve next "
             "(worst fixable debt first)",
    )
    plan_parser.add_argument("--target", default="", help="Target project root")
    plan_parser.add_argument("--goal", default="",
                             help="Restrict the board to one fractal goal's objectives")
    plan_parser.add_argument(
        "--concrete", action="store_true",
        help="Include the EXPENSIVE concrete objectives (implement-stub, "
             "wire-exports, strengthen-tests) in the climb — the highest-value "
             "develop moves, off the fast default board")
    plan_parser.add_argument(
        "--value-lead", action="store_true", dest="value_lead",
        help="Re-weight the board by BUYER VALUE so a cheap Tier-1 fix (harden, "
             "raise-from, infer-type-hints) leads a high-pending idiom tidy "
             "(sort-imports). Does NOT unlock the expensive concrete objectives "
             "(membership still needs --concrete); only re-orders the cheap board. "
             "Off by default (byte-identical); deterministic")
    plan_parser.add_argument("--json", action="store_true", help="Emit JSON")
    plan_parser.set_defaults(func=cmd_plan)

    # ascend — autonomous goal-directed self-improvement to a fixpoint
    ascend_parser = subparsers.add_parser(
        "ascend",
        help="Autonomous self-improvement: develop the worst fixable debt each "
             "round, suite-gated and grade-proven, to a fixpoint (default dry run)",
    )
    ascend_parser.add_argument("--target", default="", help="Target project root")
    ascend_parser.add_argument("--goal", default="",
                               help="Restrict the climb to one fractal goal's objectives")
    ascend_parser.add_argument("--apply", action="store_true",
                               help="Climb for real (default: preview the next move)")
    ascend_parser.add_argument("--max-rounds", type=int, default=4, dest="max_rounds",
                               help="Maximum improvement rounds (default 4)")
    ascend_parser.add_argument("--max-steps", type=int, default=25, dest="max_steps",
                               help="Cap moves per objective per round (default 25)")
    ascend_parser.add_argument("--fast", action="store_true",
                               help="Gate each move against only the impacted tests (fast "
                                    "enough to climb a large project's own body; run the "
                                    "full suite afterwards as the backstop)")
    ascend_parser.add_argument("--until", default="",
                               help="Stop once the health grade reaches this (e.g. 90 or A-)")
    ascend_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                               help="Skip the per-move suite gate (faster, unsafe)")
    ascend_parser.add_argument(
        "--concrete", action="store_true",
        help="Include the EXPENSIVE concrete objectives (implement-stub, "
             "wire-exports, strengthen-tests) in the climb — the highest-value "
             "develop moves, off the fast default board")
    ascend_parser.add_argument(
        "--value-lead", action="store_true", dest="value_lead",
        help="Re-weight the board by BUYER VALUE so a cheap Tier-1 fix (harden, "
             "raise-from, infer-type-hints) leads a high-pending idiom tidy "
             "(sort-imports). Does NOT unlock the expensive concrete objectives "
             "(membership still needs --concrete); only re-orders the cheap board. "
             "Off by default (byte-identical); deterministic")
    ascend_parser.add_argument("--json", action="store_true", help="Emit JSON")
    ascend_parser.set_defaults(func=cmd_ascend)


    # auto — the recommended one-command entry point (no flags to memorize)
    auto_parser = subparsers.add_parser(
        "auto",
        help="Autonomous review: assess the project and recommend (or --apply) the best next moves",
    )
    auto_parser.add_argument("goal", nargs="?", default="", help="Optional natural-language goal")
    auto_parser.add_argument("--target", default="", help="Target project root")
    auto_parser.add_argument(
        "--apply", action="store_true",
        help="Apply the safe, test-verified fixes (PREVIEW by default — Apex never "
             "edits without --apply). The sweep lands only COVERED moves a test "
             "exercises; weak/uncovered moves are previewed (see --allow-weak)",
    )
    auto_parser.add_argument(
        "--allow-weak", action="store_true", dest="allow_weak",
        help="With --apply: also land WEAK moves — ones a green suite passed but "
             "no test exercises (uncovered). Off by default so the sweep is SAFE "
             "(covered-only); this restores the prior land-everything behaviour",
    )
    auto_parser.add_argument(
        "--recommend", action="store_true",
        help="Recommend only — never touch the tree, even if it's safe to act",
    )
    auto_parser.add_argument(
        "--mode", default=None, choices=["report", "supervised", "autonomous"],
        help="Override the execution mode (default: inferred / supervised)",
    )
    auto_parser.add_argument("--commit", action="store_true", help="Commit each applied fix (autonomous)")
    auto_parser.add_argument(
        "--deep", action="store_true", dest="deep",
        help="Also include the EXPENSIVE synthesis objectives (cover-gaps, "
             "tdd-implement, strengthen-tests, wire-exports, generate-usage-doc) "
             "— these run pytest/mutation during grounding (slower).",
    )
    auto_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                             help="Skip test verification (not recommended)")
    auto_parser.add_argument("--max-apply", type=int, default=0, dest="max_apply",
                             help="Cap how many fixes to apply (default 8)")
    auto_parser.add_argument(
        "--evolve", type=int, default=0, dest="evolve",
        help="Run the self-improvement LOOP for N cycles (apply→re-measure→"
             "re-dream→prove) instead of a single pass — the SAME guarded, "
             "per-cycle-verified EvolutionLoop as `apex evolve --max-cycles N`. "
             "N is clamped to [1,10]; N<=0 (default) keeps the one-pass behaviour",
    )
    auto_parser.add_argument("--json", action="store_true", help="Emit JSON")
    auto_parser.add_argument("--out", default="", help="Write the report to this path")
    auto_parser.set_defaults(func=cmd_auto)

    # simulate — preview autonomous improvement on a disposable copy
    sim_parser = subparsers.add_parser(
        "simulate",
        help="Preview what 'apex evolve' would do — run on a throwaway copy, change nothing",
    )
    sim_parser.add_argument("--target", default="", help="Target project root")
    sim_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    sim_parser.add_argument("--max-cycles", type=int, default=3, dest="max_cycles",
                            help="Maximum improvement cycles to simulate")
    sim_parser.add_argument("--max-apply", type=int, default=5, dest="max_apply",
                            help="Max fixes per cycle")
    sim_parser.add_argument("--json", action="store_true", help="Emit JSON")
    sim_parser.set_defaults(func=cmd_simulate)

    # evolve — self-improvement loop: apply → re-measure → prove progress
    evolve_parser = subparsers.add_parser(
        "evolve",
        help="Self-improvement loop: apply guarded fixes to a fixpoint, then prove the gain",
    )
    evolve_parser.add_argument("--target", default="", help="Target project root")
    evolve_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    evolve_parser.add_argument("--max-cycles", type=int, default=3, dest="max_cycles",
                               help="Maximum improvement cycles (default 3)")
    evolve_parser.add_argument("--max-apply", type=int, default=5, dest="max_apply",
                               help="Max fixes applied per cycle (default 5)")
    evolve_parser.add_argument("--mode", default=None,
                               choices=["report", "supervised", "autonomous"],
                               help="Execution mode (default: supervised, or autonomous with --commit)")
    evolve_parser.add_argument("--commit", action="store_true", help="Commit each applied fix")
    evolve_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                               help="Skip test verification (not recommended)")
    evolve_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                               help="Preview the first cycle's fixes without applying")
    evolve_parser.add_argument("--history", action="store_true",
                               help="Show the recorded self-improvement trajectory and exit")
    evolve_parser.add_argument("--json", action="store_true", help="Emit JSON")
    evolve_parser.add_argument("--out", default="", help="Write the report to this path")
    evolve_parser.set_defaults(func=cmd_evolve)

    # develop — goal-directed composition of verified transforms toward a metric
    develop_parser = subparsers.add_parser(
        "develop",
        help="Drive an objective metric (e.g. zero dead parameters) by composing "
             "verified transforms, each suite-gated (default dry run; --apply writes)",
    )
    develop_parser.add_argument(
        "mode_word", nargs="?", default="",
        help="`session` runs the FIXED concrete-objective sequence (implement "
             "stubs, wire exports, infer hints, dataclassify, then modernizers) "
             "in one motion and emits the combined verified diff — the buyer "
             "artifact (default report-only; --apply writes)")
    develop_parser.add_argument("--target", default="", help="Target project root")
    develop_parser.add_argument("--objective", default="dead-params",
                                help="Objective to pursue (default: dead-params)")
    develop_parser.add_argument(
        "--risk-aware", action="store_true", dest="risk_aware",
        help="Order moves by LEARNED rollback risk (proof history) — try the "
             "low-risk ones first, like the maintain path; no-op without history")
    develop_parser.add_argument(
        "--manifesto", action="store_true", dest="manifesto_aware",
        help="HARD-ENFORCE `apex manifesto`'s learned laws in the default "
             "single-objective campaign and --auto ONLY: skip a move an AVOID "
             "law flags (naming the law), demote a move a FRAGILE law flags "
             "(never dropped); no-op (silent) with no manifesto laws, no-op "
             "WITH A WARNING when combined with session/--chain/--goal/--all/"
             "--multifile/--from-dream/--goals --fixpoint (not yet wired there)")
    develop_parser.add_argument(
        "--session", action="store_true",
        help="Run the combined concrete-objective session (same as the `session` "
             "positional) — lands stubs + exports + hints + dataclass + "
             "modernizers in one motion, one combined verified diff")
    develop_parser.add_argument("--goal", default="",
                                help="Pursue a high-level GOAL that fractally decomposes into "
                                     "objectives (e.g. reduce-debt, tidy, simplify-structure)")
    develop_parser.add_argument("--all", action="store_true", dest="all_objectives",
                                help="Sweep EVERY objective in order (modernize, dead-params, "
                                     "shrink-functions, inline-helpers) — clean everything")
    develop_parser.add_argument(
        "--chain", default="", metavar="A,B,C",
        help="Run an EXPLICIT, ordered objective SEQUENCE as ONE proof-carrying "
             "campaign (e.g. --chain implement-stub,cover-gaps,strengthen-tests): "
             "each step is precondition-gated, suite-gated with auto-rollback, and "
             "the chain HALTS honestly on a rolled-back step — no partial "
             "fake-green. A landed chain is archived as a reusable recipe. Default "
             "dry run; --apply writes")
    develop_parser.add_argument(
        "--halt-on-unmet", action="store_true", dest="halt_on_unmet",
        help="With --chain: HALT at the first step whose earlier producer landed "
             "nothing (an unmet precondition) instead of skipping past it")
    develop_parser.add_argument(
        "--goals", default="", metavar="A,B,C",
        help="A SET of goals to converge with --fixpoint (e.g. --goals "
             "reduce-debt,tidy) — each round lands them in PROVEN topological "
             "order until the set reaches a fixpoint (a round that lands "
             "nothing). Requires --fixpoint")
    develop_parser.add_argument(
        "--fixpoint", action="store_true",
        help="Run the round-based goal-SET convergence loop over --goals: each "
             "round sequences the live goals by proven dependency order, lands "
             "each atomically (or via the single-objective fallback), and a "
             "rolled-back goal is PERMANENTLY retired. Stops at a fixpoint, the "
             "round cap, or a circuit breaker. FORCES covered-only (unattended). "
             "Default dry run; --apply writes")
    develop_parser.add_argument(
        "--max-rounds", type=int, default=10, dest="max_rounds",
        help="With --fixpoint: maximum rounds before stopping honestly (default 10)")
    develop_parser.add_argument(
        "--atomic", action="store_true",
        help="With --goal: compose the goal's leaf objectives into ONE multi-file "
             "landing gated ONCE — the whole goal lands together or NEITHER (on a "
             "regression the ENTIRE goal is rolled back), instead of landing each "
             "leaf independently. Default dry run; --apply writes")
    develop_parser.add_argument(
        "--multifile", action="store_true",
        help="Land the COORDINATED multi-file change — implement a tested stub in "
             "a module AND wire its export in the owning package __init__.py — as "
             "ONE verified-or-rolled-back unit (per stub-module/package pair). "
             "Default dry run; --apply writes")
    develop_parser.add_argument(
        "--auto", action="store_true",
        help="AUTONOMOUS: land everything-applicable with NO objective-naming — "
             "pick the objectives that carry qualifying targets (by each "
             "objective's own fitness) and run each suite-gated, auto-rolled-back. "
             "Cheap objectives only by default; add --concrete to also sweep the "
             "EXPENSIVE concrete ones (implement-stub, wire-exports, "
             "strengthen-tests). SAFE: --apply lands only COVERED moves (a test "
             "exercises them); weak/uncovered moves are previewed (--allow-weak "
             "lands them). Default dry run; --apply writes")
    develop_parser.add_argument(
        "--concrete", action="store_true",
        help="With --auto: also sweep the EXPENSIVE concrete objectives "
             "(implement-stub, wire-exports, strengthen-tests — they run pytest), "
             "off the fast default board")
    develop_parser.add_argument(
        "--value-lead", action="store_true", dest="value_lead",
        help="With --auto: re-order the OBJECTIVE board by BUYER VALUE so a cheap "
             "Tier-1 fix (harden, raise-from) leads a high-pending idiom tidy "
             "(sort-imports). Does NOT unlock the expensive concrete objectives "
             "(membership still needs --concrete); only re-orders the cheap board. "
             "Distinct from --value-led (which orders a --goal's leaves). Off by "
             "default (byte-identical)")
    develop_parser.add_argument(
        "--allow-weak", action="store_true", dest="allow_weak",
        help="With --auto --apply: also land WEAK moves — ones a green suite "
             "passed but no test exercises (uncovered). Off by default so the "
             "broad sweep is SAFE (covered-only); this restores land-everything")
    develop_parser.add_argument("--grade", action="store_true",
                                help="Measure the health grade before and after — prove the gain")
    develop_parser.add_argument("--history", action="store_true",
                                help="Show the development trajectory (every graded campaign's gain)")
    develop_parser.add_argument("--from-dream", action="store_true", dest="from_dream",
                                help="Scope the campaign to the modules the nightly "
                                     "dream flagged as confluences (dream → action)")
    develop_parser.add_argument(
        "--deep", action="store_true", dest="deep",
        help="With --from-dream: land the RANKED BOARD of fitness-applicable "
             "objectives on each flagged confluence (not just dead-params) — "
             "more work per module")
    develop_parser.add_argument("--playbook", action="store_true",
                                help="Show the learned composition playbook (best verified "
                                     "recipe per objective) and exit")
    develop_parser.add_argument(
        "--top", action="store_true",
        help="Close the loop on the SINGLE highest-value proven, runnable "
             "recommendation: show its full proof and (with --apply) land it "
             "through the guarded loop, coverage-aware so a green suite can't "
             "claim a false 'verified'")
    develop_parser.add_argument(
        "--force", action="store_true",
        help="With --top --apply: apply even when no test exercises the target "
             "(labels the result weak verification — overrides the false-green guard)")
    develop_parser.add_argument(
        "--shield", action="store_true",
        help="With --top: when no test exercises the target, write a "
             "characterization-test stub for it (recommend-only) instead of just "
             "blocking — fill it in so the suite exercises the target, then re-apply")
    develop_parser.add_argument("--apply", action="store_true",
                                help="Apply the composed moves (default: dry run)")
    develop_parser.add_argument(
        "--value-led", action="store_true", dest="value_led",
        help="With --goal: attempt the highest buyer-value leaves FIRST "
             "(concrete-first — stub bodies, tests, wired surfaces before idiom "
             "ceremony), under the step budget. Off by default (declaration "
             "order); deterministic, hashseed-invariant")
    develop_parser.add_argument(
        "--min-value", type=float, default=None, dest="min_value",
        metavar="FLOOR",
        help="Buyer's value FLOOR (0..1): order an objective's candidate moves by "
             "descending buyer value and SKIP any below FLOOR (e.g. 0.35 drops "
             "Tier-3 idiom ceremony). Off by default; the suite+rollback gate is "
             "untouched, so value never overrides correctness")
    develop_parser.add_argument("--max-steps", type=int, default=25, dest="max_steps",
                                help="Maximum moves to compose (default 25)")
    develop_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                                help="Skip the per-move test verification (not recommended)")
    develop_parser.add_argument("--fast", action="store_true",
                                help="Gate each move against only the impacted tests "
                                     "(fast on a large project; run the full suite after)")
    develop_parser.add_argument("--json", action="store_true", help="Emit JSON")
    develop_parser.set_defaults(func=cmd_develop)

    # shield — build a characterization test for an untested module (development)
    shield_parser = subparsers.add_parser(
        "shield",
        help="Build a characterization test for an untested module (preview; --apply writes it)",
    )
    shield_parser.add_argument("module", nargs="?", default="",
                               help="Module to test (e.g. app/foo.py); omit with --all")
    shield_parser.add_argument("--all", action="store_true", dest="all_modules",
                               help="Shield EVERY untested module (each generated test is verified)")
    shield_parser.add_argument("--target", default="", help="Target project root")
    shield_parser.add_argument("--apply", action="store_true",
                               help="Write the generated test (never clobbers an existing one)")
    shield_parser.add_argument("--json", action="store_true", help="Emit JSON")
    shield_parser.set_defaults(func=cmd_shield)

    # maintain — one-shot scan -> ideate -> apply -> verify -> commit -> report
    maintain_parser = subparsers.add_parser(
        "maintain",
        help="One-shot maintenance: scan, generate fixes, apply (verified), commit, report",
    )
    maintain_parser.add_argument("--target", default="", help="Target project root")
    maintain_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    maintain_parser.add_argument("--depth", type=int, default=2, help="Idea permutation depth")
    maintain_parser.add_argument("--breadth", type=int, default=4, help="Operators per idea")
    maintain_parser.add_argument("--max-ideas", type=int, default=40, dest="max_ideas")
    maintain_parser.add_argument("--top", type=int, default=0, help="Limit plan to top-N ideas")
    maintain_parser.add_argument(
        "--mode", default="supervised",
        choices=["report", "supervised", "autonomous"],
        help="report=plan only, supervised=apply, autonomous=apply+commit",
    )
    maintain_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Preview the diffs of every fix without changing anything",
    )
    maintain_parser.add_argument(
        "--allow-weak", action="store_true", dest="allow_weak",
        help="Also land WEAK moves — ones a green suite passed but no test "
             "exercises (uncovered). Off by default so the apply is SAFE "
             "(covered-only, verified by a test that actually runs the change); "
             "this restores the prior land-everything behaviour",
    )
    maintain_parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip running tests + auto-rollback after each applied step",
    )
    maintain_parser.add_argument(
        "--commit", action="store_true",
        help="Auto-commit each applied step (autonomous mode only)",
    )
    maintain_parser.add_argument(
        "--max-apply", type=int, default=0, dest="max_apply",
        help="Cap how many steps to apply (0 = no cap)",
    )
    maintain_parser.add_argument("--recipe", default="",
                                 help="Scope the pass to one recipe/composite (see `apex recipes`)")
    maintain_parser.add_argument(
        "--avoid-learned-failures", action="store_true",
        dest="avoid_learned_failures",
        help="Closed loop (opt-in): skip a fix the proof-of-fix history predicts "
             "will fail on this module-trait BEFORE wasting an apply+rollback",
    )
    maintain_parser.add_argument(
        "--prefer-reliable", action="store_true", dest="prefer_reliable",
        help="Closed loop (opt-in): stably re-rank the apply order by ascending "
             "fix-risk (from the proof-of-fix history) so a --max-apply budget "
             "spends on the historically most reliable fixes first",
    )
    maintain_parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    maintain_parser.add_argument("--out", default="", help="Write the Markdown report to this path")
    maintain_parser.add_argument(
        "--proof", default="",
        help="Where to write the proof-of-fix evidence JSON "
             "(default: .apex/proof-of-fix.json in the target)",
    )
    maintain_parser.set_defaults(func=cmd_maintain)
