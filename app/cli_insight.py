"""Insight-family commands: explain, brief, dream, outcomes, recipes,
changelog, grade, impact, trackrecord, scope, proof — the commands that READ
the organism.

Final slice of the `app/cli.py` monolith (2290 lines at its peak). Pure
mechanical move: `app.cli` re-exports every symbol, identity-guarded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.cli_common import _get_project_root

if TYPE_CHECKING:
    from app.tools.js_project_profile import JsProjectProfile

# --------------------------------------------------------------------------- #
# quickstart — the 60-second on-ramp: one READ-ONLY command that composes
# EXISTING engines (grade, plus the same bounded idea/roadmap scout ``apex
# auto`` uses) to show a new user Apex's value on THEIR project, in one
# motion. No new analysis is invented here. The "landable" number is the
# bounded scout's count, honestly LABELED as such — quickstart does NOT run
# the full ``apex develop session`` enumeration, because that pass is minutes
# on a large repo and would break the 60-second promise (see
# ``_quickstart_landable`` for the measured evidence). The output points to
# ``apex develop`` for the full enumeration instead of pretending the two
# numbers are the same.
# --------------------------------------------------------------------------- #

_QUICKSTART_BANNER = "Zero-token · offline · deterministic · never-fake-green."

# Small budget so the idea/roadmap pass stays cheap — the same cost class as
# `apex auto`'s scout, deliberately smaller (no --deep synthesis, either).
_QUICKSTART_MAX_IDEAS = 20
_QUICKSTART_DEPTH = 1
_QUICKSTART_BREADTH = 3


def _quickstart_health(target: Path) -> dict:
    """The project's grade — the exact DATA ``apex grade`` renders (reuses
    ``health_score.grade``, never ``cmd_grade``), reduced to a score/letter/
    one-line breakdown. Defensively wrapped: a brand-new/unreadable project
    still yields an honest clean-bill grade instead of raising."""
    from app.engine.health_score import grade

    try:
        h = grade(str(target))
    except Exception:
        return {"score": 100, "letter": "A+",
                 "breakdown": "no gradeable Python code found"}
    costly = sorted((c for c in h.components if c.points_lost > 0),
                    key=lambda c: -c.points_lost)
    breakdown = ("; ".join(f"{c.name} -{c.points_lost}" for c in costly[:3])
                 if costly else "clean bill of health — nothing is costing points")
    return {"score": h.score, "letter": h.letter, "breakdown": breakdown}


def _quickstart_report(target: Path):
    """Run the SAME cheap idea-engine path ``apex auto`` scouts with, at a
    smaller budget. Defensively wrapped so an empty/brand-new project yields
    ``None`` (an honest zero-opportunity report) instead of raising."""
    from app.engine.idea_permutation import IdeaPermutationEngine

    try:
        return IdeaPermutationEngine(
            config={"max_total_ideas": _QUICKSTART_MAX_IDEAS,
                    "max_idea_depth": _QUICKSTART_DEPTH,
                    "breadth": _QUICKSTART_BREADTH},
            project_root=str(target),
        ).run()
    except Exception:
        return None


def _quickstart_opportunities(report) -> list[dict]:
    """Top-3 roadmap items — reuses ``RoadmapSynthesizer().build(report)``
    (the same synthesis ``cmd_auto`` builds) and ``best_first_move``'s own
    tie-break key (value/effort, then phase, then value) to rank across
    phases, so this invents no new prioritization."""
    if report is None:
        return []
    from app.engine.idea_roadmap import PHASE_ORDER, RoadmapSynthesizer

    try:
        roadmap = RoadmapSynthesizer().build(report)
    except Exception:
        return []
    candidates = [i for phase in roadmap.phases for i in phase.items]
    if not candidates:
        return []
    phase_rank = {name: n for n, name in enumerate(PHASE_ORDER)}
    ranked = sorted(candidates, key=lambda i: (
        -round(i.value / max(i.effort, 0.1), 6),
        phase_rank.get(i.phase, len(PHASE_ORDER)),
        -i.value, i.effort, -i.roi, i.branch_path,
    ))
    return [{"branch_path": i.branch_path, "title": i.title, "phase": i.phase,
             "roi": i.roi} for i in ranked[:3]]


def _quickstart_landable(report, target: Path) -> int:
    """How many executable moves the bounded quickstart scout can see — the
    roadmap's ``executable_steps`` over the SAME capped idea tree
    ``_quickstart_report`` already built (20 ideas / depth 1 / breadth 3), so
    quickstart pays for ONE cheap scout pass, not two engines.

    HONESTY NOTE — this is a DIFFERENT, smaller engine than the enumeration
    ``apex develop session`` runs, and the two counts genuinely diverge (a
    live run on this repo showed 17 vs. 76). Unifying them was tried and
    REJECTED on measured evidence: ``run_develop_session(apply=False)`` took
    120s even bounded to ``max_steps=1`` and 5+ minutes unbounded on a
    630-module repo — a per-move whole-project re-parse cost that breaks the
    60-second on-ramp promise outright. The fix is in the LABEL, not the
    engine: ``_quickstart_landable_line`` names this number as the bounded
    scout's count and points to ``apex develop`` for the full enumeration,
    so no equality between the two is ever claimed.

    Defensively wrapped: any failure collapses to 0 (honest empty), never
    raises."""
    if report is None:
        return 0
    from app.engine.idea_action_bridge import IdeaActionBridge

    try:
        plan = IdeaActionBridge().plan_roadmap(
            report, mode="report", project_root=str(target))
        return int(plan.stats.get("executable_steps", 0))
    except Exception:
        return 0


def _quickstart_suite_detected(target: Path) -> bool:
    """Whether a test suite is DETECTABLE for this project — a pure,
    filesystem-only check (config files / ``tests/`` dir / a flat
    pytest-discoverable layout), no subprocess and no test run. Backs the
    honest per-suite-state wording below: quickstart must never promise
    test-verification a suite-less project cannot earn. Defensively wrapped:
    any failure reads as "no suite detected" — the conservative,
    never-fake-green reading."""
    from app.skills.execution.run_tests import RunTestsSkill

    try:
        return bool(RunTestsSkill()._detect_commands(target))
    except Exception:
        return False


def _quickstart_next_steps(target_arg: str) -> list[str]:
    """Three copy-paste commands, parameterized on the SAME ``--target`` value
    the user passed in (so they are valid to paste verbatim, whatever the
    current shell's cwd is)."""
    return [
        f"apex grade --target {target_arg} --diff",
        f"apex develop --target {target_arg} --apply",
        f"apex dashboard --target {target_arg}",
    ]


def _quickstart_landable_line(landable_count: int, suite_detected: bool) -> str:
    """The one honest "what Apex can land right now" sentence — worded per
    whether a test suite is DETECTABLE, so quickstart never promises
    test-verification a suite-less project cannot earn (never-fake-green).

    With a detectable suite: each move will be test-verified on ``--apply``
    (suite-gated, auto-rollback) — the TIER_VERIFIED/TIER_WEAK story
    ``apex develop`` carries through. With NO detectable suite: say so
    plainly — a landed move would carry the ``no-suite`` tier, unverified,
    never dressed up as "test-verified".

    The count is also honestly ATTRIBUTED: it is the bounded quickstart
    scout's number, not ``apex develop``'s full enumeration (a different,
    bigger engine — see ``_quickstart_landable``), so the line names its
    source and points to ``apex develop`` for the full count instead of
    implying the two are equal."""
    if suite_detected:
        return (
            f"{landable_count} move(s) found by the bounded quickstart scout "
            "— full enumeration: `apex develop` (preview); each lands "
            "test-verified on --apply (suite-gated, auto-rollback).")
    return (
        f"{landable_count} move(s) found by the bounded quickstart scout — "
        "no test suite detected: moves would land unverified (no-suite "
        "tier). Full enumeration: `apex develop` (preview).")


def _render_quickstart(data: dict) -> list[str]:
    """Render the human-readable report from the SAME dict ``--json`` emits."""
    g = data["grade"]
    lines = [_QUICKSTART_BANNER, "",
             f"## Health: {g['letter']}  ({g['score']}/100)",
             data["breakdown"], "",
             "## Top opportunities (what to develop next)"]
    if data["top_opportunities"]:
        for n, op in enumerate(data["top_opportunities"], 1):
            lines.append(f"{n}. `{op['branch_path']}` {op['title']} "
                        f"({op['phase']} · ROI {op['roi']})")
    else:
        lines.append("_No opportunities yet — this project may be new or very small._")
    lines.append("")
    lines.append("## What Apex can land right now")
    lines.append(_quickstart_landable_line(
        data["landable_count"], data["suite_detected"]))
    lines.append("")
    lines.append("## Next steps")
    lines.extend(f"- `{cmd}`" for cmd in data["next_steps"])
    return lines


def cmd_quickstart(args: argparse.Namespace) -> int:
    """The 60-second on-ramp, as ONE motion: health grade, top opportunities,
    and what the bounded scout says Apex can land right now — composed
    entirely from existing, already-deterministic engines
    (``health_score.grade`` and the capped idea/roadmap scout). The landable
    number is labeled as the scout's count and defers to ``apex develop``
    for the full enumeration (see ``_quickstart_landable``).

    STRICTLY READ-ONLY: every call below is report-mode / dry-run / draft-off,
    so this never applies a fix and never snapshots — a pure measurement, like
    ``apex grade``. Deterministic: no clock/random touches the output, so the
    same project yields byte-identical output run after run.
    """
    raw_target = getattr(args, "target", "") or ""
    target = Path(raw_target).resolve() if raw_target else _get_project_root()

    health = _quickstart_health(target)
    report = _quickstart_report(target)
    data = {
        "grade": {"score": health["score"], "letter": health["letter"]},
        "breakdown": health["breakdown"],
        "top_opportunities": _quickstart_opportunities(report),
        "landable_count": _quickstart_landable(report, target),
        "suite_detected": _quickstart_suite_detected(target),
        "next_steps": _quickstart_next_steps(raw_target or "."),
    }

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        print("\n".join(_render_quickstart(data)))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    """Explain why a specific idea scored what it did — the engine's reasoning."""
    from app.engine.idea_explain import explain_idea, render_explanation_markdown
    from app.engine.idea_permutation import IdeaPermutationEngine

    target = Path(args.target).resolve() if args.target else _get_project_root()
    report = IdeaPermutationEngine(
        config={"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
                "breadth": args.breadth, "fractal_facets": getattr(args, "facets", False)},
        project_root=str(target),
    ).run(objective=args.objective or None)

    branch = getattr(args, "branch", "") or ""
    if not branch:
        # --top (default): explain the highest-value idea in the tree.
        if not report.ideas:
            print("[explain] No ideas generated for this target.")
            return 1
        branch = max(report.ideas, key=lambda i: i.value).branch_path

    exp = explain_idea(report, branch)
    if exp is None:
        print(f"[explain] No idea found at branch `{branch}`. "
              "Run `apex ideate` to see available branch paths.")
        return 1

    if args.json:
        print(json.dumps(exp.to_dict(), indent=2))
    else:
        print(render_explanation_markdown(exp))
    return 0


def _brief_check(args: argparse.Namespace, target: Path, branch: str) -> int:
    """The ``--check`` sub-path: re-measure a saved brief's evidence burndown."""
    from app.engine.idea_brief import check_brief, render_check_markdown

    if not branch:
        print("⛔ --check needs the BRANCH of a previously saved brief "
              "(apex brief x.o --save)")
        return 1
    result = check_brief(str(target), branch)
    if result is None:
        print(f"⛔ no saved brief for `{branch}` — save one first: "
              f"apex brief {branch} --save")
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_check_markdown(result))
    return 0


