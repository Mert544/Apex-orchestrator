"""Autonomy-family commands: maintain, auto, evolve, simulate.

Extracted from the 1900-line `app/cli.py` monolith — the engine's own #1
convergence target (central dependency hub × high churn). Pure mechanical
move: `app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
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
    """Dry-run: preview the diffs without touching anything."""
    preview = bridge.dry_run_plan(plan, str(target))
    if args.json:
        print(json.dumps(preview, indent=2))
        return
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


def _maintain_apply(args, engine, bridge, plan, target) -> int:
    """Apply the plan (verified, guarded), then learn, record, report, prove."""
    from app.engine.idea_action_bridge import render_maintenance_markdown
    from app.engine.idea_memory import IdeaMemory
    from app.engine.signal_trends import SignalTrends

    avoid = _maintain_avoid_signatures(args, target)
    apply_kwargs = {"avoid_signatures": avoid} if avoid is not None else {}
    summary = bridge.apply_plan(
        plan, str(target), mode=args.mode,
        verify=not args.no_verify,
        max_apply=(args.max_apply or None) if args.max_apply else None,
        commit=args.commit,
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


def _auto_recommend(args, target, goal, shape, roadmap, sec_n,
                    executable, decision, emit_json) -> int:
    """The recommend path: never touch the tree, report what could be applied."""
    if emit_json:
        print(json.dumps({
            "target": str(target), "goal": goal, "ideas": shape.total_ideas,
            "modules": shape.distinct_subjects, "security_findings": sec_n,
            "observations": shape.observations,
            "quick_wins": [{"title": i.title, "roi": i.roi} for i in roadmap.quick_wins],
            "applicable": executable, "applied": False, "decision": decision.to_dict(),
        }, indent=2))
        return 0
    print(f"_Apex chose not to apply automatically: {decision.reason}._\n")
    print(
        f"I can safely apply **{executable}** of these (test-verified, "
        "auto-rolled-back). When you're ready:\n\n"
        "  • Apply now:            apex auto --apply\n"
        "  • Preview as diffs:     apex maintain --dry-run\n"
        "  • See the full roadmap: apex ideate --roadmap"
    )
    return 0


def _auto_act(args, target, goal, bridge, engine, report, mode,
              commit, decision, emit_json) -> int:
    """The act path: roadmap-ordered, verified, capped guarded apply + report."""
    from app.engine.idea_action_bridge import render_maintenance_markdown

    plan = bridge.plan_roadmap(report, mode=mode, project_root=str(target), draft=True)
    summary = bridge.apply_plan(
        plan, str(target), mode=mode,
        verify=not getattr(args, "no_verify", False),
        max_apply=(getattr(args, "max_apply", 0) or 8),
        commit=commit,
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
        if proof_path is not None:
            print(f"\n_Proof-of-fix evidence written to `{proof_path}`._")
        if not commit:
            print("\n_Applied to your working tree, not committed — "
                  "review with `git diff`, undo with `git checkout -- .`_")
    if getattr(args, "out", ""):
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n[auto] Report written to {out_path}")
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    """One autonomous command — no flags to memorize.

    Assesses the project, decides what matters most (via the roadmap), and either
    recommends the best next moves (default, no changes) or, with ``--apply``,
    safely applies the test-verified, auto-rolled-back fixes in roadmap order.
    An optional natural-language goal focuses the ideas and can hint the mode.
    """
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
    engine = IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
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

    # How many safe, executable fixes are available, and is the tree clean?
    scout = bridge.plan_roadmap(report, mode="report", project_root=str(target))
    executable = scout.stats.get("executable_steps", 0)
    tree_clean = _working_tree_clean(target)

    # Apex decides — autonomously — whether to act or recommend.
    from app.policies.autonomy_policy import AutonomyPolicy

    decision = AutonomyPolicy().decide(
        executable_steps=executable,
        working_tree_clean=tree_clean,
        explicit_apply=explicit_apply,
        explicit_recommend=explicit_recommend,
        commit=commit,
    )
    mode = explicit_mode or decision.mode
    if decision.act and mode == "report":
        mode = "supervised"  # acting requires a patch-capable mode

    if not decision.act:
        return _auto_recommend(args, target, goal, shape, roadmap, sec_n,
                               executable, decision, emit_json)
    return _auto_act(args, target, goal, bridge, engine, report, mode,
                     commit, decision, emit_json)



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
    loop = EvolutionLoop(
        project_root=str(target),
        mode=mode,
        max_cycles=getattr(args, "max_cycles", 3),
        max_apply_per_cycle=getattr(args, "max_apply", 5) or 5,
        verify=not getattr(args, "no_verify", False),
        commit=getattr(args, "commit", False),
        objective=getattr(args, "objective", "") or None,
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


def _develop_goal(args, target, goal, max_steps, verify, apply) -> int:
    """`apex develop --goal`: pursue a high-level goal that fractally decomposes."""
    from app.engine.fractal_develop import compile_goal, render_goal_markdown

    gr = compile_goal(str(target), goal, max_steps=max_steps, verify=verify, apply=apply)
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


def _develop_from_dream(args, target, objective, max_steps, verify, apply) -> int:
    """`apex develop --from-dream`: scope the campaign to dream-flagged confluences."""
    from app.engine.objective_compiler import (
        compile_from_dream, dream_confluence_modules, render_from_dream_markdown,
    )

    modules = dream_confluence_modules(str(target))
    results = compile_from_dream(str(target), objective=objective,
                                 max_steps=max_steps, verify=verify, apply=apply)
    if args.json:
        print(json.dumps({"modules": modules,
                          "campaigns": [r.to_dict() for r in results]}, indent=2))
    else:
        print(render_from_dream_markdown(results, modules))
        if apply and any(r.steps for r in results):
            print(_APPLIED_TREE_NOTE)
    return 0


def _develop_objective(args, target, objective, grade_before, max_steps, verify, apply) -> int:
    """`apex develop` default: compose verified transforms toward one objective metric."""
    from app.engine.objective_compiler import compile_objective, render_compile_markdown

    result = compile_objective(
        str(target), objective=objective, max_steps=max_steps,
        verify=verify, apply=apply, scope_verify=getattr(args, "fast", False),
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

    if getattr(args, "playbook", False):
        return _develop_playbook(args, target)
    if getattr(args, "history", False):
        return _develop_history(args, target)
    if getattr(args, "top", False):
        return _develop_top(args, target)

    want_grade = getattr(args, "grade", False)
    grade_before = _grade_score(str(target)) if want_grade else None

    goal = getattr(args, "goal", "") or ""
    if goal:
        return _develop_goal(args, target, goal, max_steps, verify, apply)
    if getattr(args, "all_objectives", False):
        return _develop_all(args, target, grade_before, max_steps, verify, apply)
    if getattr(args, "from_dream", False):
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
    """Run just the generated test file; True when it passes."""
    import subprocess
    try:
        r = subprocess.run(["python", "-m", "pytest", "-q", "-x", test_path],
                           cwd=target, capture_output=True, timeout=timeout)
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
    rankings = rank_objectives(str(target), restrict)
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
        scope_verify=getattr(args, "fast", False))
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
        help="Force-apply the safe, test-verified fixes (overrides the autonomy gate)",
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
    auto_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                             help="Skip test verification (not recommended)")
    auto_parser.add_argument("--max-apply", type=int, default=0, dest="max_apply",
                             help="Cap how many fixes to apply (default 8)")
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
    develop_parser.add_argument("--target", default="", help="Target project root")
    develop_parser.add_argument("--objective", default="dead-params",
                                help="Objective to pursue (default: dead-params)")
    develop_parser.add_argument("--goal", default="",
                                help="Pursue a high-level GOAL that fractally decomposes into "
                                     "objectives (e.g. reduce-debt, tidy, simplify-structure)")
    develop_parser.add_argument("--all", action="store_true", dest="all_objectives",
                                help="Sweep EVERY objective in order (modernize, dead-params, "
                                     "shrink-functions, inline-helpers) — clean everything")
    develop_parser.add_argument("--grade", action="store_true",
                                help="Measure the health grade before and after — prove the gain")
    develop_parser.add_argument("--history", action="store_true",
                                help="Show the development trajectory (every graded campaign's gain)")
    develop_parser.add_argument("--from-dream", action="store_true", dest="from_dream",
                                help="Scope the campaign to the modules the nightly "
                                     "dream flagged as confluences (dream → action)")
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
    maintain_parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    maintain_parser.add_argument("--out", default="", help="Write the Markdown report to this path")
    maintain_parser.add_argument(
        "--proof", default="",
        help="Where to write the proof-of-fix evidence JSON "
             "(default: .apex/proof-of-fix.json in the target)",
    )
    maintain_parser.set_defaults(func=cmd_maintain)
