#!/usr/bin/env python3
"""Apex Orchestrator CLI.

Usage:
    python -m app.cli scan --plan=project_scan --target=/path/to/project
    python -m app.cli plugin install <name_or_url>
    python -m app.cli plugin list
    python -m app.cli plugin uninstall <name>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path



from app.cli_autonomy import (  # noqa: F401  (re-exports: import surface unchanged)
    _working_tree_clean,
    cmd_auto,
    cmd_evolve,
    cmd_maintain,
    cmd_simulate,
)
from app.cli_common import _get_project_root  # noqa: F401  (re-export)
from app.cli_ops import (  # noqa: F401  (re-exports: import surface unchanged)
    cmd_agents,
    cmd_consensus,
    cmd_daemon,
    cmd_fix_coverage,
    cmd_fix_docstrings,
    cmd_lsp,
    cmd_metrics,
    cmd_scan,
    cmd_self_audit,
)
from app.cli_reporting import (  # noqa: F401  (re-exports: import surface unchanged)
    cmd_city,
    cmd_dashboard,
    cmd_deadcode,
    cmd_debug,
    cmd_fractal,
    cmd_hotspots,
    cmd_report,
)
from app.cli_plugins import (  # noqa: F401  (re-exports: import surface unchanged)
    cmd_hook,
    cmd_marketplace,
    cmd_plugin_install,
    cmd_plugin_list,
    cmd_plugin_uninstall,
)
from app.cli_ideate import cmd_ideate  # noqa: F401  (re-export)
from app.cli_review import (  # noqa: F401  (re-exports: import surface unchanged)
    _apply_review_fixes,
    _render_review_fixes_markdown,
    cmd_review,
)
from app.cli_refactor import cmd_move, cmd_rename  # noqa: F401  (re-exports)


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


def cmd_brief(args: argparse.Namespace) -> int:
    """A design-level idea rendered as an actionable engineering brief.

    ``--save`` snapshots the brief's evidence baseline; ``--check`` re-measures
    a saved brief against the CURRENT code — evidenced items whose evidence
    vanished are resolved by the scan, not by a checkbox (the burndown).
    """
    from app.engine.idea_brief import (
        build_brief,
        check_brief,
        render_brief_markdown,
        render_check_markdown,
        save_brief,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    branch = getattr(args, "branch", "") or ""

    if getattr(args, "check", False):
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

    from app.engine.idea_permutation import IdeaPermutationEngine

    report = IdeaPermutationEngine(
        {"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
         "breadth": args.breadth},
        project_root=str(target),
    ).run(objective=args.objective or None)
    brief = build_brief(report, branch_path=branch)
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


def cmd_dream(args: argparse.Namespace) -> int:
    """Review the organism's memory stores, extract patterns, curate, digest."""
    from app.engine.dream import dream, render_dream_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    report = dream(str(target), curate=getattr(args, "curate", False))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_dream_markdown(report))
        if report.digest_path:
            print(f"[dream] Digest written to {report.digest_path}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    """Give the project a single health grade (A–F) with a breakdown."""
    from app.engine.health_score import grade, render_grade_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    h = grade(str(target))
    if args.json:
        print(json.dumps(h.to_dict(), indent=2))
    else:
        print(render_grade_markdown(h))
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


def cmd_bench(args: argparse.Namespace) -> int:
    """Grade pinned external codebases with the same rubric (calibration)."""
    from app.benchmarking.external import load_manifest, render_bench_markdown, run_bench

    manifest = Path(args.manifest) if args.manifest else (
        _get_project_root() / "docs" / "bench" / "manifest.json")
    if not manifest.exists():
        print(f"⛔ manifest not found: {manifest}")
        return 1
    results = run_bench(load_manifest(manifest), keep=getattr(args, "keep", False))
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(render_bench_markdown(results, manifest_path=str(manifest)))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_bench_markdown(results, manifest_path=str(manifest)),
                            encoding="utf-8")
        print(f"[bench] Report written to {out_path}")
    return 1 if any(r.error for r in results) else 0


def cmd_run(args: argparse.Namespace) -> int:
    from app.intent.parser import IntentParser
    from app.automation.planner import AutonomousPlanner

    target = Path(args.target).resolve() if args.target else _get_project_root()
    intent_parser = IntentParser()
    intent = intent_parser.parse(args.goal, explicit_mode=args.mode)

    planner = AutonomousPlanner()
    plan = planner.build_plan(intent)

    print("\n=== APEX ORCHESTRATOR — AUTONOMOUS RUN ===")
    print(f"Goal: {intent.goal}")
    print(f"Plan: {plan.plan_name}")
    print(f"Steps: {len(plan.steps)}")
    print(f"Agents: {', '.join(plan.agents) if plan.agents else 'all available'}")
    print(f"Mode: {plan.mode}")
    print(f"Can patch: {plan.can_patch}")
    print(f"Fallback: {plan.fallback_plan}")
    print(f"Rationale: {plan.rationale}")
    print()

    os.environ["EPISTEMIC_TARGET_ROOT"] = str(target)
    os.environ["EPISTEMIC_AUTOMATION_PLAN"] = plan.plan_name
    os.environ["EPISTEMIC_OBJECTIVE"] = intent.goal
    if args.fractal:
        os.environ["APEX_USE_FRACTAL"] = "1"
    if args.auto_patch is not None:
        os.environ["APEX_AUTO_PATCH"] = "1" if args.auto_patch else "0"
    if args.auto_commit is not None:
        os.environ["APEX_AUTO_COMMIT"] = "1" if args.auto_commit else "0"
    if args.max_fractal_budget is not None:
        os.environ["APEX_MAX_FRACTAL_BUDGET"] = str(args.max_fractal_budget)
    if args.safety_policy is not None:
        os.environ["APEX_SAFETY_POLICY"] = args.safety_policy
    if args.dry_run:
        os.environ["APEX_DRY_RUN"] = "1"
    if args.mode is not None:
        os.environ["APEX_MODE"] = args.mode

    if plan.mode == "supervised":
        print(
            "[supervised mode] Running with human oversight. Patches will be staged, not committed."
        )

    if plan.mode == "autonomous":
        print(
            "[autonomous mode] Full automation enabled. Changes will be applied automatically."
        )

    if plan.mode == "report":
        print("[report mode] Scanning only. No files will be modified.")

    from app.main import main

    main()

    # Auto-fractal summary for security/audit goals
    if any(kw in intent.goal.lower() for kw in ("security", "audit", "risk", "vuln")):
        print("\n=== AUTO-FRACTAL SUMMARY ===")
        from app.agents.fractal_agents import FractalSecurityAgent

        agent = FractalSecurityAgent()
        result = agent.run(project_root=str(target), max_depth=3)
        from app.reporting.composer import ReportComposer

        composer = ReportComposer([result])
        summary = composer.to_markdown()
        print(summary[:1500])  # Print first 1500 chars to avoid flooding
        if len(summary) > 1500:
            print("\n... (truncated) Use `apex report` for full output.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="apex", description="Apex Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command")

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

    # grade — single project health grade (A-F)
    grade_parser = subparsers.add_parser(
        "grade", help="Give the project a single health grade (A-F) with a breakdown",
    )
    grade_parser.add_argument("--target", default="", help="Target project root")
    grade_parser.add_argument("--min-score", type=int, default=0, dest="min_score",
                              help="Exit non-zero if the score is below this (CI gate)")
    grade_parser.add_argument("--json", action="store_true", help="Emit JSON")
    grade_parser.set_defaults(func=cmd_grade)

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

    # impact — function-level blast radius (who calls this, transitively)
    impact_parser = subparsers.add_parser(
        "impact",
        help="Show the blast radius of changing a function (its transitive callers)",
    )
    impact_parser.add_argument("function", help="Function/method name to analyze")
    impact_parser.add_argument("--target", default="", help="Target project root")
    impact_parser.add_argument("--json", action="store_true", help="Emit JSON")
    impact_parser.set_defaults(func=cmd_impact)

    # review — diff-scoped code review (Apex as a PR reviewer)
    review_parser = subparsers.add_parser(
        "review",
        help="Review only the lines changed since a base ref (security/bugs/style/docs)",
    )
    review_parser.add_argument("--target", default="", help="Target project root")
    review_parser.add_argument("--base", default="HEAD", help="Git base ref to diff against")
    review_parser.add_argument("--fail-on-high", action="store_true", dest="fail_on_high",
                              help="Exit non-zero if a high-severity issue is in the diff (CI)")
    review_parser.add_argument("--sarif", default="",
                               help="Write findings as SARIF 2.1.0 to this path "
                                    "(GitHub code scanning compatible)")
    review_parser.add_argument("--fix", action="store_true",
                              help="Apply the auto-fixable findings on the changed files (test-verified)")
    review_parser.add_argument("--json", action="store_true", help="Emit JSON")
    review_parser.set_defaults(func=cmd_review)

    # rename — cross-file rename (definition + imports + call sites), verified
    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a top-level function/class across the whole project (test-verified)",
    )
    rename_parser.add_argument("old", help="Current symbol name")
    rename_parser.add_argument("new", help="New symbol name")
    rename_parser.add_argument("--param", default="",
                               help="Rename a PARAMETER of this function instead "
                                    "(def site + body + keyword call sites)")
    rename_parser.add_argument("--target", default="", help="Target project root")
    rename_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                               help="Preview the unified diff without changing files")
    rename_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                               help="Skip the test verification run")
    rename_parser.add_argument("--json", action="store_true", help="Emit JSON")
    rename_parser.set_defaults(func=cmd_rename)

    # move — move/rename a module across the project (imports rewritten), verified
    move_parser = subparsers.add_parser(
        "move",
        help="Move/rename a module; every import in the project is rewritten (test-verified)",
    )
    move_parser.add_argument("src", help="Current module path (e.g. app/old.py)")
    move_parser.add_argument("dst", help="New module path (e.g. app/sub/new.py)")
    move_parser.add_argument("--target", default="", help="Target project root")
    move_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                             help="Preview the unified diff without changing files")
    move_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                             help="Skip the test verification run")
    move_parser.add_argument("--json", action="store_true", help="Emit JSON")
    move_parser.set_defaults(func=cmd_move)

    # bench — grade pinned external codebases (calibration, reproducible)
    bench_parser = subparsers.add_parser(
        "bench",
        help="Grade pinned external repos with the same rubric — calibration for the grade",
    )
    bench_parser.add_argument("--manifest", default="",
                              help="Manifest JSON (default: docs/bench/manifest.json)")
    bench_parser.add_argument("--out", default="", help="Write the Markdown report to this path")
    bench_parser.add_argument("--keep", action="store_true",
                              help="Keep the cloned working directories")
    bench_parser.add_argument("--json", action="store_true", help="Emit JSON")
    bench_parser.set_defaults(func=cmd_bench)

    # brief — a design-level idea as an actionable engineering brief
    brief_parser = subparsers.add_parser(
        "brief",
        help="Turn a design-level idea into an actionable work brief (facts, plan, done-when)",
    )
    brief_parser.add_argument("branch", nargs="?", default="",
                              help="Branch path (default: the top design-level idea)")
    brief_parser.add_argument("--target", default="", help="Target project root")
    brief_parser.add_argument("--objective", default="", help="Optional focus")
    brief_parser.add_argument("--depth", type=int, default=2)
    brief_parser.add_argument("--breadth", type=int, default=4)
    brief_parser.add_argument("--max-ideas", type=int, default=40, dest="max_ideas")
    brief_parser.add_argument("--save", action="store_true",
                              help="Snapshot the brief's evidence baseline for --check")
    brief_parser.add_argument("--check", action="store_true",
                              help="Re-measure a saved brief: evidence gone = item resolved")
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
    dream_parser.add_argument("--json", action="store_true", help="Emit JSON")
    dream_parser.set_defaults(func=cmd_dream)

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

    # scan
    scan_parser = subparsers.add_parser("scan", help="Run an automation plan")
    scan_parser.add_argument(
        "--plan", default="project_scan", help="Automation plan name"
    )
    scan_parser.add_argument("--target", default="", help="Target project root")
    scan_parser.add_argument("--focus-branch", default="", help="Focus branch path")
    scan_parser.add_argument("--objective", default="", help="Scan objective")
    scan_parser.add_argument(
        "--auto-patch",
        type=lambda x: x.lower() in ("1", "true", "yes"),
        default=None,
        help="Enable automatic patching",
    )
    scan_parser.add_argument(
        "--auto-commit",
        type=lambda x: x.lower() in ("1", "true", "yes"),
        default=None,
        help="Enable automatic commit",
    )
    scan_parser.add_argument(
        "--max-fractal-budget",
        type=int,
        default=None,
        help="Max fractal analysis budget",
    )
    scan_parser.add_argument(
        "--safety-policy",
        default=None,
        choices=["minimal", "standard", "strict"],
        help="Safety policy level",
    )
    scan_parser.add_argument(
        "--mode",
        default=None,
        choices=["report", "supervised", "autonomous"],
        help="Execution mode (report/supervised/autonomous)",
    )
    scan_parser.set_defaults(func=cmd_scan)

    # agents
    agents_parser = subparsers.add_parser("agents", help="Run helper agents")
    agents_parser.add_argument(
        "agent_type",
        choices=["security", "docstring", "test-stub", "dependency"],
        help="Agent type",
    )
    agents_parser.add_argument("--target", default="", help="Target project root")
    agents_parser.add_argument(
        "--patch", action="store_true", help="Apply patches (docstring agent)"
    )
    agents_parser.add_argument(
        "--generate", action="store_true", help="Generate stubs (test-stub agent)"
    )
    agents_parser.set_defaults(func=cmd_agents)

    # consensus
    consensus_parser = subparsers.add_parser(
        "consensus", help="Evaluate claims via agent consensus"
    )
    consensus_parser.add_argument(
        "--claims", required=True, help="Semicolon-separated claims to evaluate"
    )
    consensus_parser.add_argument(
        "--strategy",
        default="majority",
        choices=["unanimous", "majority", "supermajority", "weighted", "threshold"],
        help="Consensus strategy",
    )
    consensus_parser.add_argument(
        "--quorum", type=int, default=2, help="Minimum votes required"
    )
    consensus_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    consensus_parser.add_argument(
        "--use-memory",
        action="store_true",
        help="Enable persistent agent memory for caching and learning",
    )
    consensus_parser.set_defaults(func=cmd_consensus)

    # plugin
    plugin_parser = subparsers.add_parser("plugin", help="Manage plugins")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_cmd")

    install_parser = plugin_sub.add_parser("install", help="Install a plugin")
    install_parser.add_argument("name", help="Plugin name or URL")
    install_parser.set_defaults(func=cmd_plugin_install)

    list_parser = plugin_sub.add_parser("list", help="List installed plugins")
    list_parser.set_defaults(func=cmd_plugin_list)

    uninstall_parser = plugin_sub.add_parser("uninstall", help="Uninstall a plugin")
    uninstall_parser.add_argument("name", help="Plugin name")
    uninstall_parser.set_defaults(func=cmd_plugin_uninstall)

    # run (autonomous intent-based)
    run_parser = subparsers.add_parser(
        "run", help="Run Apex autonomously based on a natural-language goal"
    )
    run_parser.add_argument(
        "--goal",
        required=True,
        help="Natural-language goal, e.g. 'security audit', 'fix docstrings'",
    )
    run_parser.add_argument("--target", default="", help="Target project root")
    run_parser.add_argument(
        "--mode",
        default="supervised",
        choices=["report", "supervised", "autonomous"],
        help="Execution mode",
    )
    run_parser.add_argument(
        "--fractal",
        action="store_true",
        help="Enable fractal 5-Whys deep analysis on all findings",
    )
    run_parser.add_argument(
        "--auto-patch",
        type=lambda x: x.lower() in ("1", "true", "yes"),
        default=None,
        help="Enable automatic patching (overrides mode default)",
    )
    run_parser.add_argument(
        "--auto-commit",
        type=lambda x: x.lower() in ("1", "true", "yes"),
        default=None,
        help="Enable automatic commit (overrides mode default)",
    )
    run_parser.add_argument(
        "--max-fractal-budget",
        type=int,
        default=None,
        help="Max fractal analysis budget (default 10)",
    )
    run_parser.add_argument(
        "--safety-policy",
        default=None,
        choices=["minimal", "standard", "strict"],
        help="Safety policy level",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode (validate only, no file changes)",
    )
    run_parser.set_defaults(func=cmd_run)

    # daemon
    daemon_parser = subparsers.add_parser(
        "daemon", help="Run Apex periodically in the background"
    )
    daemon_parser.add_argument(
        "action", choices=["start", "stop", "status"], help="Daemon action"
    )
    daemon_parser.add_argument(
        "--goal", default="scan project", help="Goal to run periodically"
    )
    daemon_parser.add_argument(
        "--interval", type=int, default=3600, help="Interval in seconds"
    )
    daemon_parser.add_argument("--target", default="", help="Target project root")
    daemon_parser.add_argument(
        "--mode",
        default="report",
        choices=["report", "supervised", "autonomous"],
        help="Execution mode for daemon runs",
    )
    daemon_parser.add_argument(
        "--legacy", action="store_true",
        help="Use the older goal-driven `apex run` each cycle instead of autonomous `apex auto`",
    )
    daemon_parser.set_defaults(func=cmd_daemon)

    # fractal
    fractal_parser = subparsers.add_parser(
        "fractal", help="Fractal deep analysis tools"
    )
    fractal_sub = fractal_parser.add_subparsers(dest="subcommand")

    fractal_analyze_parser = fractal_sub.add_parser(
        "analyze", help="Analyze project with fractal 5-Whys depth"
    )
    fractal_analyze_parser.add_argument(
        "--target", default="", help="Target project root"
    )
    fractal_analyze_parser.add_argument(
        "--depth", type=int, default=5, help="Max fractal depth (1-5)"
    )
    fractal_analyze_parser.add_argument(
        "--json", action="store_true", help="Output raw JSON"
    )
    fractal_analyze_parser.add_argument(
        "--max-fractal-budget",
        type=int,
        default=None,
        help="Max fractal analysis budget (default 10)",
    )
    fractal_analyze_parser.set_defaults(func=cmd_fractal)

    fractal_tree_parser = fractal_sub.add_parser(
        "tree", help="Render fractal tree for a single finding"
    )
    fractal_tree_parser.add_argument(
        "--finding",
        required=True,
        help='JSON finding, e.g. {"issue":"eval()","file":"a.py"}',
    )
    fractal_tree_parser.add_argument(
        "--depth", type=int, default=5, help="Max fractal depth (1-5)"
    )
    fractal_tree_parser.set_defaults(func=cmd_fractal)

    # report
    report_parser = subparsers.add_parser(
        "report", help="Generate report from run results"
    )
    report_parser.add_argument(
        "--input", required=True, help="Input JSON file from a previous run"
    )
    report_parser.add_argument(
        "--format",
        default="markdown",
        choices=["markdown", "html", "sarif"],
        help="Output format",
    )
    report_parser.add_argument("--output", required=True, help="Output file path")
    report_parser.set_defaults(func=cmd_report)

    # self-audit
    self_audit_parser = subparsers.add_parser("self-audit", help="Run Apex self-audit on its own codebase")
    self_audit_parser.add_argument("--target", default=".", help="Target project root")
    self_audit_parser.add_argument("--format", default="markdown", choices=["markdown", "json"], help="Output format")
    self_audit_parser.set_defaults(func=cmd_self_audit)

    # fix-docstrings
    fix_doc_parser = subparsers.add_parser("fix-docstrings", help="Auto-fix missing docstrings")
    fix_doc_parser.add_argument("--target", default=".", help="Target project root")
    fix_doc_parser.add_argument("--dry-run", action="store_true", help="Show gaps without patching")
    fix_doc_parser.set_defaults(func=cmd_fix_docstrings)

    # fix-coverage
    fix_cov_parser = subparsers.add_parser("fix-coverage", help="Auto-generate test stubs")
    fix_cov_parser.add_argument("--target", default=".", help="Target project root")
    fix_cov_parser.add_argument("--generate", action="store_true", help="Generate test files")
    fix_cov_parser.set_defaults(func=cmd_fix_coverage)

    # lsp
    lsp_parser = subparsers.add_parser("lsp", help="Start LSP language server (stdio)")
    lsp_parser.set_defaults(func=cmd_lsp)

    # metrics
    metrics_parser = subparsers.add_parser("metrics", help="Start Prometheus metrics endpoint")
    metrics_parser.add_argument("--port", type=int, default=9090, help="Metrics endpoint port")
    metrics_parser.set_defaults(func=cmd_metrics)

    # marketplace
    marketplace_parser = subparsers.add_parser("marketplace", help="Start plugin marketplace server")
    marketplace_parser.add_argument("--port", type=int, default=8765, help="Marketplace server port")
    marketplace_parser.add_argument("--plugin-dir", default="plugins", help="Plugin directory")
    marketplace_parser.set_defaults(func=cmd_marketplace)

    # ideate
    ideate_parser = subparsers.add_parser(
        "ideate",
        help="Generate a permutation tree of development ideas from the codebase",
    )
    ideate_parser.add_argument("--target", default="", help="Target project root")
    ideate_parser.add_argument(
        "--objective", default="", help="Optional theme to focus ideas on"
    )
    ideate_parser.add_argument("--depth", type=int, default=2, help="Permutation depth")
    ideate_parser.add_argument(
        "--breadth", type=int, default=4, help="Operators applied per idea"
    )
    ideate_parser.add_argument(
        "--max-ideas", type=int, default=40, dest="max_ideas", help="Idea budget"
    )
    ideate_parser.add_argument(
        "--min-relevance",
        type=float,
        default=0.0,
        dest="min_relevance",
        help="Drop ideas below this relevance to the objective (0=off)",
    )
    ideate_parser.add_argument(
        "--actions",
        action="store_true",
        help="Bridge ideas into a supervised, never-applied action plan",
    )
    ideate_parser.add_argument(
        "--top", type=int, default=0, help="Limit action plan to top-N ideas by value"
    )
    ideate_parser.add_argument(
        "--draft",
        action="store_true",
        help="Draft real patch previews for executable steps (never applied)",
    )
    ideate_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply executable steps — gated by mode + safety gates (opt-in)",
    )
    ideate_parser.add_argument(
        "--verify",
        action="store_true",
        help="After applying, run tests and auto-rollback any step that breaks them",
    )
    ideate_parser.add_argument(
        "--commit",
        action="store_true",
        help="Auto-commit each applied step (autonomous mode only)",
    )
    ideate_parser.add_argument(
        "--max-apply",
        type=int,
        default=0,
        dest="max_apply",
        help="Cap how many steps a maintenance run applies (0 = no cap)",
    )
    ideate_parser.add_argument(
        "--mode",
        default="supervised",
        choices=["report", "supervised", "autonomous"],
        help="Execution mode for --apply (report cannot patch)",
    )
    ideate_parser.add_argument(
        "--mermaid", action="store_true", help="Also emit a Mermaid diagram"
    )
    ideate_parser.add_argument("--json", action="store_true", help="Emit JSON")
    ideate_parser.add_argument("--out", default="", help="Write markdown to this path")
    ideate_parser.add_argument(
        "--kind",
        default="",
        choices=["", "all", "permutation", "synthesis", "pair"],
        help="List only ideas of this kind (value-sorted)",
    )
    ideate_parser.add_argument(
        "--roadmap",
        action="store_true",
        help="Sequence ideas into a prioritized roadmap (Stabilize→Secure→Evolve→Refine)",
    )
    ideate_parser.add_argument(
        "--facets",
        action="store_true",
        help="Fractal zoom: expand the strongest leaves into self-similar sub-ideas",
    )
    ideate_parser.add_argument(
        "--facet-depth",
        type=int,
        default=1,
        dest="facet_depth",
        help="How many self-similar facet zoom levels to recurse (with --facets)",
    )
    ideate_parser.add_argument(
        "--shape",
        action="store_true",
        help="Analyze the shape/health of the generated idea tree",
    )
    ideate_parser.add_argument(
        "--pareto",
        action="store_true",
        help="Show the efficient frontier: non-dominated ideas across impact/effort/value",
    )
    ideate_parser.add_argument(
        "--adaptive",
        action="store_true",
        help="Adaptive depth: let high-value branches grow deeper (value-guided fractal)",
    )
    ideate_parser.add_argument(
        "--sequence",
        action="store_true",
        help="Dependency-ordered execution plan (prerequisites first) + critical path",
    )
    ideate_parser.add_argument(
        "--budget", type=float, default=0.0,
        help="Optimal idea portfolio for this effort budget (impact-maximizing knapsack)",
    )
    ideate_parser.add_argument(
        "--invest", action="store_true",
        help="Investment curve: impact achievable per effort budget + diminishing-returns knee",
    )
    ideate_parser.add_argument(
        "--phase",
        default="",
        choices=["", "Stabilize", "Secure", "Evolve", "Refine"],
        help="With --roadmap --actions: restrict the action plan to one phase",
    )
    ideate_parser.add_argument(
        "--save",
        action="store_true",
        help="With --roadmap: snapshot the roadmap to .apex/roadmap-snapshot.json",
    )
    ideate_parser.add_argument(
        "--diff",
        action="store_true",
        help="With --roadmap: show what changed since the last saved snapshot",
    )
    ideate_parser.set_defaults(func=cmd_ideate)

    # dashboard
    dash_parser = subparsers.add_parser(
        "dashboard", help="Generate a self-contained HTML project dashboard"
    )
    dash_parser.add_argument("--target", default="", help="Target project root")
    dash_parser.add_argument("--objective", default="", help="Optional theme to focus ideas on")
    dash_parser.add_argument("--depth", type=int, default=2, help="Idea permutation depth")
    dash_parser.add_argument("--breadth", type=int, default=3, help="Operators per idea")
    dash_parser.add_argument("--max-ideas", type=int, default=24, dest="max_ideas", help="Idea budget")
    dash_parser.add_argument("--out", default="", help="Output HTML path (default <target>/.apex/dashboard.html)")
    dash_parser.set_defaults(func=cmd_dashboard)

    # hotspots — rank modules by complexity × blast-radius ÷ tests
    hot_parser = subparsers.add_parser(
        "hotspots", help="Rank the modules most worth attention (complexity × fan-in ÷ tests)"
    )
    hot_parser.add_argument("--target", default="", help="Target project root")
    hot_parser.add_argument("--limit", type=int, default=15, help="How many hotspots to show")
    hot_parser.add_argument("--json", action="store_true", help="Emit JSON")
    hot_parser.set_defaults(func=cmd_hotspots)

    # deadcode — cross-file: symbols defined but referenced nowhere
    dead_parser = subparsers.add_parser(
        "deadcode", help="Report module-level symbols defined but never referenced (cross-file)"
    )
    dead_parser.add_argument("--target", default="", help="Target project root")
    dead_parser.add_argument("--limit", type=int, default=40, help="How many to show")
    dead_parser.add_argument("--json", action="store_true", help="Emit JSON")
    dead_parser.set_defaults(func=cmd_deadcode)

    # city — 3D "company city": modules as buildings, Apex agents as walking workers
    city_parser = subparsers.add_parser(
        "city", help="Generate the 3D company-city dashboard (modules as buildings, agents as workers)"
    )
    city_parser.add_argument("--target", default="", help="Target project root")
    city_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    city_parser.add_argument("--out", default="", help="Output HTML path (default <target>/.apex/city.html)")
    city_parser.set_defaults(func=cmd_city)

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
    maintain_parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    maintain_parser.add_argument("--out", default="", help="Write the Markdown report to this path")
    maintain_parser.add_argument(
        "--proof", default="",
        help="Where to write the proof-of-fix evidence JSON "
             "(default: .apex/proof-of-fix.json in the target)",
    )
    maintain_parser.set_defaults(func=cmd_maintain)

    # debug
    debug_parser = subparsers.add_parser(
        "debug", help="Trace a run or analyze a traceback via the debug subsystem"
    )
    debug_sub = debug_parser.add_subparsers(dest="subcommand")

    dbg_trace = debug_sub.add_parser(
        "trace", help="Run with debug tracing; write a .apex/debug report"
    )
    dbg_trace.add_argument("--target", default="", help="Target project root")
    dbg_trace.add_argument("--json", action="store_true", help="Emit JSON")
    dbg_trace.set_defaults(func=cmd_debug)

    dbg_analyze = debug_sub.add_parser(
        "analyze", help="Diagnose a traceback (from --trace file or stdin)"
    )
    dbg_analyze.add_argument("--target", default="", help="Target project root")
    dbg_analyze.add_argument("--trace", default="-", help="Traceback file, or - for stdin")
    dbg_analyze.add_argument("--file", default="", help="Optional source file to scan")
    dbg_analyze.add_argument("--json", action="store_true", help="Emit JSON")
    dbg_analyze.set_defaults(func=cmd_debug)

    # hook
    hook_parser = subparsers.add_parser("hook", help="Manage git hooks")
    hook_parser.add_argument(
        "action", choices=["install", "uninstall"], help="Hook action"
    )
    hook_parser.add_argument("--target", default="", help="Target project root")
    hook_parser.set_defaults(func=cmd_hook)

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    # No subcommand: run the autonomous review on the current project (safe,
    # recommend-only). Users shouldn't have to memorize commands — `apex` alone
    # tells you the state of your project and the best next moves.
    return cmd_auto(argparse.Namespace(
        goal="", target="", apply=False, recommend=False, mode=None, commit=False,
        no_verify=False, max_apply=0, json=False, out="",
    ))


if __name__ == "__main__":
    sys.exit(main())