def _brief_develop(args: argparse.Namespace, target: Path, branch: str) -> int:
    """The ``--develop`` sub-path: run evidenced concerns as develop campaigns."""
    from app.engine.brief_develop import (
        develop_brief,
        render_brief_develop_markdown,
    )

    result = develop_brief(
        str(target), branch_path=branch,
        subject=getattr(args, "subject", "") or "",
        max_steps=getattr(args, "max_steps", 25),
        verify=not getattr(args, "no_verify", False),
        apply=getattr(args, "apply", False),
        depth=args.depth, breadth=args.breadth, max_ideas=args.max_ideas,
        objective_focus=args.objective or "")
    if result is None:
        print("No design-level idea to develop (every idea is directly executable).")
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_brief_develop_markdown(result))
        if not getattr(args, "apply", False):
            print("[brief] Dry run — re-run with --develop --apply to land the moves.")
    return 0


def _brief_build(args: argparse.Namespace, target: Path, branch: str) -> int:
    """The default sub-path: build (and optionally --save) a fresh brief."""
    from app.engine.idea_brief import (
        build_brief,
        render_brief_markdown,
        save_brief,
    )
    from app.engine.idea_permutation import IdeaPermutationEngine

    report = IdeaPermutationEngine(
        {"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
         "breadth": args.breadth},
        project_root=str(target),
    ).run(objective=args.objective or None)
    brief = build_brief(report, branch_path=branch,
                        subject=getattr(args, "subject", "") or "")
    if brief is None:
        print("No design-level idea to brief (every idea is directly executable).")
        return 1
    if args.json:
        print(json.dumps(brief.to_dict(), indent=2))
    else:
        print(render_brief_markdown(brief))
    if getattr(args, "save", False):
        path = save_brief(brief, str(target))
        print(f"\n[brief] Evidence baseline saved to {path} — "
              f"measure progress later with: apex brief {brief.branch_path} --check")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """A design-level idea rendered as an actionable engineering brief.

    ``--save`` snapshots the brief's evidence baseline; ``--check`` re-measures
    a saved brief against the CURRENT code — evidenced items whose evidence
    vanished are resolved by the scan, not by a checkbox (the burndown).
    """
    target = Path(args.target).resolve() if args.target else _get_project_root()
    branch = getattr(args, "branch", "") or ""

    if getattr(args, "check", False):
        return _brief_check(args, target, branch)
    if getattr(args, "develop", False):
        return _brief_develop(args, target, branch)
    return _brief_build(args, target, branch)


def cmd_dream(args: argparse.Namespace) -> int:
    """Review the organism's memory stores, extract patterns, curate, digest.

    With ``--land`` it instead runs the overnight LANDING CHAIN (``_cmd_dream_land``):
    the value-led concrete objectives, scoped to the dream's confluences, each
    verified-with-rollback. Without ``--land`` the command is unchanged.

    ``--learn-gates`` (opt-in, default off) threads ``learn_gates=True`` into the
    promote gate — tighten-only feedback from realized-fix evidence; omitted, the
    gate is the static constants (byte-identical)."""
    if getattr(args, "land", False):
        return _cmd_dream_land(args)
    from app.engine.dream import dream, render_dream_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    report = dream(str(target), curate=getattr(args, "curate", False),
                   learn_gates=getattr(args, "learn_gates", False))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_dream_markdown(report))
        if report.digest_path:
            print(f"[dream] Digest written to {report.digest_path}")
    return 0


def _cmd_dream_land(args: argparse.Namespace) -> int:
    """`apex dream --land`: the overnight landing CHAIN.

    Runs ``dream_develop`` — the value-led concrete objective order, scoped to the
    dream's confluence modules (or whole-tree when none), each landed through the
    existing verified-with-rollback compiler — and prints one DreamChainReport.
    DRY-RUN by default; ``--apply`` writes, ``--fast`` scopes the per-move gate.
    Exit 0 even on an empty chain — a project with nothing landable is an honest
    refusal, not a failure.

    ``apex dream --land`` is the project's ONLY unattended landing surface — no
    human reviews the diff between chain steps the way an ``apex develop``/
    ``apex assist --apply`` session would — so it forces ``covered_only`` True via
    ``resolve_covered_only(unattended=True)``, the SAME single-source-of-truth
    policy ``apex evolve``/the daemon force for their own unattended loops (#115's
    precedent). Strictly demote-direction: a move a green suite can't vouch for is
    withheld (previewed) instead of landed; it can never make a run land MORE. A
    DRY RUN (the default, no ``--apply``) never reaches the gated apply loop, so
    the preview is byte-identical regardless."""
    from app.engine.dream_develop import (
        _PREVIEW_MAX_MODULES,
        dream_develop,
        record_dream_chain_memory,
        record_dream_outcomes,
        render_dream_chain_markdown,
    )
    from app.policies.autonomy_policy import resolve_covered_only

    target = Path(args.target).resolve() if args.target else _get_project_root()
    covered_only = resolve_covered_only(allow_weak=False, unattended=True)

    preview = getattr(args, "preview", False)
    apply = getattr(args, "apply", False)
    value_ranked = getattr(args, "value_ranked", False)
    # Explicit --max-modules N always wins; else --preview supplies the shared
    # default cap; else no cap (the exhaustive chain). This keeps an explicit N
    # from being silently overridden when --preview is also passed.
    max_modules = (args.max_modules if getattr(args, "max_modules", None) is not None
                   else (_PREVIEW_MAX_MODULES if preview else None))
    # A non-positive cap is a no-op in the engine (_centrality_capped / the
    # value-ranked slice both treat <= 0 as "keep all"), so normalize it to "no
    # cap" HERE too — otherwise the disclosure below would claim "capped to top 0"
    # while every confluence was actually retained.
    if max_modules is not None and max_modules <= 0:
        max_modules = None

    report = dream_develop(str(target), apply=apply,
                           fast=getattr(args, "fast", False),
                           covered_only=covered_only,
                           max_modules=max_modules,
                           value_ranked=value_ranked,
                           preview_skip_mutation=preview)
    _dream_land_write_proof(args, report, target)
    # Learn-loop: feed the chain's OWN landed/withheld per-direction outcomes, and
    # its per-scope-module composition recipe, back into the SAME learn stores the
    # next-night dream ranking reads. Both are a strict no-op on a dry run / empty
    # chain, so the off-by-default tree stays byte-identical.
    record_dream_outcomes(report, str(target))
    record_dream_chain_memory(report, str(target))

    # CLI-LOCAL disclosure of any bound the user armed — never mutates the shared
    # DreamChainReport / renderer, so every other caller stays byte-identical.
    bound, note = _dream_bound_disclosure(preview, apply, max_modules, value_ranked)
    if args.json:
        payload = report.to_dict()
        if bound is not None:
            payload["preview_bound"] = bound
        print(json.dumps(payload, indent=2))
    else:
        print(render_dream_chain_markdown(report))
        if note is not None:
            print(note)
    return 0


def _dream_bound_disclosure(preview, apply, max_modules, value_ranked):
    """The honest ``(json_dict, text_line)`` disclosure of any armed dream bound,
    or ``(None, None)`` when no bound was requested. A non-positive ``max_modules``
    has already been normalized to ``None`` by the caller, so a cap is disclosed
    only when it actually bit."""
    if not (preview or max_modules is not None or value_ranked):
        return None, None
    bound = {
        "max_modules": max_modules,
        "value_ranked": value_ranked,
        # The mutation objective is dropped only on a dry-run preview.
        "skipped_mutation_objectives": bool(preview and not apply),
    }
    parts = []
    if max_modules is not None:
        parts.append(f"capped to top {max_modules} confluence module(s) by centrality")
    if value_ranked:
        parts.append("ordered by value (highest-leverage first)")
    if bound["skipped_mutation_objectives"]:
        parts.append("skipped the un-previewable mutation objective (strengthen-tests)")
    note = ("Bounded run: " + "; ".join(parts)
            + " — re-run without --preview/--max-modules/--value-ranked "
            "for the exhaustive chain.")
    return bound, note


def _dream_land_write_proof(args: argparse.Namespace, report, target: Path) -> None:
    """Persist the LANDED chain onto the shared proof-of-fix trail.

    On ``--apply`` with at least one landed campaign, write the dream chain's
    verified-with-rollback moves to ``<target>/.apex/proof-of-fix.json`` (the SAME
    artifact value-landed / the owner-report / the tamper-seal consume), so the
    dream differentiator's realized buyer value becomes legible cross-run. Mirrors
    ``_maintain_write_proof``'s guard exactly: a DRY RUN (``apply`` off) or an empty
    chain (no ``results``) writes NOTHING — the off-by-default tree stays
    byte-identical. ``write_proof`` archives the prior pointer, so this merges with
    the maintain history layer rather than clobbering it."""
    if not (getattr(args, "apply", False) and report.results):
        return
    from app.engine.dream_develop import build_dream_proof
    from app.engine.proof_of_fix import write_proof

    proof = build_dream_proof(report, str(target))
    proof_path = write_proof(proof, str(target))
    if not args.json:
        print(f"\n[dream] Proof-of-fix evidence written to {proof_path}")


def cmd_intelligence(args: argparse.Namespace) -> int:
    """Unified Apex Intelligence report — anomalies, validated discoveries,
    emerging hotspots, proposed fix-rules, and self-assessment in one view."""
    from app.engine.intelligence_report import build_intelligence_report
    from app.tools.project_profile import ProjectProfiler

    target = Path(args.target).resolve() if args.target else _get_project_root()
    profile = ProjectProfiler(str(target)).profile(light=False)
    print(build_intelligence_report(profile, str(target)))
    return 0


