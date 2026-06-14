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




# Idea-engine bounds for pulse: a small budget so the snapshot is fast — pulse is
# a one-screen "vital signs" read, not the full ideate tree. Deterministic for a
# fixed tree (the engine adds no time/random to scoring).
_PULSE_MAX_IDEAS = 12
_PULSE_DEPTH = 2
_PULSE_BREADTH = 3
_PULSE_TOP_MOVES = 3
_PULSE_OUT_OF_SCOPE_FILES = 2


def _pulse_grade(root: Path) -> dict:
    """The project's health grade (letter + score), read defensively.

    Grounded in ``health_score.grade`` (a light profile + one detect pass). Any
    failure collapses to a neutral, never-crash shape with an empty letter so the
    header still renders ("Grade: —") rather than aborting the whole snapshot.
    """
    try:
        from app.engine.health_score import grade

        h = grade(str(root))
        return {"letter": h.letter, "score": int(h.score), "scope_line": h.scope_line}
    except Exception:
        return {"letter": "", "score": None, "scope_line": ""}


def _pulse_scope(root: Path) -> dict:
    """Honest analysis-coverage: analysed% (Python) vs out-of-scope%, plus the
    1-2 biggest out-of-scope files. Grounded in the profile's scope-accounting
    fields and ``scan_polyglot_facts``; degrades to the all-Python shape on any
    failure so the section never crashes the snapshot."""
    try:
        from app.tools.polyglot_facts import scan_polyglot_facts
        from app.tools.project_profile import ProjectProfiler

        profile = ProjectProfiler(str(root)).profile(light=True)
    except Exception:
        return {"all_python": True, "analyzed_pct": 100, "out_of_scope_pct": 0, "files": []}

    if profile is None or getattr(profile, "source_file_count", 0) <= 0:
        return {"all_python": True, "analyzed_pct": 100, "out_of_scope_pct": 0, "files": []}

    out_ratio = getattr(profile, "out_of_scope_ratio", 0.0) or 0.0
    breakdown = getattr(profile, "language_breakdown", {}) or {}
    all_python = not (out_ratio > 0 and breakdown)
    files: list[dict] = []
    if not all_python:
        try:
            facts = scan_polyglot_facts(str(root), limit=_PULSE_OUT_OF_SCOPE_FILES)
        except Exception:
            facts = []
        files = [{"path": f.path, "language": f.language, "loc": f.loc} for f in facts]

    return {
        "all_python": all_python,
        "analyzed_pct": round((getattr(profile, "analyzed_ratio", 1.0) or 1.0) * 100),
        "out_of_scope_pct": round(out_ratio * 100),
        "files": files,
    }


def _pulse_moves(root: Path) -> list[dict]:
    """The top few grounded next-moves: each idea's title + its concrete focus
    (the riskiest anchor symbol/line when the idea carries one).

    Bounded idea-engine run (small budget) so the snapshot stays fast. Reads
    defensively: any engine failure yields no moves rather than crashing. The
    top moves are the highest-value ideas, ordered ``(-value, branch_path)`` so
    the selection is deterministic for a fixed tree.
    """
    try:
        from app.engine.idea_permutation import IdeaPermutationEngine

        report = IdeaPermutationEngine(
            {"max_total_ideas": _PULSE_MAX_IDEAS, "max_idea_depth": _PULSE_DEPTH,
             "breadth": _PULSE_BREADTH},
            project_root=str(root),
        ).run()
        ideas = list(report.ideas or [])
    except Exception:
        return []

    ideas.sort(key=lambda i: (-i.value, i.branch_path))
    moves: list[dict] = []
    for idea in ideas[:_PULSE_TOP_MOVES]:
        focus = ""
        anchors = idea.anchors or []
        if anchors:
            a = anchors[0]
            symbol = str(a.get("symbol", "")).rsplit(".", 1)[-1]
            line = a.get("line")
            metric = a.get("metric", "")
            if symbol:
                detail = ", ".join(
                    str(b) for b in (metric, f"line {line}" if line else "") if b
                )
                focus = f"{symbol} ({detail})" if detail else symbol
        moves.append({
            "title": idea.title,
            "branch_path": idea.branch_path,
            "value": round(idea.value, 4),
            "focus": focus,
        })
    return moves


