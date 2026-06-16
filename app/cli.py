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
    cmd_develop,
    cmd_evolve,
    cmd_maintain,
    cmd_shield,
    cmd_simulate,
)
from app.cli_common import _get_project_root  # noqa: F401  (re-export)
from app.cli_insight import (  # noqa: F401  (re-exports: import surface unchanged)
    cmd_brief,
    cmd_changelog,
    cmd_dream,
    cmd_duplication,
    cmd_explain,
    cmd_grade,
    cmd_impact,
    cmd_mutants,
    cmd_objectives,
    cmd_outcomes,
    cmd_recipes,
    cmd_scope,
    cmd_trackrecord,
)
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
    cmd_deps,
    cmd_fractal,
    cmd_gate,
    cmd_hotspots,
    cmd_pulse,
    cmd_report,
)
from app.cli_viz import (  # noqa: F401  (re-exports: import surface unchanged)
    cmd_canvas,
    cmd_changed,
    cmd_idea_html,
    cmd_partition,
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
from app.cli_refactor import cmd_extract, cmd_inline, cmd_move, cmd_rename, cmd_rewrite, cmd_signature, cmd_teach  # noqa: F401  (re-exports)


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


def _run_print_plan(intent, plan) -> None:
    """Echo the planned autonomous run header to stdout."""
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


def _run_set_env(args: argparse.Namespace, target: Path, intent, plan) -> None:
    """Export the EPISTEMIC_*/APEX_* environment knobs the run reads."""
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


def _run_mode_message(plan) -> None:
    """Print the one-line oversight note matching the resolved plan mode."""
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


def _run_fractal_summary(intent, target: Path) -> None:
    """Emit an auto-fractal security digest when the goal is risk-flavored."""
    # Auto-fractal summary for security/audit goals
    if not any(kw in intent.goal.lower() for kw in ("security", "audit", "risk", "vuln")):
        return
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


def cmd_run(args: argparse.Namespace) -> int:
    from app.intent.parser import IntentParser
    from app.automation.planner import AutonomousPlanner

    target = Path(args.target).resolve() if args.target else _get_project_root()
    intent_parser = IntentParser()
    intent = intent_parser.parse(args.goal, explicit_mode=args.mode)

    planner = AutonomousPlanner()
    plan = planner.build_plan(intent)

    _run_print_plan(intent, plan)
    _run_set_env(args, target, intent, plan)
    _run_mode_message(plan)

    from app.main import main

    main()

    _run_fractal_summary(intent, target)

    return 0


def _register_local_parsers(subparsers) -> None:
    """Subcommands whose cmd_* still lives in this module: bench, run."""
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

def main() -> int:
    """Compose the CLI from the family modules.

    Each family registers its own subcommands (the engine's #1 convergence
    target was this file: hub x churn x single-author x co-change — moving
    parser definitions next to their commands sends future churn to the
    family modules instead of this hub).
    """
    import app.cli_autonomy as cli_autonomy
    import app.cli_ideate as cli_ideate
    import app.cli_insight as cli_insight
    import app.cli_insights as cli_insights
    import app.cli_ops as cli_ops
    import app.cli_plugins as cli_plugins
    import app.cli_reporting as cli_reporting
    import app.cli_refactor as cli_refactor
    import app.cli_review as cli_review
    import app.cli_viz as cli_viz

    parser = argparse.ArgumentParser(prog="apex", description="Apex Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Registration order shapes `apex --help`: flagship first, then the
    # analysis/refactor surface, then operations and reporting.
    cli_autonomy.register_parsers(subparsers)    # auto, simulate, evolve, maintain
    cli_insight.register_parsers(subparsers)     # grade, impact, brief, dream, ...
    cli_insights.register_parsers(subparsers)    # insights (analyzer suite sweep)
    cli_ideate.register_parsers(subparsers)      # ideate
    cli_review.register_parsers(subparsers)      # review
    cli_refactor.register_parsers(subparsers)    # rename, move, signature
    _register_local_parsers(subparsers)          # bench, run
    cli_ops.register_parsers(subparsers)         # scan, agents, consensus, daemon, ...
    cli_viz.register_parsers(subparsers)        # canvas, changed, idea-html, partition
    cli_reporting.register_parsers(subparsers)   # dashboard, hotspots, city, debug, ...
    cli_plugins.register_parsers(subparsers)     # plugin, marketplace, hook

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