def _render_polyglot_markdown(summary: dict, findings: list) -> str:
    """Deterministic markdown for the non-Python risk surface."""
    lines = ["# Polyglot risk (non-Python)", ""]
    langs = summary.get("languages", []) if isinstance(summary, dict) else []
    lines.append("## Languages")
    if langs:
        for lang in langs:
            lines.append(f"- **{lang.get('language', '?')}**: "
                         f"{lang.get('files', 0)} file(s), {lang.get('loc', 0)} LOC")
    else:
        lines.append("_No non-Python source found._")
    lines += ["", "## Hotspots"]
    hotspots = summary.get("hotspots", []) if isinstance(summary, dict) else []
    if hotspots:
        for h in hotspots:
            lines.append(f"- `{h.get('path', '?')}` (score {h.get('score', 0)}): "
                         f"{h.get('why', '')}")
    else:
        lines.append("_Nothing notable._")
    lines += ["", "## Findings"]
    if findings:
        for f in findings[:20]:
            lines.append(f"- `{f.get('path', '?')}:{f.get('line', 0)}` "
                         f"[{f.get('severity', '?')}/{f.get('kind', '?')}] "
                         f"{f.get('message', '')}")
    else:
        lines.append("_No high-confidence findings._")
    return "\n".join(lines)


def cmd_readiness(args: argparse.Namespace) -> int:
    """Honest real-world readiness: the fixer-vs-linter actionability ratio
    (how many planned steps Apex can auto-fix vs only flag) + scope coverage."""
    from app.engine.readiness_report import render_readiness_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    print(render_readiness_markdown(str(target)))
    return 0