def _pulse_trackrecord(root: Path) -> dict:
    """Apex's measured landing rates per fix-type on THIS repo, read from its own
    ``.apex/idea-memory.json``. Deterministic and defensive: a fresh repo with no
    memory yields an empty record (the "no track record yet" path)."""
    try:
        from app.engine.idea_memory import IdeaMemory

        summary = IdeaMemory.load(root).summary()
    except Exception:
        summary = {}

    by_key: dict[str, dict] = {}
    for row in [*(summary.get("most_reliable") or []), *(summary.get("least_reliable") or [])]:
        key = row.get("key", "")
        if key and key not in by_key:
            by_key[key] = {
                "key": key,
                "success_rate": float(row.get("success_rate", 0.0)),
                "samples": int(row.get("samples", 0)),
            }
    by_type = sorted(by_key.values(), key=lambda r: (-r["success_rate"], r["key"]))
    return {"by_type": by_type, "has_record": bool(by_type)}


def _pulse_snapshot(root: Path) -> dict:
    """Assemble the whole deterministic 'vital signs' snapshot for ``root``.

    Each section is read independently and defensively (any missing piece →
    that section degrades, never crashes), so the snapshot is total: it always
    returns a complete, renderable shape for any directory.
    """
    return {
        "project_root": str(root),
        "grade": _pulse_grade(root),
        "scope": _pulse_scope(root),
        "moves": _pulse_moves(root),
        "trackrecord": _pulse_trackrecord(root),
    }


def _render_trackrecord_line(by_type: list[dict]) -> str:
    """One calm line summarising landing rates, e.g. 'sort_imports 100% (50),
    harden 0% (3)'. Empty list → the honest 'no track record yet'."""
    if not by_type:
        return "no track record yet"
    parts = [
        f"{row['key']} {round(row['success_rate'] * 100)}% ({row['samples']})"
        for row in by_type[:_PULSE_TOP_MOVES]
    ]
    return ", ".join(parts)


def render_pulse(snap: dict) -> str:
    """Render the snapshot as a compact, scannable one-screen vital-signs view."""
    grade = snap["grade"]
    scope = snap["scope"]
    moves = snap["moves"]

    lines = ["# Apex pulse", ""]

    # Header: grade letter + score.
    letter = grade.get("letter") or "—"
    score = grade.get("score")
    if score is None:
        lines.append(f"Grade: **{letter}**")
    else:
        lines.append(f"Grade: **{letter}** ({score}/100)")
    lines.append("")

    # Scope: analysed% vs out-of-scope%, plus the biggest out-of-scope files.
    if scope.get("all_python"):
        lines.append("Scope: analysing 100% (all Python)")
    else:
        analysed = scope.get("analyzed_pct", 100)
        out_pct = scope.get("out_of_scope_pct", 0)
        line = f"Scope: analysing {analysed}% (Python); {out_pct}% out of scope"
        files = scope.get("files") or []
        if files:
            named = ", ".join(f"`{f['path']}` ({f['loc']} LOC)" for f in files)
            line += f" — biggest outside: {named}"
        lines.append(line)
    lines.append("")

    # Top grounded next-moves: title + concrete focus when present.
    lines.append("Next moves:")
    if moves:
        for m in moves:
            focus = f" → focus: {m['focus']}" if m.get("focus") else ""
            lines.append(f"- {m['title']}{focus}")
    else:
        lines.append("- (no ideas generated for this target)")
    lines.append("")

    # Track record: one-line landing-rate summary.
    lines.append(f"Track record: {_render_trackrecord_line(snap['trackrecord']['by_type'])}")
    lines.append("")
    lines.append(
        "_Deterministic, stdlib-only, LLM-free — every number read from this "
        "repo's own structure and Apex's evidence trail._"
    )
    return "\n".join(lines)


def cmd_pulse(args: argparse.Namespace) -> int:
    """The cell's instant-value face: a one-screen grounded 'vital signs'
    snapshot of the project Apex sits in — grade, honest scope, the top grounded
    next-moves, and the measured track record. Deterministic, stdlib-only,
    LLM-free; reads every section defensively so a missing piece degrades that
    section rather than crashing the snapshot."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    snap = _pulse_snapshot(target)
    if getattr(args, "json", False):
        print(json.dumps(snap, indent=2, default=str))
    else:
        print(render_pulse(snap))
    return 0


def register_parsers(subparsers) -> None:
    """Register the reporting family's subcommands: dashboard, hotspots,
    deadcode, city, report, fractal, debug, pulse."""
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

    # pulse — the cell's instant-value face: a one-screen grounded "vital signs"
    # snapshot (grade, honest scope, top next-moves, track record). Deterministic.
    pulse_parser = subparsers.add_parser(
        "pulse",
        help="One-screen grounded vital-signs snapshot: grade, scope, top next-moves, "
             "track record (deterministic, stdlib-only, LLM-free)",
    )
    pulse_parser.add_argument("--target", default="", help="Target project root")
    pulse_parser.add_argument("--json", action="store_true", help="Emit JSON")
    pulse_parser.set_defaults(func=cmd_pulse)
