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

    engine = IdeaPermutationEngine(
        config={"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
                "breadth": args.breadth},
        project_root=str(target),
        extra_operators=plugins.idea_operators(),
    )
    report = engine.run(objective=args.objective or None)

    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(report, mode=args.mode, top=(args.top or None), project_root=str(target))

    # --recipe: scope the pass to one named intent (typo fails loudly).
    recipe = getattr(args, "recipe", "") or ""
    if recipe:
        from app.execution.recipes import filter_plan

        try:
            remaining = filter_plan(plan, recipe)
        except ValueError as exc:
            print(f"⛔ {exc}")
            return 1
        print(f"[maintain] scoped to recipe `{recipe}` — "
              f"{remaining} executable step(s) in scope")

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
    from app.engine.signal_trends import SignalTrends

    SignalTrends(str(target)).record(engine.last_profile)  # trend baseline
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
    engine = IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
        project_root=str(target),
        extra_operators=plugins.idea_operators(),
    )
    report = engine.run(objective=goal or None)
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
        from app.engine.composition_archive import (
            CompositionArchive, render_playbook_markdown,
        )

        archive = CompositionArchive.load(str(target))
        if args.json:
            print(json.dumps(archive.to_dict(), indent=2))
        else:
            print(render_playbook_markdown(archive))
        return 0

    if getattr(args, "history", False):
        from app.engine.dev_history import DevHistory, render_history_markdown

        history = DevHistory.load(str(target))
        if args.json:
            print(json.dumps(history.to_dict(), indent=2))
        else:
            print(render_history_markdown(history))
        return 0

    want_grade = getattr(args, "grade", False)
    grade_before = _grade_score(str(target)) if want_grade else None

    if getattr(args, "all_objectives", False):
        from app.engine.objective_compiler import compile_all, render_all_markdown

        results = compile_all(str(target), max_steps=max_steps, verify=verify, apply=apply)
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print(render_all_markdown(results))
            if apply and any(r.steps for r in results):
                print("_Applied to your working tree, not committed — "
                      "review with `git diff`._")
        _print_grade_proof(str(target), grade_before, apply and any(r.steps for r in results),
                           objective="all", moves=sum(len(r.steps) for r in results))
        return 0

    if getattr(args, "from_dream", False):
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
                print("_Applied to your working tree, not committed — "
                      "review with `git diff`._")
        return 0

    from app.engine.objective_compiler import compile_objective, render_compile_markdown

    result = compile_objective(
        str(target), objective=objective, max_steps=max_steps,
        verify=verify, apply=apply,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_compile_markdown(result))
        if result.applied and result.steps:
            print("_Applied to your working tree, not committed — "
                  "review with `git diff`._")
    _print_grade_proof(str(target), grade_before, result.applied and bool(result.steps),
                       objective=objective, moves=len(result.steps))
    # Non-zero only when an explicitly named objective is unknown (a usage error).
    return 1 if (result.blocked and not result.steps
                 and any("unknown objective" in b for b in result.blocked)) else 0


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


def register_parsers(subparsers) -> None:
    """Register the autonomy family's subcommands: auto, simulate, evolve, maintain."""
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
    develop_parser.add_argument("--apply", action="store_true",
                                help="Apply the composed moves (default: dry run)")
    develop_parser.add_argument("--max-steps", type=int, default=25, dest="max_steps",
                                help="Maximum moves to compose (default 25)")
    develop_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                                help="Skip the per-move test verification (not recommended)")
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
    maintain_parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    maintain_parser.add_argument("--out", default="", help="Write the Markdown report to this path")
    maintain_parser.add_argument(
        "--proof", default="",
        help="Where to write the proof-of-fix evidence JSON "
             "(default: .apex/proof-of-fix.json in the target)",
    )
    maintain_parser.set_defaults(func=cmd_maintain)
