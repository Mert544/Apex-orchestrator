"""Reporting-family commands: debug, dashboard, deadcode, hotspots, city, report, fractal.

Extracted from the `app/cli.py` monolith — the engine's own #1 convergence
target (central dependency hub × high churn). Pure mechanical move:
`app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.cli_common import _get_project_root

def cmd_debug(args: argparse.Namespace) -> int:
    """Trace a run or analyze a traceback using the debug subsystem."""
    target = Path(args.target).resolve() if args.target else _get_project_root()

    if args.subcommand == "analyze":
        if args.trace and args.trace != "-":
            trace_text = Path(args.trace).read_text(encoding="utf-8")
        else:
            trace_text = sys.stdin.read()
        from app.agents.limbs import get_limb

        result = get_limb("debug").run(
            project_root=str(target),
            error_trace=trace_text,
            target_file=getattr(args, "file", "") or "",
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            rc = result.get("root_cause")
            print("=== APEX DEBUG ANALYZE ===")
            print(f"Root cause: {rc['type'] if rc else 'unidentified'}")
            for s in result.get("suggestions", []):
                print(f"  - {s}")
        return 0

    # default subcommand == "trace"
    from app.engine.debug_engine import DebugEngine
    from app.tools.project_profile import ProjectProfiler

    debug = DebugEngine(str(target), enabled=True)
    debug.trace("cli", f"debug trace target={target}")
    profile = ProjectProfiler(str(target)).profile()
    debug.snapshot(
        branch_map={d: 1 for d in profile.top_directories},
        telemetry={"total_files": profile.total_files},
    )
    report = debug.report()
    debug_files = sorted((target / ".apex" / "debug").glob("debug-*.json"))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== APEX DEBUG TRACE ===")
        print(f"Traces: {report['trace_count']}  Anomalies: {len(report['anomalies'])}")
        if debug_files:
            print(f"Report: {debug_files[-1]}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Generate a self-contained HTML dashboard for the project."""
    from app.reporting.dashboard import build_dashboard

    target = Path(args.target).resolve() if args.target else _get_project_root()
    html_doc = build_dashboard(
        str(target),
        objective=args.objective or None,
        max_ideas=args.max_ideas,
        idea_depth=args.depth,
        breadth=args.breadth,
    )
    out_path = Path(args.out) if args.out else target / ".apex" / "dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"[dashboard] Written to {out_path}")
    return 0


def cmd_deadcode(args: argparse.Namespace) -> int:
    """Report module-level symbols defined but referenced nowhere in the project."""
    from app.reporting.deadcode import find_dead_code, render_dead_code_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    evidence = None
    if getattr(args, "confirm", False):
        # Opt-in runtime confirmation: run the named tests under stdlib `trace`
        # and harvest which lines actually executed, so each finding can be
        # confirmed/refuted. May be slow for large suites — name a targeted path.
        from app.engine.runtime_trace import trace_pytest

        evidence = trace_pytest(getattr(args, "tests", "tests"), root=str(target))
    rows = find_dead_code(str(target), limit=args.limit, evidence=evidence)
    if args.json:
        import json
        print(json.dumps(rows, indent=2))
    else:
        print(render_dead_code_markdown(rows))
    return 0


def cmd_hotspots(args: argparse.Namespace) -> int:
    """Rank the modules most worth attention (complexity × blast-radius ÷ tests)."""
    from app.reporting.hotspots import build_hotspots, render_hotspots_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    rows = build_hotspots(str(target), limit=args.limit)
    if args.json:
        import json
        print(json.dumps(rows, indent=2))
    else:
        print(render_hotspots_markdown(rows))
    return 0


def cmd_city(args: argparse.Namespace) -> int:
    """Generate the 3D 'company city' dashboard — modules as buildings, agents as workers."""
    from app.reporting.city_dashboard import build_city

    target = Path(args.target).resolve() if args.target else _get_project_root()
    html_doc = build_city(str(target))
    out_path = Path(args.out) if args.out else target / ".apex" / "city.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"[city] Written to {out_path}")
    return 0



def cmd_report(args: argparse.Namespace) -> int:
    from app.reporting.composer import ReportComposer

    input_file = Path(args.input)
    if not input_file.exists():
        print(f"[report] Input file not found: {input_file}")
        return 1

    try:
        data = json.loads(input_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[report] Invalid JSON: {exc}")
        return 1

    results = data.get("swarm_results", data.get("results", []))
    composer = ReportComposer(results)

    fmt = args.format.lower()
    output = Path(args.output)
    if fmt == "markdown":
        composer.to_markdown(output)
    elif fmt == "html":
        composer.to_html(output)
    elif fmt == "sarif":
        composer.to_sarif(output)
    else:
        print(f"[report] Unknown format: {fmt}")
        return 1

    print(f"[report] {fmt.upper()} report written to {output}")
    return 0


def cmd_fractal(args: argparse.Namespace) -> int:
    """Run fractal deep analysis on a finding or project."""
    target = Path(args.target).resolve() if args.target else _get_project_root()

    if args.subcommand == "analyze":
        from app.agents.fractal_agents import FractalSecurityAgent

        agent = FractalSecurityAgent()
        if args.max_fractal_budget is not None:
            agent.max_fractal_budget = args.max_fractal_budget
        result = agent.run(project_root=target, max_depth=args.depth)
        print(
            f"Scanned {result['scanned_files']} files, found {result['findings_count']} risks"
        )
        print(
            f"Fractal analyzed {result['fractal_analyzed']} findings (depth={args.depth})"
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            from app.reporting.composer import ReportComposer

            composer = ReportComposer([result])
            md = composer.to_markdown()
            print(md)

    elif args.subcommand == "tree":
        from app.engine.fractal_5whys import Fractal5WhysEngine

        engine = Fractal5WhysEngine(max_depth=args.depth)
        finding = json.loads(args.finding)
        tree = engine.analyze(finding)
        print("\n".join(engine.summarize_tree(tree).splitlines()))

    return 0




def register_parsers(subparsers) -> None:
    """Register the reporting family's subcommands: dashboard, hotspots,
    deadcode, city, report, fractal, debug."""
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
    dead_parser.add_argument(
        "--confirm", action="store_true",
        help="Opt-in: run the project's own tests under stdlib trace to confirm/refute "
             "each finding at runtime (may be slow; names a targeted --tests path)",
    )
    dead_parser.add_argument(
        "--tests", default="tests",
        help="Test path traced when --confirm is set (default: tests)",
    )
    dead_parser.set_defaults(func=cmd_deadcode)

    # city — 3D "company city": modules as buildings, Apex agents as walking workers
    city_parser = subparsers.add_parser(
        "city", help="Generate the 3D company-city dashboard (modules as buildings, agents as workers)"
    )
    city_parser.add_argument("--target", default="", help="Target project root")
    city_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    city_parser.add_argument("--out", default="", help="Output HTML path (default <target>/.apex/city.html)")
    city_parser.set_defaults(func=cmd_city)

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