def cmd_fixrisk(args: argparse.Namespace) -> int:
    """Learned fix-risk: how likely a planned fix is to roll back, from Apex's
    own proof history + counterfactual learning (deterministic, read-only).

    With ``--explain`` (requires ``--action`` and ``--module``), prints a
    per-signal risk breakdown for ONE candidate instead of the aggregate
    report — see :func:`app.engine.fix_risk_model.render_fix_risk_explanation`."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    if getattr(args, "explain", False):
        action = getattr(args, "action", "") or ""
        module = getattr(args, "module", "") or ""
        if not action or not module:
            print("fix-risk --explain requires --action and --module")
            return 2
        from app.engine.fix_risk_model import render_fix_risk_explanation

        print(render_fix_risk_explanation(action, module, str(target)))
        return 0

    from app.engine.fix_risk_model import render_fix_risk_markdown

    print(render_fix_risk_markdown(str(target)))
    return 0


def cmd_discoveries(args: argparse.Namespace) -> int:
    """Ranked discovery leads: anomaly + temporal + rule-synthesis engines fused
    into one corroboration-ranked stream (deterministic, read-only)."""
    from app.engine.discovery_synthesis import render_discoveries_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    print(render_discoveries_markdown(str(target)))
    return 0


def cmd_polyglot(args: argparse.Namespace) -> int:
    """Non-Python risk surface: TS/JS/YAML/HTML/shell hotspots + findings."""
    from app.engine.polyglot_findings import scan_polyglot_findings
    from app.engine.polyglot_metrics import polyglot_summary

    target = Path(args.target).resolve() if args.target else _get_project_root()
    summary = polyglot_summary(str(target))
    findings = scan_polyglot_findings(str(target))
    if args.json:
        print(json.dumps({"summary": summary, "findings": findings}, indent=2))
    else:
        print(_render_polyglot_markdown(summary, findings))
    return 0


def cmd_outcomes(args: argparse.Namespace) -> int:
    """Grade the project against YOUR written rubric (per-criterion gaps)."""
    from app.engine.outcomes import (
        RUBRIC_REL,
        evaluate,
        init_rubric,
        render_outcomes_markdown,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    if getattr(args, "init", False):
        path = init_rubric(str(target))
        print(f"[outcomes] Starter rubric written to {path} — edit the bar, "
              "then run `apex outcomes` (exits non-zero on gaps; CI-ready).")
        return 0
    report = evaluate(str(target))
    if report is None:
        print(f"⛔ no rubric at {RUBRIC_REL} — create one: apex outcomes --init")
        return 1
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_outcomes_markdown(report))
    return 0 if report.passed else 1


def cmd_recipes(args: argparse.Namespace) -> int:
    """List the named, composable transform catalog."""
    from app.execution.recipes import COMPOSITES, RECIPES, render_recipes_markdown

    if args.json:
        print(json.dumps({"recipes": [r.to_dict() for r in RECIPES.values()],
                          "composites": {k: list(v) for k, v in COMPOSITES.items()}},
                         indent=2))
    else:
        print(render_recipes_markdown())
    return 0


def cmd_changelog(args: argparse.Namespace) -> int:
    """Release notes written from artifacts, not memory."""
    from app.reporting.changelog import build_changelog

    target = Path(args.target).resolve() if args.target else _get_project_root()
    md = build_changelog(str(target))
    print(md)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"[changelog] Written to {out_path}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    """Give the project a single health grade (A–F) with a breakdown."""
    from app.engine.health_score import (
        grade, load_grade_snapshot, render_grade_diff_markdown,
        render_grade_markdown, save_grade_snapshot,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    h = grade(str(target))

    if getattr(args, "diff", False):
        old = load_grade_snapshot(str(target))
        if old:
            print(render_grade_diff_markdown(old, h))
        else:
            print("_No grade snapshot found — run `apex grade --save` first._\n")
            print(render_grade_markdown(h))
    elif args.json:
        print(json.dumps(h.to_dict(), indent=2))
    else:
        print(render_grade_markdown(h))

    if getattr(args, "save", False):
        save_grade_snapshot(str(target), h)
        print("[grade] Snapshot saved to .apex/grade-snapshot.json")

    if getattr(args, "min_score", 0) and h.score < args.min_score:
        return 1
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    """Show the blast radius of changing a function: who transitively calls it."""
    from app.engine.call_graph import CallGraph, render_impact_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    graph = CallGraph.build(str(target))
    if args.json:
        print(json.dumps({
            "function": args.function,
            "definitions": [d.to_dict() for d in graph.definitions(args.function)],
            "direct_callers": [d.to_dict() for d in graph.direct_callers(args.function)],
            "blast_radius": [d.to_dict() for d in graph.blast_radius(args.function)],
        }, indent=2))
    else:
        print(render_impact_markdown(args.function, graph))
    return 0




def cmd_duplication(args: argparse.Namespace) -> int:
    """Find copy-pasted code blocks across the project — fix the bug once, miss
    the other three copies. Reports each duplicated block and where it lives."""
    from app.engine.dedup import find_duplicates, render_duplicates_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    blocks = find_duplicates(str(target),
                             min_statements=getattr(args, "min_statements", 5),
                             min_occurrences=2)
    if args.json:
        print(json.dumps([b.to_dict() for b in blocks], indent=2))
    else:
        print(render_duplicates_markdown(blocks))
    return 0


def cmd_mutants(args: argparse.Namespace) -> int:
    """Measure test STRENGTH by mutation: seed faults into a module and see how
    many the suite kills vs. survives (survivors = where the tests are blind)."""
    from app.engine.mutation_tester import (
        mutation_score,
        render_mutation_markdown,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    result = mutation_score(
        str(target), args.module,
        max_mutants=args.max_mutants, verify_timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(render_mutation_markdown(result))
    return 0


def cmd_immune(args: argparse.Namespace) -> int:
    """Apex's IMMUNE system — proactively find where the suite is blindest and,
    with --apply, land mutant-killing assertions there via the strengthen-tests
    engine. Default is a fast, read-only posture report (no writes)."""
    from app.reporting.immune_report import immune_posture, render_immune_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    if getattr(args, "apply", False):
        from app.engine.objective_compiler import compile_objective
        result = compile_objective(
            str(target), objective="strengthen-tests", apply=True, verify=True,
            max_steps=getattr(args, "max_modules", 0) or 3)
        landed = [s for s in result.steps if getattr(s, "verified", False)]
        if getattr(args, "json", False):
            print(json.dumps({"immunized": [s.target for s in landed],
                              "count": len(landed)}, indent=2))
            return 0
        if not landed:
            print("Immune sweep: no surviving mutant could be killed with an "
                  "honest double-gated assertion right now (nothing landed).")
            return 0
        print(f"# Immune sweep — {len(landed)} module(s) hardened\n")
        for step in landed:
            print(f"- `{step.target}` — {step.description}")
        return 0
    posture = immune_posture(target, top=getattr(args, "top", 20))
    if getattr(args, "json", False):
        print(json.dumps(posture, indent=2))
        return 0
    print(render_immune_markdown(posture), end="")
    return 0


def cmd_manifesto(args: argparse.Namespace) -> int:
    """The project's LIVING MANIFESTO — the architectural laws Apex has LEARNED
    here (AVOID / FRAGILE / TRUST / PROVEN idioms), synthesised from its proof-
    carrying experience. Read-only, deterministic, zero-token."""
    from app.engine.manifesto import derive_manifesto, render_manifesto_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    manifesto = derive_manifesto(target)
    if getattr(args, "json", False):
        print(json.dumps(manifesto, indent=2))
        return 0
    print(render_manifesto_markdown(manifesto), end="")
    return 0


def _objective_reachability() -> tuple[list[str], set[str]]:
    """Every registered develop objective, plus the subset the idea engine can
    actually PROPOSE (i.e. a value in ``FACET_OBJECTIVE_MAP``).

    Honest self-measurement: an objective the compiler knows how to pursue is
    still *unreachable* unless some facet phrase routes to it. Both sets are read
    live from the registries, so the answer tracks the code, never a snapshot.
    """
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    registered = sorted(set(available_objectives()))
    # Reachable == mapped AND actually registered (a map value naming a retired
    # objective is not a capability the compiler can deliver).
    reachable = set(FACET_OBJECTIVE_MAP.values()) & set(registered)
    return registered, reachable


def cmd_objectives(args: argparse.Namespace) -> int:
    """List every registered develop objective with whether the idea engine can
    reach it — surfacing objectives wired into the compiler but not yet routed
    from any facet phrase (``FACET_OBJECTIVE_MAP``)."""
    registered, reachable = _objective_reachability()

    if getattr(args, "json", False):
        print(json.dumps({
            "objectives": [
                {"name": name, "reachable": name in reachable}
                for name in registered
            ],
            "total": len(registered),
            "reachable": sorted(reachable),
            "unreachable": [n for n in registered if n not in reachable],
            "reachable_count": len(reachable),
            "unreachable_count": len(registered) - len(reachable),
        }, indent=2))
        return 0

    width = max((len(n) for n in registered), default=9)
    print(f"{'OBJECTIVE':<{width}}  REACH")
    print(f"{'-' * width}  -----")
    for name in registered:
        flag = "REACHABLE" if name in reachable else "unreachable"
        print(f"{name:<{width}}  {flag}")
    n, m = len(registered), len(reachable)
    print()
    print(f"{n} objectives, {m} reachable from the idea engine, "
          f"{n - m} not yet wired")
    return 0


def cmd_native_mind(args: argparse.Namespace) -> int:
    """Show what Apex's native intelligence has LEARNED from this project — the
    reusable return-body idioms it mined from the project's own functions, ranked
    by how often the codebase uses each. Read-only, deterministic, zero-token: it
    reads the same corpus the opt-in ``APEX_NATIVE_MIND`` lane learns from, so the
    report reflects exactly what Apex could transplant onto an unfinished stub."""
    from app.reporting.native_mind_report import (
        finishable_stubs,
        render_experience_markdown,
        render_finishable_stubs_markdown,
        render_native_mind_markdown,
        summarize_native_mind,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    if getattr(args, "experience", False):
        from app.engine.native_proof_memory import decayed_reliability
        reliability = decayed_reliability(target)
        if getattr(args, "json", False):
            print(json.dumps(reliability, indent=2))
            return 0
        print(render_experience_markdown(reliability), end="")
        return 0
    if getattr(args, "stubs", False):
        rows = finishable_stubs(target)
        if getattr(args, "json", False):
            print(json.dumps({"finishable": rows,
                              "native_only": sum(r["native_only"] for r in rows)},
                             indent=2))
            return 0
        print(render_finishable_stubs_markdown(rows), end="")
        return 0
    summary = summarize_native_mind(target, top=getattr(args, "top", 20))
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
        return 0
    print(render_native_mind_markdown(summary), end="")
    return 0


def _read_proof_of_fix(root: Path) -> dict:
    """The proof-of-fix evidence trail, read defensively (missing/corrupt → {}).

    Mirrors the established readers in ``outcomes._last_proof`` /
    ``changelog._fixes_section``: ``.apex/proof-of-fix.json`` is the artifact a
    maintenance pass leaves behind, and a fresh repo simply has none.
    """
    path = root / ".apex" / "proof-of-fix.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_count(value: object, fallback: int) -> int:
    """Coerce a recorded total to int, falling back when not recorded.

    A MISSING key and an explicit null both fall back (they mean "not
    recorded"); a real recorded value wins, defensively coerced.
    """
    if value is None:
        return fallback
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _count_outcome(fixes: list, outcome: str) -> int:
    """How many recorded fixes (dicts only) carry the given ``outcome``."""
    return sum(
        1 for f in fixes
        if isinstance(f, dict) and f.get("outcome") == outcome
    )


def _proof_tally(proof: dict) -> tuple[int, int]:
    """(landed, reverted) from the proof trail: recorded totals win, else count."""
    totals = proof.get("totals") or {}
    fixes = proof.get("fixes") or []
    verified = _count_outcome(fixes, "applied")
    rolled_back = _count_outcome(fixes, "rolled_back")
    landed = _coerce_count(totals.get("applied"), verified) if totals else verified
    reverted = _coerce_count(totals.get("rolled_back"), rolled_back) if totals else rolled_back
    return landed, reverted


def _reliability_table(mem: dict) -> list[dict]:
    """Merge IdeaMemory's reliability views into one deterministically ordered
    table: every tracked fix-type once, best landing rate first, then key."""
    rows = [*(mem.get("most_reliable") or []), *(mem.get("least_reliable") or [])]
    by_key: dict[str, dict] = {}
    for row in rows:
        key = row.get("key", "")
        if key and key not in by_key:
            by_key[key] = {
                "key": key,
                "success_rate": float(row.get("success_rate", 0.0)),
                "samples": int(row.get("samples", 0)),
            }
    return sorted(by_key.values(), key=lambda r: (-r["success_rate"], r["key"]))


def _trackrecord(root: Path) -> dict:
    """Assemble Apex's PROVEN track record on this repo from the two artifacts it
    already keeps: the proof-of-fix evidence trail (what landed, test-verified,
    with auto-rollback) and IdeaMemory's per-fix-type landing rates.

    Deterministic and defensive: both sources read from disk, missing files
    collapse to an empty record, and the per-type table is sorted by
    (success_rate desc, key asc) so the output is byte-stable across runs.
    """
    from app.engine.idea_memory import IdeaMemory

    proof = _read_proof_of_fix(root)
    landed, reverted = _proof_tally(proof)

    mem = IdeaMemory.load(root).summary()
    by_type = _reliability_table(mem)

    has_record = landed > 0 or bool(by_type)
    return {
        "verified_fixes": landed,
        "rolled_back": reverted,
        "operators_tracked": int(mem.get("operators_tracked", 0) or 0),
        "by_type": by_type,
        "generated_at": proof.get("generated_at", ""),
        "has_record": has_record,
    }


_RELIABLE_FLOOR = 0.75   # ≥ this landing rate → lead with it
_RISKY_CEIL = 0.40       # ≤ this → expect blocks / rollbacks


def render_trackrecord_markdown(rec: dict) -> str:
    """The calm, factual, evidence-grounded track-record report."""
    if not rec["has_record"]:
        return ("# Apex track record\n\n"
                "no track record yet — run `apex maintain` to start building one.")

    landed = rec["verified_fixes"]
    reverted = rec["rolled_back"]
    lines = ["# Apex track record", ""]
    fix_word = "fix" if landed == 1 else "fixes"
    lines.append(
        f"Apex has landed **{landed} {fix_word}** on this repo — each one "
        "test-verified, with automatic rollback if the suite went red."
    )
    if reverted:
        rb_word = "attempt" if reverted == 1 else "attempts"
        lines.append(
            f"A further {reverted} {rb_word} were rolled back automatically "
            "rather than left broken — the safety net working as designed."
        )
    lines.append("")

    by_type = rec["by_type"]
    if by_type:
        lines += ["## By fix type", "",
                  "Landing rate per operator, measured on this codebase over "
                  "time (lead with the reliable; expect blocks on the risky):", ""]
        for row in by_type:
            pct = round(row["success_rate"] * 100)
            samples = row["samples"]
            s_word = "sample" if samples == 1 else "samples"
            if row["success_rate"] >= _RELIABLE_FLOOR:
                flag = "reliable — lead with this"
            elif row["success_rate"] <= _RISKY_CEIL:
                flag = "risky — expect blocks/rollbacks"
            else:
                flag = "mixed"
            lines.append(
                f"- `{row['key']}` — {pct}% landed over {samples} {s_word} "
                f"({flag})"
            )
        lines.append("")

    lines.append(
        "_Every number here is read from Apex's own evidence trail "
        "(`.apex/proof-of-fix.json`, `.apex/idea-memory.json`) — deterministic, "
        "zero-token, no model in the loop._"
    )
    return "\n".join(lines)


def cmd_trackrecord(args: argparse.Namespace) -> int:
    """Show Apex's PROVEN track record on this repo — how many fixes it has
    landed (test-verified, auto-rollback) and the per-fix-type landing rates it
    has measured over time. Reads only Apex's own artifacts; LLM-free."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    rec = _trackrecord(target)
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print(render_trackrecord_markdown(rec))
    return 0


# ---------------------------------------------------------------------------
# proof — render the proof-of-fix evidence Apex already computes but never shows
# ("make the proof visible", ROADMAP "Next"). Read-only, LLM-free: it loads,
# formats, and prints existing artifacts and INVENTS no new analysis.
# ---------------------------------------------------------------------------

def _proof_disposition(fix: dict, outcome: str, withheld: bool) -> tuple[str, str]:
    """(display_outcome, committed) for one move's commit disposition.

    An applied-but-WITHHELD fix is on disk for review, NOT committed — surfaced
    as its own state (with the gate that fired) so a reader never mistakes it for
    a committed fix. Blocked/rolled-back never committed either. Honest by
    construction: an unverified/withheld move is never rendered as committed.
    """
    if outcome == "applied" and withheld:
        gate = "fence" if fix.get("fenced") else ("baseline-red" if fix.get("baseline_red") else "")
        return "applied & withheld", (f"no ({gate})" if gate else "no")
    if outcome == "applied":
        return "applied", ("yes" if fix.get("commit_hash") else "no")
    return outcome, "no"


def _proof_reason(fix: dict, outcome: str, withheld: bool) -> str:
    """The one honest reason for a non-clean move — every field already present
    in the record (blocked_reason / rollback.reason / withheld_reason)."""
    if outcome == "blocked":
        return str(fix.get("blocked_reason") or "")
    if outcome == "rolled_back":
        return str((fix.get("rollback") or {}).get("reason") or "")
    if withheld:
        return str(fix.get("withheld_reason") or "")
    return ""


def _proof_move(fix: dict) -> dict:
    """One rendered move-row dict from a stored ``fixes[]`` record.

    Reads only fields ``proof_of_fix._fix_record`` already wrote — the finding,
    the terminal ``outcome``, the coverage level, the commit disposition and the
    one honest reason for a non-clean move. It NEVER upgrades an unverified move
    to look verified: a withheld/rolled-back/blocked move keeps its own outcome
    and reason verbatim.
    """
    finding = fix.get("finding") or {}
    # Coverage is the verification strength level EXACTLY as recorded (a green
    # suite that never touched the module reads "none"/"no-suite"/"baseline-red"
    # — honest evidence, not an implied full-coverage pass).
    strength = (fix.get("verification") or {}).get("strength") or {}
    outcome = str(fix.get("outcome") or "blocked")
    withheld = bool(fix.get("commit_withheld"))
    display_outcome, committed = _proof_disposition(fix, outcome, withheld)
    return {
        "outcome": display_outcome,
        "label": str(finding.get("label") or ""),
        "action": str(finding.get("action") or ""),
        "target": str(finding.get("target") or ""),
        "coverage": str(strength.get("level") or ""),
        "committed": committed,
        "reason": _proof_reason(fix, outcome, withheld),
    }


_PROOF_EMPTY_TRACK = {
    "proofs": 0,
    "fixes": 0,
    "totals": {"applied": 0, "rolled_back": 0, "blocked": 0, "total": 0,
               "reliability": 0.0},
    "by_action": {},
    "by_module": {},
}


def _proof_record(root: Path) -> dict:
    """Assemble the proof-of-fix VISIBILITY record for ``root`` from the two
    artifacts Apex already keeps — the latest proof pointer
    (``.apex/proof-of-fix.json``) and the full proof history (latest + archived
    ``proof-<hash>.json``).

    Reuses the existing defensive loaders (``_read_proof_of_fix``,
    ``proof_history.load_proof_history`` / ``summarise_fix_track_record``) and the
    pure tamper functions (``proof_of_fix.proof_hash`` / ``proof_manifest``); it
    computes NOTHING new. Deterministic — the moves iterate the stored file order,
    the track-record dicts are already sorted, and ``generated_at`` is carried
    verbatim, never regenerated. Never raises: a missing/corrupt proof collapses
    to the honest empty state.
    """
    from app.engine.proof_history import (
        load_proof_history,
        summarise_fix_track_record,
    )
    from app.engine.proof_of_fix import proof_hash, proof_manifest

    proof = _read_proof_of_fix(root)
    history = load_proof_history(root)
    has_proof = bool(proof) or bool(history)
    if not has_proof:
        return {"has_proof": False, "moves": [], "track_record": dict(_PROOF_EMPTY_TRACK)}

    fixes = [f for f in (proof.get("fixes") or []) if isinstance(f, dict)]
    manifest = proof_manifest(proof) if proof else {}
    totals = proof.get("totals") or {}
    return {
        "has_proof": True,
        "objective": str(proof.get("objective") or ""),
        "mode": str(proof.get("mode") or ""),
        "verify": bool(proof.get("verify")),
        "generated_at": str(proof.get("generated_at") or ""),
        "totals": {
            "applied": _coerce_count(totals.get("applied"), 0),
            "rolled_back": _coerce_count(totals.get("rolled_back"), 0),
            "blocked": _coerce_count(totals.get("blocked"), 0),
        },
        # Iterate stored file order — the order apply_plan recorded, reproduced
        # byte-for-byte from the JSON. No sort, no clock.
        "moves": [_proof_move(f) for f in fixes],
        "proof_hash": proof_hash(proof) if proof else "",
        "verdict": str(manifest.get("verdict") or ""),
        "track_record": summarise_fix_track_record(history),
    }


def render_proof_markdown(record: dict) -> str:
    """Render the proof-of-fix VISIBILITY record as Markdown (pure, deterministic).

    Honest empty state (a 3-line message pointing at ``apex maintain``) when no
    proof exists yet; otherwise the objective/mode/verify line, the per-move
    table (Outcome | Finding | Coverage | Committed | Reason) in stored file
    order, the totals, the tamper-evidence line (``proof_hash`` + verdict), and
    the track-record block. Adds no clock and no random; iterates the already
    file-ordered moves and the already-sorted track-record dicts, so the same
    ``.apex/proof-of-fix.json`` renders identical text every run.
    """
    if not record.get("has_proof"):
        return (
            "# Apex proof of fix\n\n"
            "No proof-of-fix evidence yet — run `apex maintain` (or `apex maintain "
            "--dry-run` to preview) to generate one. Apex records every "
            "applied/rolled-back/blocked move with test evidence and a tamper-"
            "evident hash."
        )

    lines = ["# Apex proof of fix", ""]
    objective = record.get("objective") or "—"
    mode = record.get("mode") or "—"
    lines.append(
        f"Objective: {objective}   Mode: {mode}   "
        f"Verify: {'yes' if record.get('verify') else 'no'}"
    )
    lines.append("")

    lines += ["## Moves (this run)", ""]
    lines.append("| Outcome | Finding (label / action / target) | Coverage | Committed | Reason |")
    lines.append("|---------|-----------------------------------|----------|-----------|--------|")
    for move in record.get("moves") or []:
        finding = " / ".join(p for p in (move["label"], move["action"], move["target"]) if p)
        lines.append(
            f"| {_proof_cell(move['outcome'])} | {_proof_cell(finding)} "
            f"| {_proof_cell(move['coverage'])} | {_proof_cell(move['committed'])} "
            f"| {_proof_cell(move['reason'])} |"
        )
    lines.append("")

    totals = record.get("totals") or {}
    lines.append(
        f"Totals: {int(totals.get('applied', 0))} applied, "
        f"{int(totals.get('rolled_back', 0))} rolled back, "
        f"{int(totals.get('blocked', 0))} blocked."
    )
    lines.append("")

    lines += ["## Tamper evidence", ""]
    lines.append(f"proof_hash: {record.get('proof_hash') or '—'}")
    lines.append(f"verdict: {record.get('verdict') or '—'}")
    lines.append("")

    lines += _render_proof_track_record(record.get("track_record") or {})

    lines.append("")
    lines.append(
        "_Every number here is read from Apex's own evidence trail "
        "(`.apex/proof-of-fix.json` + archived proofs) — deterministic, "
        "zero-token, no model in the loop._"
    )
    return "\n".join(lines)


def _proof_cell(text: str) -> str:
    """Neutralize table-breaking chars in one Markdown cell (mirrors
    ``learning_section._escape_cell``: ``|`` → entity, newlines → ``<br>``)."""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = "<br>".join(text.split("\n"))
    return text.replace("|", "&#124;")


def _render_proof_track_record(track: dict) -> list[str]:
    """The '## Track record' block from ``summarise_fix_track_record`` output.

    REUSES the orphaned ``learning_section`` helpers (``_action_row`` /
    ``_percent`` / ``_action_sort_key``) — they already format the by-action
    reliability table, so the By-action rows share that renderer rather than
    duplicating it. The ``by_action``/``by_module`` dicts are already sorted by
    the summariser, so iteration is deterministic.
    """
    # Reuse: learning_section already renders the by-action reliability table
    # (Action | Reliability | Applied | Rolled back | Blocked | Total).
    from app.reporting.learning_section import (
        _action_row,
        _action_sort_key,
        _percent,
    )

    totals = track.get("totals") or {}
    proofs = int(track.get("proofs", 0))
    fixes = int(track.get("fixes", 0))
    lines = ["## Track record (all runs on this repo)", ""]
    lines.append(
        f"Proofs: {proofs}   Fixes: {fixes}   "
        f"Reliability: {_percent(float(totals.get('reliability', 0.0)))}"
    )

    by_action = track.get("by_action") or {}
    if by_action:
        lines += ["", "### By action", "",
                  "| Action | Reliability | Applied | Rolled back | Blocked | Total |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for action, stats in sorted(by_action.items(), key=_action_sort_key):
            lines.append(_action_row(action, stats))

    by_module = track.get("by_module") or {}
    if by_module:
        lines += ["", "### By module", "",
                  "| Module | Reliability | Applied | Rolled back | Blocked | Total |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for module, stats in sorted(by_module.items(), key=_action_sort_key):
            lines.append(_action_row(module, stats))

    return lines


def cmd_agenda(args: argparse.Namespace) -> int:
    """Show the Apex agenda: what this project should do next, in three honest
    lanes — provable-landable now (value-ranked with the project's own learned
    demotes), human-decision (handed over with rationale), and watched (learned
    caution made visible). Pure deterministic synthesis of existing engines;
    recommends only — nothing is written or landed. Always exits 0."""
    from app.engine.agenda import build_agenda, render_agenda_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    agenda = build_agenda(target)
    if args.json:
        print(json.dumps(agenda, sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_agenda_markdown(agenda))
    return 0


def _vault_diff_index(raw: str) -> tuple[int | None, str]:
    """Parse a ``--diff`` value into ``(index, error)``. An empty string means
    "latest" (``index=None``, no error); an unparseable value is reported as
    an honest error string rather than raising."""
    if not raw:
        return None, ""
    try:
        return int(raw), ""
    except ValueError:
        return None, f"`{raw}` is not a valid snapshot index (expected a whole number)"


def _cmd_vault_diff(target: Path, view: dict, raw_diff: str, as_json: bool) -> None:
    """The ``--diff`` seam: print a snapshot-vs-live delta, or an honest note
    plus the current vault (mirrors ``cmd_grade``'s ``--diff`` fallback) when
    the value is unparseable or no matching snapshot exists."""
    from app.memory.vault import render_vault_markdown
    from app.memory.vault_history import (
        available_indices, diff_vault, load_snapshot, render_vault_diff_markdown,
    )

    index, error = _vault_diff_index(raw_diff)
    if not error:
        snapshot = load_snapshot(target, index)
        if snapshot is not None:
            diff = diff_vault(snapshot["view"], view)
            if as_json:
                print(json.dumps({
                    "snapshot_index": snapshot["index"],
                    "snapshot_label": snapshot.get("label", ""),
                    **diff.to_dict(),
                }, sort_keys=True, indent=2, ensure_ascii=False))
            else:
                print(render_vault_diff_markdown(
                    diff, snapshot["index"], snapshot.get("label", "")))
            return
        have = available_indices(target)
        note = f"_No snapshot #{index} found" if index is not None else "_No snapshot saved yet"
        if have:
            note += f" (available: {', '.join(str(i) for i in have)})"
        error = note + " — save one first with `apex vault --save`._"
    print(error + "\n")
    if as_json:
        print(json.dumps(view, sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_vault_markdown(view))


def cmd_vault(args: argparse.Namespace) -> int:
    """Refresh and show the Apex vault: ONE deterministic roll-up of the
    project's persistent memory stores (idea-memory, dream journal, dream
    digest, proof-of-fix + derived track record). Mirrors the live stores
    losslessly into ``.apex/vault/vault.json`` (single-writer, rebuildable);
    absent stores are reported honestly. ``--save [LABEL]`` snapshots the
    current view under ``.apex/vault/snapshots/`` (index-keyed, no clock);
    ``--diff [INDEX]`` shows an honest, deterministic delta between a saved
    snapshot (latest by default) and the live vault. Read-only over every
    source store; LLM-free; always exits 0 (an empty vault, or no snapshot
    yet, is honest state, not an error)."""
    from app.memory.vault import load_vault_view, render_vault_markdown, write_vault

    target = Path(args.target).resolve() if args.target else _get_project_root()
    if args.refresh:
        write_vault(target)
    view = load_vault_view(target)

    diff_arg = getattr(args, "diff", None)
    if diff_arg is not None:
        _cmd_vault_diff(target, view, diff_arg, args.json)
    elif args.json:
        print(json.dumps(view, sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_vault_markdown(view))

    save_arg = getattr(args, "save", None)
    if save_arg is not None:
        from app.memory.vault_history import save_snapshot

        ref = save_snapshot(target, view, label=save_arg)
        label_note = f' ("{ref["label"]}")' if ref["label"] else ""
        print(f"[vault] Snapshot #{ref['index']} saved{label_note} → {ref['path']}")
    return 0


def cmd_proof(args: argparse.Namespace) -> int:
    """Show the proof-of-fix evidence for the last maintain run on this repo:
    each applied/rolled-back/blocked/withheld move with its reason, a tamper-
    evident sha256, and the aggregate track record. Reads only Apex's own
    artifacts; invents no analysis; LLM-free. Always exits 0 (a missing proof is
    honest state, not an error)."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    record = _proof_record(target)
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(render_proof_markdown(record))
    return 0


_SCOPE_EMPTY_REPORT = {
    "source_file_count": 0,
    "python_file_count": 0,
    "analyzed_pct": 100,
    "out_of_scope_pct": 0,
    "all_python": True,
    "language_breakdown": [],
    "unparsed_count": 0,
    "unparsed_files": [],
    "files": [],
}


def _scope_profile(root: Path):
    """Profile ``root`` (light), collapsing any failure to ``None``."""
    from app.tools.project_profile import ProjectProfiler

    try:
        return ProjectProfiler(str(root)).profile(light=True)
    except Exception:
        return None


def _scope_file_entry(fact, test_stems: set) -> dict:
    """One out-of-scope file's dict, flagged ``has_test`` and (only if >0) debt.

    A non-Python file is "tested" when some test file's stem names it — Apex's
    test files are linked by name, so an out-of-scope file with no such mention
    is honestly flagged "no test found". The TODO/FIXME marker count is read
    defensively and ONLY added when > 0, so a no-debt file's dict (and the
    --json shape) stays byte-identical to before this signal existed.
    """
    stem = Path(fact.path).stem
    has_test = stem in test_stems or any(stem in t for t in test_stems)
    entry = {
        "path": fact.path,
        "language": fact.language,
        "loc": fact.loc,
        "churn": fact.churn,
        "has_test": has_test,
    }
    debt = int(getattr(fact, "debt_markers", 0) or 0)
    if debt > 0:
        entry["debt_markers"] = debt
    return entry


def _scope_files(root: Path, profile) -> list[dict]:
    """The largest / most-active out-of-scope file dicts (ranked by the scanner)."""
    from app.tools.polyglot_facts import scan_polyglot_facts

    test_stems = {Path(t).stem for t in getattr(profile, "test_files", []) or []}
    return [_scope_file_entry(f, test_stems) for f in scan_polyglot_facts(str(root))]


def _scope_cross_links(root: Path) -> list[dict]:
    """Cross-language coupling pairs git shows co-changing across the Python
    boundary. Defensive: [] on any git error (all-Python / shallow history)."""
    from app.engine.cross_language_coupling import cross_language_coupling
    return [
        {"py": c.py, "other": c.other, "language": c.other_language,
         "cochanges": c.cochanges}
        for c in cross_language_coupling(str(root))
    ]


def _scope_report(root: Path) -> dict:
    """Assemble Apex's honest analysis-scope report for this repo.

    Grounded entirely in ``ProjectProfiler('.').profile()`` (the scope-accounting
    fields ``analyzed_ratio`` / ``out_of_scope_ratio`` / ``language_breakdown``,
    already computed over the canonical skip-dir walk) and the language-agnostic
    ``scan_polyglot_facts`` (the biggest / most-active non-Python files). Both are
    deterministic and offline; this assembler adds no time/random and never
    crashes — a profile failure collapses to the empty (all-Python) shape.

    Determinism: ``language_breakdown`` is already sorted (count desc, then name)
    by the profiler, and ``scan_polyglot_facts`` ranks by ``(-churn, -loc, path)``.
    The ``has_test`` flag on each out-of-scope file is read from the profile's
    ``test_files`` (a non-Python file is "tested" only if a sibling/test path
    names its stem), so the untested flag tracks the repo, never a guess.
    """
    profile = _scope_profile(root)
    if profile is None or profile.source_file_count <= 0:
        # Empty repo (no source-bearing files at all): nothing to disclose, but
        # the honest answer is still "all of what little there is".
        return dict(_SCOPE_EMPTY_REPORT)

    breakdown = [
        {"language": lang, "files": count}
        for lang, count in profile.language_breakdown.items()
    ]
    # The COMPLETE unanalysed accounting (parse-failures + ``.pyi`` stubs +
    # over-cap files), single-sourced from the profiler. ``unanalyzed_*`` is the
    # canonical name; ``unparsed_*`` is its back-compat alias (same set).
    unparsed_count = int(
        getattr(profile, "unanalyzed_count", None)
        if getattr(profile, "unanalyzed_count", None) is not None
        else getattr(profile, "unparsed_count", 0) or 0
    )
    # Bounded, sorted (the profile already sorts) preview of the dropped files —
    # capped like the other report sections so a repo with hundreds of broken
    # files doesn't dump them all. The count carries the TRUE total.
    unparsed_files = list(
        getattr(profile, "unanalyzed_files", None)
        or getattr(profile, "unparsed_files", []) or []
    )[:5]
    # The reassuring "100% (all Python)" path is honest ONLY when nothing was
    # dropped. A repo that is all-Python yet has a file that failed to parse must
    # NOT take it — there is a real gap to disclose, so fall to the detailed shape.
    all_python = (
        not (profile.out_of_scope_ratio > 0 and profile.language_breakdown)
        and unparsed_count == 0
    )
    # The SCOPE report speaks for what was TRULY analysed. When NOTHING was
    # dropped, the percentages are computed EXACTLY as before (the original
    # ``round(analyzed_ratio * 100)`` / ``round(out_of_scope_ratio * 100)``), so
    # the common all-parseable case is byte-identical down to float rounding —
    # deriving them any other way risks a ``1.0 - x`` rounding shift on a repo
    # like 99.5%. ONLY when files were dropped do we switch to the parse-aware
    # honest ratio (which the raw language ratio cannot express), and there we
    # derive out-of-scope as ``100 - analyzed_pct`` so the two always sum to 100.
    if unparsed_count <= 0:
        analyzed_pct = round(profile.analyzed_ratio * 100)
        out_of_scope_pct = round(profile.out_of_scope_ratio * 100)
    else:
        honest_ratio = getattr(profile, "analyzed_ratio_honest",
                               profile.analyzed_ratio)
        # A real drop exists, so the honest answer is NEVER 100%: one broken file
        # in a 601-file repo is 99.83%, which would round UP to 100 and re-hide
        # the gap. Clamp at 99 when anything was dropped so the disclosed
        # percentage can never silently claim full coverage.
        analyzed_pct = min(round(honest_ratio * 100), 99)
        out_of_scope_pct = 100 - analyzed_pct
    return {
        "source_file_count": profile.source_file_count,
        "python_file_count": profile.python_file_count,
        "analyzed_pct": analyzed_pct,
        "out_of_scope_pct": out_of_scope_pct,
        "all_python": all_python,
        "language_breakdown": breakdown,
        "unparsed_count": unparsed_count,
        "unparsed_files": unparsed_files,
        "files": _scope_files(root, profile),
        "cross_links": _scope_cross_links(root),
    }


def _scope_all_python_lines() -> list[str]:
    """The all-Python reassurance block (header + the two reassurance lines)."""
    return [
        "# Apex analysis scope", "",
        "Apex analyses 100% of this repo (all Python).", "",
        "_Every source-bearing file here is Python — the subset Apex deep-"
        "analyses — so its grade speaks for the whole repo._",
    ]


def _scope_headline_lines(rep: dict) -> list[str]:
    """The header + analysed/out-of-scope ratio sentence.

    Parse-aware: when in-language ``.py`` files were DROPPED because they failed
    to parse, the headline names that gap inline (turning a silent omission into
    a disclosed strength) rather than pretending the percentage is purely a
    language boundary. With no dropped files the clause is absent, so the polyglot
    headline is byte-identical to before.
    """
    sentence = (
        f"Apex analyses {rep['analyzed_pct']}% of this repo (Python). "
        f"{rep['out_of_scope_pct']}% is outside its analysis scope."
    )
    n = int(rep.get("unparsed_count", 0) or 0)
    if n > 0:
        f_word = "file" if n == 1 else "files"
        was_word = "was" if n == 1 else "were"
        sentence += (
            f" {n} Python {f_word} could not be parsed and {was_word} excluded "
            "from analysis."
        )
    return ["# Apex analysis scope", "", sentence, ""]


def _scope_unparsed_lines(rep: dict) -> list[str]:
    """The "could not be parsed" section naming the dropped files ([] when none).

    Bounded (the report already caps the preview) and sorted, like every other
    section. Discloses exactly which in-language files Apex saw but could not
    analyse — so a broken or maliciously-mangled ``.py`` can never hide behind a
    "100% analysed" claim. Additive: empty unless real drops occurred.
    """
    n = int(rep.get("unparsed_count", 0) or 0)
    if n <= 0:
        return []
    names = rep.get("unparsed_files") or []
    f_word = "file" if n == 1 else "files"
    lines = [
        "## Could not be parsed (excluded from analysis)", "",
        f"{n} Python {f_word} failed to parse (syntax error or unreadable "
        "encoding) and {pron} excluded from the structure graph, security scan, "
        "and cycle detection — so the percentage above never counts {pron2} as "
        "analysed:".format(
            pron="was" if n == 1 else "were",
            pron2="it" if n == 1 else "them",
        ),
        "",
    ]
    lines += [f"- `{name}`" for name in names]
    if n > len(names):
        lines.append(f"- … and {n - len(names)} more")
    lines.append("")
    return lines


def _scope_breakdown_lines(breakdown: list) -> list[str]:
    """The out-of-scope language breakdown section ([] when no breakdown)."""
    if not breakdown:
        return []
    lines = ["## Outside analysis scope", "",
             "The non-Python remainder, by language:", ""]
    for row in breakdown:
        n = row["files"]
        f_word = "file" if n == 1 else "files"
        lines.append(f"- {row['language']} — {n} {f_word}")
    lines.append("")
    return lines


def _scope_file_line(f: dict) -> str:
    """One out-of-scope file bullet, with untested flag and optional debt clause."""
    commit_word = "commit" if f["churn"] == 1 else "commits"
    flag = "" if f["has_test"] else " — no test found"
    # Debt clause: additive, ONLY when the file carries >0 TODO/FIXME
    # markers, so a no-debt line stays byte-identical to before.
    debt = f.get("debt_markers", 0) or 0
    debt_clause = f" — {debt} TODO/FIXME" if debt > 0 else ""
    return (
        f"- `{f['path']}` ({f['language']}, {f['loc']} LOC, "
        f"{f['churn']} {commit_word}){flag}{debt_clause}"
    )


def _scope_files_lines(files: list) -> list[str]:
    """The largest / most-active out-of-scope files section ([] when none)."""
    if not files:
        return []
    lines = ["## Largest / most-active out-of-scope files", "",
             "Where the non-Python risk concentrates — Apex can name these "
             "but can't deep-analyse them yet:", ""]
    lines += [_scope_file_line(f) for f in files]
    lines.append("")
    return lines


def _scope_cross_lines(cross: list) -> list[str]:
    """The cross-language coupling section ([] when no cross-links)."""
    if not cross:
        return []
    lines = ["## Cross-language coupling (keep in sync)", "",
             "Files git shows changing together across the Python boundary — "
             "Apex can't deep-analyse the non-Python side, but they move as a "
             "unit, so a change to one likely needs the other:", ""]
    for c in cross:
        cw = "co-change" if c["cochanges"] == 1 else "co-changes"
        lines.append(
            f"- `{c['py']}` ↔ `{c['other']}` ({c['language']}, "
            f"{c['cochanges']} {cw})"
        )
    lines.append("")
    return lines


def render_scope_markdown(rep: dict) -> str:
    """The calm, honest analysis-scope report: what Apex covers and what it
    doesn't. All-Python repo → the "100% (all Python)" reassurance; a polyglot
    repo → the headline ratio, the out-of-scope language breakdown, and the
    biggest / most-active out-of-scope files (untested ones flagged)."""
    if rep["all_python"]:
        return "\n".join(_scope_all_python_lines())

    lines = _scope_headline_lines(rep)
    lines += _scope_unparsed_lines(rep)
    lines += _scope_breakdown_lines(rep["language_breakdown"])
    lines += _scope_files_lines(rep["files"])
    lines += _scope_cross_lines(rep.get("cross_links") or [])
    lines.append(
        "_Apex names its own limits: it grades only Python, and says so. Every "
        "number here is read from its own deterministic profile of this repo — "
        "zero-token, no model in the loop._"
    )
    return "\n".join(lines)


def cmd_scope(args: argparse.Namespace) -> int:
    """Report, honestly, how much of THIS repo Apex's Python-only analysis covers
    and name the biggest out-of-scope files. The trust differentiator over a tool
    that silently grades only Python. Deterministic, stdlib-only, LLM-free."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    rep = _scope_report(target)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(render_scope_markdown(rep))
    return 0


def render_js_scope_markdown(profile: JsProjectProfile) -> str:
    """The JS/TS project-scope report: module/dependency-graph size, the highest
    fan-in hubs, and the untested modules — with the highest-leverage untested hub
    called out. A pure formatter over the profiler's own already-computed fields;
    the JS/TS analog of :func:`render_scope_markdown`. Deterministic, no model."""
    n_mod = len(profile.modules)
    n_test = len(profile.test_files)
    n_edges = len(profile.dependency_edges)
    n_ext = len(profile.external_dependencies)
    lines = [
        "# Apex JS/TS project scope",
        "",
        f"{n_mod} module(s), {n_test} test file(s), {n_edges} internal "
        f"dependency edge(s), {n_ext} external package(s).",
        "",
    ]
    if profile.dependency_hubs:
        lines += ["## Dependency hubs (highest fan-in)", ""]
        for m in profile.dependency_hubs:
            lines.append(f"- `{m}` (fan-in {profile.module_fanin.get(m, 0)})")
        lines.append("")
    if profile.untested_modules:
        shown = profile.untested_modules[:5]
        lines += [
            f"## Untested modules ({profile.untested_count} total, "
            f"top {len(shown)} shown)",
            "",
        ]
        for m in shown:
            lines.append(f"- `{m}`")
        lines.append("")
    if profile.hub_untested_modules:
        top = profile.hub_untested_modules[0]
        lines += [
            "## Highest-leverage gap: untested hub",
            "",
            f"`{top['module']}` has fan-in {top['fan_in']} and no linked test — "
            "the single highest-leverage place to spend your next hour.",
            "",
        ]
    lines.append(
        "_Every number here is read from Apex's own deterministic JS/TS profile of "
        "this project — zero-token, no model in the loop._"
    )
    return "\n".join(lines)


def cmd_js_scope(args: argparse.Namespace) -> int:
    """Report the JS/TS side of a project the way ``apex scope``/``apex hotspots``
    do for Python: the module/dependency graph, the highest fan-in hubs, and the
    untested modules (the untested hub is the highest-leverage gap). Deterministic,
    LLM-free. Honest empty: a project with no JS/TS says so."""
    import dataclasses

    from app.tools.js_project_profile import profile_js_project

    target = Path(args.target).resolve() if args.target else _get_project_root()
    profile = profile_js_project(target)
    if args.json:
        print(json.dumps(dataclasses.asdict(profile), indent=2))
    elif not profile.modules:
        print("No JS/TS project detected at this root.")
    else:
        print(render_js_scope_markdown(profile))
    return 0


def register_parsers(subparsers) -> None:
    """Register the insight family's subcommands: quickstart, grade, impact,
    brief, dream, outcomes, recipes, changelog, explain, objectives."""
    # quickstart — the 60-second on-ramp: health + top opportunities + what's
    # safely landable right now, composed from existing engines, read-only
    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="60-second on-ramp: health grade, top opportunities, and what "
             "Apex can safely land right now — one read-only command",
    )
    quickstart_parser.add_argument("--target", default="", help="Target project root")
    quickstart_parser.add_argument("--json", action="store_true", help="Emit JSON")
    quickstart_parser.set_defaults(func=cmd_quickstart)

    # grade — single project health grade (A-F)
    grade_parser = subparsers.add_parser(
        "grade", help="Give the project a single health grade (A-F) with a breakdown",
    )
    grade_parser.add_argument("--target", default="", help="Target project root")
    grade_parser.add_argument("--min-score", type=int, default=0, dest="min_score",
                              help="Exit non-zero if the score is below this (CI gate)")
    grade_parser.add_argument("--save", action="store_true",
                              help="Snapshot the current grade to .apex/grade-snapshot.json")
    grade_parser.add_argument("--diff", action="store_true",
                              help="Compare to the saved snapshot and show what improved")
    grade_parser.add_argument("--json", action="store_true", help="Emit JSON")
    grade_parser.set_defaults(func=cmd_grade)

    # impact — function-level blast radius (who calls this, transitively)
    impact_parser = subparsers.add_parser(
        "impact",
        help="Show the blast radius of changing a function (its transitive callers)",
    )
    impact_parser.add_argument("function", help="Function/method name to analyze")
    impact_parser.add_argument("--target", default="", help="Target project root")
    impact_parser.add_argument("--json", action="store_true", help="Emit JSON")
    impact_parser.set_defaults(func=cmd_impact)

    # duplication — find copy-pasted code blocks across the project
    dup_parser = subparsers.add_parser(
        "duplication",
        help="Find copy-pasted code blocks across the project (extract shared helpers)",
    )
    dup_parser.add_argument("--target", default="", help="Target project root")
    dup_parser.add_argument("--min-statements", type=int, default=5, dest="min_statements",
                            help="Minimum block size (statements) to report (default 5)")
    dup_parser.add_argument("--json", action="store_true", help="Emit JSON")
    dup_parser.set_defaults(func=cmd_duplication)

    # mutants — mutation testing: how strong is the suite for one module?
    mutants_parser = subparsers.add_parser(
        "mutants",
        help="Mutation testing: seed faults into a module and report how many the suite kills",
    )
    mutants_parser.add_argument("--module", required=True,
                                help="Module to mutate, relative to the project root (e.g. app/foo.py)")
    mutants_parser.add_argument("--target", default="", help="Target project root")
    mutants_parser.add_argument("--max-mutants", type=int, default=30, dest="max_mutants",
                                help="Cap the number of mutants verified (cost control)")
    mutants_parser.add_argument("--timeout", type=int, default=120,
                                help="Per-mutant pytest timeout in seconds")
    mutants_parser.add_argument("--json", action="store_true", help="Emit JSON")
    mutants_parser.set_defaults(func=cmd_mutants)

    # immune — proactively find the suite's blind spots and (with --apply) land
    # mutant-killing assertions there via the strengthen-tests engine
    immune_parser = subparsers.add_parser(
        "immune",
        help="Immune posture: where the suite is blindest (fast, read-only); "
             "--apply lands mutant-killing tests via strengthen-tests",
    )
    immune_parser.add_argument("--target", default="", help="Target project root")
    immune_parser.add_argument("--top", type=int, default=20,
                               help="How many highest-risk modules to show (default 20)")
    immune_parser.add_argument(
        "--apply", action="store_true",
        help="Run a proactive immune sweep: land mutant-killing assertions on the "
             "most-fragile modules (strengthen-tests, suite-verified, auto-rollback)")
    immune_parser.add_argument("--max-modules", type=int, default=0, dest="max_modules",
                               help="With --apply: cap modules to immunise (default 3)")
    immune_parser.add_argument("--json", action="store_true", help="Emit JSON")
    immune_parser.set_defaults(func=cmd_immune)

    # manifesto — the architectural laws Apex has learned on this project
    manifesto_parser = subparsers.add_parser(
        "manifesto",
        help="The project's living constitution: the AVOID / FRAGILE / TRUST / "
             "proven-idiom laws Apex learned from its proof-carrying experience",
    )
    manifesto_parser.add_argument("--target", default="", help="Target project root")
    manifesto_parser.add_argument("--json", action="store_true", help="Emit JSON")
    manifesto_parser.set_defaults(func=cmd_manifesto)

    # brief — a design-level idea as an actionable engineering brief
    brief_parser = subparsers.add_parser(
        "brief",
        help="Turn a design-level idea into an actionable work brief (facts, plan, done-when)",
    )
    brief_parser.add_argument("branch", nargs="?", default="",
                              help="Branch path (default: the top design-level idea)")
    brief_parser.add_argument("--target", default="", help="Target project root")
    brief_parser.add_argument("--subject", default="",
                              help="Target by MODULE PATH (stable across runs, "
                                   "unlike branch paths — prefer this with --save)")
    brief_parser.add_argument("--objective", default="", help="Optional focus")
    brief_parser.add_argument("--depth", type=int, default=2)
    brief_parser.add_argument("--breadth", type=int, default=4)
    brief_parser.add_argument("--max-ideas", type=int, default=40, dest="max_ideas")
    brief_parser.add_argument("--save", action="store_true",
                              help="Snapshot the brief's evidence baseline for --check")
    brief_parser.add_argument("--check", action="store_true",
                              help="Re-measure a saved brief: evidence gone = item resolved")
    brief_parser.add_argument("--develop", action="store_true",
                              help="Run the brief's evidenced concerns as verified develop "
                                   "campaigns, then re-measure the burndown")
    brief_parser.add_argument("--apply", action="store_true",
                              help="With --develop: actually land the moves (default: dry run)")
    brief_parser.add_argument("--max-steps", type=int, default=25, dest="max_steps",
                              help="With --develop: cap moves per objective")
    brief_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                              help="With --develop: skip the per-move suite gate (faster, unsafe)")
    brief_parser.add_argument("--json", action="store_true", help="Emit JSON")
    brief_parser.set_defaults(func=cmd_brief)

    # dream — scheduled curation over Apex's own memory stores
    dream_parser = subparsers.add_parser(
        "dream",
        help="Review memory stores, extract patterns, curate, and write the dream digest",
    )
    dream_parser.add_argument("--target", default="", help="Target project root")
    dream_parser.add_argument("--curate", action="store_true",
                              help="Apply the curation (default only reports; inputs untouched)")
    dream_parser.add_argument("--learn-gates", action="store_true", dest="learn_gates",
                              help="Tighten the promote gate for confluence keys whose past "
                                   "promotions never realized a held-and-verified fix "
                                   "(tighten-only; default off, byte-identical)")
    dream_parser.add_argument("--land", action="store_true",
                              help="Run the overnight LANDING CHAIN: value-led concrete "
                                   "objectives, scoped to the dream's confluences, each "
                                   "verified-with-rollback (default dry run)")
    dream_parser.add_argument("--apply", action="store_true",
                              help="With --land: actually write the verified moves (default: dry run)")
    dream_parser.add_argument("--fast", action="store_true",
                              help="With --land: scope each per-move gate to the changed module")
    dream_parser.add_argument("--preview", action="store_true",
                              help="With --land: a fast bounded preview — cap to the top confluence "
                                   "modules by centrality and skip the un-previewable mutation "
                                   "objective (disclosed, never silent). Dry-run answer in seconds")
    dream_parser.add_argument("--max-modules", type=int, default=None, dest="max_modules",
                              help="With --land: cap the confluence scope to the top-N modules by "
                                   "fan-in centrality. UNLIKE --preview this is NOT apply-gated — "
                                   "with --apply it genuinely lands fewer confluences, not just "
                                   "previews fewer")
    dream_parser.add_argument("--value-ranked", action="store_true", dest="value_ranked",
                              help="With --land: order the confluence scope by value (highest-leverage "
                                   "modules first) instead of the default alphabetical order")
    dream_parser.add_argument("--json", action="store_true", help="Emit JSON")
    dream_parser.set_defaults(func=cmd_dream)

    # intelligence — unified Apex Intelligence report (research organs in one view)
    intel_parser = subparsers.add_parser(
        "intelligence",
        help="Unified Apex Intelligence: anomalies, validated discoveries, "
             "emerging hotspots, proposed fix-rules, self-assessment",
    )
    intel_parser.add_argument("--target", default="", help="Target project root")
    intel_parser.set_defaults(func=cmd_intelligence)

    # polyglot — non-Python risk surface (TS/JS/YAML/HTML/shell)
    poly_parser = subparsers.add_parser(
        "polyglot",
        help="Non-Python risk: TS/JS/YAML/HTML/shell hotspots + high-confidence findings",
    )
    poly_parser.add_argument("--target", default="", help="Target project root")
    poly_parser.add_argument("--json", action="store_true", help="Emit JSON")
    poly_parser.set_defaults(func=cmd_polyglot)

    # readiness — honest fixer-vs-linter actionability ratio + scope coverage
    ready_parser = subparsers.add_parser(
        "readiness",
        help="Honest real-world readiness: auto-fixable vs flag-only ratio + scope",
    )
    ready_parser.add_argument("--target", default="", help="Target project root")
    ready_parser.set_defaults(func=cmd_readiness)

    # fix-risk — learned rollback-risk of planned fixes (proof history + counterfactual)
    fixrisk_parser = subparsers.add_parser(
        "fix-risk",
        help="Learned fix-risk: rollback likelihood of planned fixes from proof history",
    )
    fixrisk_parser.add_argument("--target", default="", help="Target project root")
    fixrisk_parser.add_argument("--explain", action="store_true",
                                help="Per-signal risk breakdown for one --action/--module candidate")
    fixrisk_parser.add_argument("--action", default="",
                                help="Action type to explain (with --explain)")
    fixrisk_parser.add_argument("--module", default="",
                                help="Module/target to explain, relative to the project root (with --explain)")
    fixrisk_parser.set_defaults(func=cmd_fixrisk)

    # discoveries — ranked leads fused from the anomaly/temporal/rule engines
    disc_parser = subparsers.add_parser(
        "discoveries",
        help="Ranked discovery leads: anomaly + temporal + rule-synthesis, fused",
    )
    disc_parser.add_argument("--target", default="", help="Target project root")
    disc_parser.set_defaults(func=cmd_discoveries)

    # outcomes — grade the project against a user-written rubric (CI gate)
    outcomes_parser = subparsers.add_parser(
        "outcomes",
        help="Verify the project against YOUR rubric — per-criterion gaps, CI-ready exit code",
    )
    outcomes_parser.add_argument("--target", default="", help="Target project root")
    outcomes_parser.add_argument("--init", action="store_true",
                                 help="Write a starter rubric to .apex/outcomes.json")
    outcomes_parser.add_argument("--json", action="store_true", help="Emit JSON")
    outcomes_parser.set_defaults(func=cmd_outcomes)

    # recipes — the named, composable transform catalog
    recipes_parser = subparsers.add_parser(
        "recipes",
        help="List the transform catalog as named, composable recipes",
    )
    recipes_parser.add_argument("--json", action="store_true", help="Emit JSON")
    recipes_parser.set_defaults(func=cmd_recipes)

    # changelog — release notes from evidence
    changelog_parser = subparsers.add_parser(
        "changelog",
        help="Release notes from artifacts: commits, verified fixes, landed roadmap work, the grade",
    )
    changelog_parser.add_argument("--target", default="", help="Target project root")
    changelog_parser.add_argument("--out", default="", help="Write the Markdown to this path")
    changelog_parser.set_defaults(func=cmd_changelog)

    # objectives — the develop catalog and its idea-engine reachability
    objectives_parser = subparsers.add_parser(
        "objectives",
        help="List registered develop objectives and which the idea engine can reach",
    )
    objectives_parser.add_argument("--json", action="store_true", help="Emit JSON")
    objectives_parser.set_defaults(func=cmd_objectives)

    # native-mind — what the native intelligence has learned from this project
    native_mind_parser = subparsers.add_parser(
        "native-mind",
        help="Show the return-body idioms Apex's native intelligence learned from "
             "this project's own code (the opt-in APEX_NATIVE_MIND corpus)",
    )
    native_mind_parser.add_argument("--target", default="", help="Target project root")
    native_mind_parser.add_argument("--top", type=int, default=20,
                                    help="How many dominant idioms to show (default 20)")
    native_mind_parser.add_argument(
        "--stubs", action="store_true",
        help="Dry-run: which of THIS project's unfinished stubs the native lane "
             "could finish (flagging the native-only wins), no writes")
    native_mind_parser.add_argument(
        "--experience", action="store_true",
        help="Show the idiom shapes the native lane has PROVEN it can land here, "
             "recency-weighted (the learned experience it ranks by)")
    native_mind_parser.add_argument("--json", action="store_true", help="Emit JSON")
    native_mind_parser.set_defaults(func=cmd_native_mind)

    # trackrecord — Apex's proven, test-verified fix history on THIS repo
    trackrecord_parser = subparsers.add_parser(
        "trackrecord",
        help="Show Apex's proven track record on this repo: fixes landed (test-verified, "
             "auto-rollback) and per-fix-type landing rates over time",
    )
    trackrecord_parser.add_argument("--target", default="", help="Target project root")
    trackrecord_parser.add_argument("--json", action="store_true", help="Emit JSON")
    trackrecord_parser.set_defaults(func=cmd_trackrecord)

    # proof — render the proof-of-fix evidence Apex already computes (make it visible)
    proof_parser = subparsers.add_parser(
        "proof",
        help="Show the proof-of-fix evidence for the last maintain run: each "
             "applied/rolled-back/blocked/withheld move with reasons, a tamper-"
             "evident sha256, and the track record (read-only, LLM-free)",
    )
    proof_parser.add_argument("--target", default="", help="Target project root")
    proof_parser.add_argument("--json", action="store_true", help="Emit JSON")
    proof_parser.set_defaults(func=cmd_proof)

    # vault — one deterministic roll-up of the project's persistent memory
    vault_parser = subparsers.add_parser(
        "vault",
        help="Show (and --refresh) the Apex vault: one deterministic roll-up "
             "of the project's persistent memory stores — idea-memory, dream "
             "journal/digest, proof-of-fix + derived track record (read-only "
             "over the sources, LLM-free)",
    )
    vault_parser.add_argument("--target", default="", help="Target project root")
    vault_parser.add_argument("--json", action="store_true", help="Emit JSON")
    vault_parser.add_argument(
        "--refresh", action="store_true",
        help="Rewrite .apex/vault/vault.json from the live stores first "
             "(byte-identical when nothing changed)")
    vault_parser.add_argument(
        "--save", nargs="?", const="", default=None, metavar="LABEL",
        help="Snapshot the current vault under .apex/vault/snapshots/ "
             "(monotonic index, no wall-clock; optional LABEL travels with it)")
    vault_parser.add_argument(
        "--diff", nargs="?", const="", default=None, metavar="INDEX",
        help="Show an honest, deterministic delta between a saved snapshot "
             "(latest by default, or snapshot INDEX) and the live vault")
    vault_parser.set_defaults(func=cmd_vault)

    # agenda — what should this project do next (three honest lanes)
    agenda_parser = subparsers.add_parser(
        "agenda",
        help="Show what this project should do next in three honest lanes: "
             "provable-landable now (value-ranked), human-decision (with "
             "rationale), watched (learned caution). Deterministic synthesis "
             "of existing engines; recommends only, writes nothing",
    )
    agenda_parser.add_argument("--target", default="", help="Target project root")
    agenda_parser.add_argument("--json", action="store_true", help="Emit JSON")
    agenda_parser.set_defaults(func=cmd_agenda)

    # scope — how much of THIS repo Apex's Python analysis covers (and what it
    # honestly leaves outside that scope)
    scope_parser = subparsers.add_parser(
        "scope",
        help="Report honestly how much of this repo Apex analyses (Python) and "
             "name the biggest out-of-scope files",
    )
    scope_parser.add_argument("--target", default="", help="Target project root")
    scope_parser.add_argument("--json", action="store_true", help="Emit JSON")
    scope_parser.set_defaults(func=cmd_scope)

    # js-scope — the JS/TS analog of `apex scope`/`apex hotspots` (module graph,
    # dependency hubs, untested modules) for the non-Python half of a stack
    js_scope_parser = subparsers.add_parser(
        "js-scope",
        help="Report the JS/TS module graph, dependency hubs, and untested modules "
             "(the JS/TS analog of `apex scope`/`apex hotspots`)",
    )
    js_scope_parser.add_argument("--target", default="", help="Target project root")
    js_scope_parser.add_argument("--json", action="store_true", help="Emit JSON")
    js_scope_parser.set_defaults(func=cmd_js_scope)

    # explain — show why an idea scored what it did
    explain_parser = subparsers.add_parser(
        "explain",
        help="Explain why an idea scored what it did (provenance, score, ROI, caveats)",
    )
    explain_parser.add_argument("branch", nargs="?", default="",
                                help="Branch path to explain (e.g. x.a.c); default: the top idea")
    explain_parser.add_argument("--target", default="", help="Target project root")
    explain_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    explain_parser.add_argument("--depth", type=int, default=2, help="Permutation depth")
    explain_parser.add_argument("--breadth", type=int, default=4, help="Operators per idea")
    explain_parser.add_argument("--max-ideas", type=int, default=40, dest="max_ideas",
                                help="Idea budget")
    explain_parser.add_argument("--facets", action="store_true",
                                help="Include fractal facet ideas (for facet branch paths)")
    explain_parser.add_argument("--json", action="store_true", help="Emit JSON")
    explain_parser.set_defaults(func=cmd_explain)
