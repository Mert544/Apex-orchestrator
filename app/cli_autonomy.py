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

def cmd_maintain(args: argparse.Namespace) -> int:
    """One-shot maintenance: scan -> ideate -> apply -> verify -> commit -> report."""
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.engine.idea_action_bridge import (
        IdeaActionBridge,
        render_maintenance_markdown,
    )
    from app.plugins.registry import PluginRegistry

    target = Path(args.target).resolve() if args.target else _get_project_root()
    plugins = PluginRegistry()
    plugins.load_all()

    report = IdeaPermutationEngine(
        config={"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
                "breadth": args.breadth},
        project_root=str(target),
        extra_operators=plugins.idea_operators(),
    ).run(objective=args.objective or None)

    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(report, mode=args.mode, top=(args.top or None), project_root=str(target))

    # Dry-run: preview the diffs without touching anything.
    if getattr(args, "dry_run", False):
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
        return 0

    summary = bridge.apply_plan(
        plan, str(target), mode=args.mode,
        verify=not args.no_verify,
        max_apply=(args.max_apply or None) if args.max_apply else None,
        commit=args.commit,
    )
    from app.engine.idea_memory import IdeaMemory

    IdeaMemory.learn_from(summary, str(target))  # learn from this run's outcomes
    md = render_maintenance_markdown(summary, str(target), objective=args.objective or "")

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(md)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n[maintain] Report written to {out_path}")
    # Proof-of-fix: the auditable evidence record for everything this pass did.
    if summary.get("results"):
        from app.engine.proof_of_fix import build_proof, write_proof

        proof = build_proof(summary, str(target), objective=args.objective or "")
        proof_path = write_proof(proof, str(target), out=getattr(args, "proof", "") or None)
        if not args.json:
            print(f"\n[maintain] Proof-of-fix evidence written to {proof_path}")
    return 0



def cmd_auto(args: argparse.Namespace) -> int:
    """One autonomous command — no flags to memorize.

    Assesses the project, decides what matters most (via the roadmap), and either
    recommends the best next moves (default, no changes) or, with ``--apply``,
    safely applies the test-verified, auto-rolled-back fixes in roadmap order.
    An optional natural-language goal focuses the ideas and can hint the mode.
    """
    from app.engine.idea_action_bridge import (
        IdeaActionBridge,
        render_maintenance_markdown,
    )
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.engine.idea_roadmap import RoadmapSynthesizer
    from app.engine.idea_tree_shape import analyze_tree_shape
    from app.plugins.registry import PluginRegistry

    target = Path(args.target).resolve() if args.target else _get_project_root()
    goal = (getattr(args, "goal", "") or "").strip()
    explicit_apply = getattr(args, "apply", False)
    explicit_recommend = getattr(args, "recommend", False)

    # An explicit --mode (or one inferred from the goal) is honored; otherwise
    # the AutonomyPolicy picks the mode based on what's safe to do.
    explicit_mode = getattr(args, "mode", None)
    if not explicit_mode and goal:
        try:
            from app.intent.parser import IntentParser

            explicit_mode = IntentParser().parse(goal).mode
        except Exception:
            explicit_mode = None

    plugins = PluginRegistry()
    plugins.load_all()
    report = IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
        project_root=str(target),
        extra_operators=plugins.idea_operators(),
    ).run(objective=goal or None)
    roadmap = RoadmapSynthesizer().build(report)
    shape = analyze_tree_shape(report)

    # Best-effort security headline (a failing scanner must not break auto).
    # Split project code from example/fixture code with the same predicate the
    # grade uses, so auto and grade tell one consistent story: demo fixtures
    # carry intentional vulnerabilities and must not inflate the headline.
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

    # --- Narrative: the state of the project ---------------------------------
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
    # What the engine has learned about this project from past runs.
    try:
        from app.engine.idea_memory import IdeaMemory

        mem = IdeaMemory.load(str(target)).summary()
        if mem.get("most_reliable"):
            best = mem["most_reliable"][0]
            lines.append(
                f"_What I've learned here: `{best['key']}` fixes land "
                f"{int(best['success_rate'] * 100)}% of the time "
                f"({best['samples']} samples) — I weight that in._\n"
            )
    except Exception:
        pass
    emit_json = getattr(args, "json", False)
    if not emit_json:
        print("\n".join(lines))

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

    # --- Recommend: never touch the tree -------------------------------------
    if not decision.act:
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

    # --- Act: roadmap-ordered, verified, capped for safety -------------------
    plan = bridge.plan_roadmap(report, mode=mode, project_root=str(target), draft=True)
    summary = bridge.apply_plan(
        plan, str(target), mode=mode,
        verify=not getattr(args, "no_verify", False),
        max_apply=(getattr(args, "max_apply", 0) or 8),
        commit=commit,
    )
    from app.engine.idea_memory import IdeaMemory

    IdeaMemory.learn_from(summary, str(target))  # the engine gets wiser each run
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


