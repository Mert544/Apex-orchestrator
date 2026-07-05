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

def _debug_analyze(args: argparse.Namespace, target: Path) -> int:
    """`apex debug analyze`: diagnose a traceback (from --trace file or stdin)."""
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


def _debug_trace(args: argparse.Namespace, target: Path) -> int:
    """`apex debug trace`: run with debug tracing; write a .apex/debug report."""
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


def cmd_debug(args: argparse.Namespace) -> int:
    """Trace a run or analyze a traceback using the debug subsystem."""
    target = Path(args.target).resolve() if args.target else _get_project_root()

    if args.subcommand == "analyze":
        return _debug_analyze(args, target)

    # default subcommand == "trace"
    return _debug_trace(args, target)


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


def _pulse_grade(root: Path, profile=None) -> dict:
    """The project's health grade (letter + score), read defensively.

    Grounded in ``health_score.grade`` (a light profile + one detect pass). A
    shared ``profile`` may be injected to skip a redundant re-scan. Any failure
    collapses to a neutral, never-crash shape with an empty letter so the
    header still renders ("Grade: —") rather than aborting the whole snapshot.
    """
    try:
        from app.engine.health_score import grade

        h = grade(str(root), profile=profile)
        return {"letter": h.letter, "score": int(h.score), "scope_line": h.scope_line}
    except Exception:
        return {"letter": "", "score": None, "scope_line": ""}


def _honest_unanalyzed_count(profile) -> int:
    """COMPLETE count of in-language files counted but NOT analysed, read straight
    off the profile (the SINGLE SOURCE OF TRUTH). Prefers the canonical
    ``unanalyzed_count``, falls back to its back-compat alias ``unparsed_count``;
    any missing/None attribute reads as 0. Inlined (not imported) so the pulse
    snapshot's lazy ``project_profile`` stub-injection can't shadow it."""
    n = getattr(profile, "unanalyzed_count", None)
    if n is None:
        n = getattr(profile, "unparsed_count", 0)
    return int(n or 0)


def _honest_analyzed_ratio(profile) -> float:
    """The HONEST analysed fraction (analysed-count / source-total) read off the
    profile's ``analyzed_ratio_honest``; falls back to the raw language
    ``analyzed_ratio`` only if absent. Equals the language ratio when nothing was
    dropped, so the common case is byte-identical."""
    honest = getattr(profile, "analyzed_ratio_honest", None)
    if honest is None:
        honest = getattr(profile, "analyzed_ratio", 1.0)
    return float(honest if honest is not None else 1.0)


def _pulse_scope(root: Path, profile=None) -> dict:
    """Honest analysis-coverage: analysed% (Python) vs out-of-scope%, plus the
    1-2 biggest out-of-scope files. Grounded in the profile's scope-accounting
    fields and ``scan_polyglot_facts``; degrades to the all-Python shape on any
    failure so the section never crashes the snapshot. A shared ``profile`` may
    be injected to skip a redundant re-scan (it reads only fields present in
    both the light and full flavors, so the output is unchanged)."""
    try:
        from app.tools.polyglot_facts import scan_polyglot_facts

        if profile is None:
            from app.tools.project_profile import ProjectProfiler

            profile = ProjectProfiler(str(root)).profile(light=True)
    except Exception:
        return {"all_python": True, "analyzed_pct": 100, "out_of_scope_pct": 0, "files": []}

    if profile is None or getattr(profile, "source_file_count", 0) <= 0:
        return {"all_python": True, "analyzed_pct": 100, "out_of_scope_pct": 0, "files": []}

    out_ratio = getattr(profile, "out_of_scope_ratio", 0.0) or 0.0
    breakdown = getattr(profile, "language_breakdown", {}) or {}
    unanalyzed_count = _honest_unanalyzed_count(profile)
    # "all Python" (the reassuring 100% footer) is honest ONLY when the grade
    # truly speaks for the whole repo: no out-of-scope languages AND no in-language
    # file that was counted but not analysed. Same gate as ``_scope_report``.
    all_python = not (out_ratio > 0 and breakdown) and unanalyzed_count == 0
    # The biggest out-of-scope files come from the polyglot scan (NON-Python),
    # populated only when a polyglot remainder genuinely exists.
    files = _pulse_scope_files(root, scan_polyglot_facts) if (
        out_ratio > 0 and breakdown) else []
    analyzed_pct, out_of_scope_pct = _pulse_scope_pcts(
        profile, out_ratio, unanalyzed_count)
    return {
        "all_python": all_python,
        "analyzed_pct": analyzed_pct,
        "out_of_scope_pct": out_of_scope_pct,
        "files": files,
    }


def _pulse_scope_files(root: Path, scan_polyglot_facts) -> list[dict]:
    """The biggest / most-active NON-Python files for the pulse scope footer.

    Defensive: any scan failure yields [] so the snapshot never crashes. Split out
    to keep ``_pulse_scope`` simple."""
    try:
        facts = scan_polyglot_facts(str(root), limit=_PULSE_OUT_OF_SCOPE_FILES)
    except Exception:
        facts = []
    return [{"path": f.path, "language": f.language, "loc": f.loc} for f in facts]


def _pulse_scope_pcts(profile, out_ratio: float, unanalyzed_count: int) -> tuple[int, int]:
    """``(analyzed_pct, out_of_scope_pct)`` for the pulse scope footer.

    Byte-identity: with NOTHING dropped, derive the percentages EXACTLY as before
    (raw language ratio, independent round of each), so the common case is
    unchanged down to float rounding. ONLY when files were dropped do we switch to
    the honest ratio (clamped at 99 so a real drop can never round UP to a false
    100%) and derive out-of-scope as ``100 - analyzed`` so the two sum to 100 —
    mirroring ``cli_insight._scope_report``.
    """
    if unanalyzed_count <= 0:
        return (
            round((getattr(profile, "analyzed_ratio", 1.0) or 1.0) * 100),
            round(out_ratio * 100),
        )
    analyzed_pct = min(round(_honest_analyzed_ratio(profile) * 100), 99)
    return analyzed_pct, 100 - analyzed_pct


def _pulse_moves(root: Path, profile=None) -> list[dict]:
    """The top few grounded next-moves: each idea's title + its concrete focus
    (the riskiest anchor symbol/line when the idea carries one).

    Bounded idea-engine run (small budget) so the snapshot stays fast. A shared
    ``profile`` may be injected so the engine skips its own re-scan (the biggest
    single cost). Reads defensively: any engine failure yields no moves rather
    than crashing. The top moves are the highest-value ideas, ordered
    ``(-value, branch_path)`` so the selection is deterministic for a fixed tree.
    """
    try:
        from app.engine.idea_permutation import IdeaPermutationEngine

        report = IdeaPermutationEngine(
            {"max_total_ideas": _PULSE_MAX_IDEAS, "max_idea_depth": _PULSE_DEPTH,
             "breadth": _PULSE_BREADTH},
            project_root=str(root),
            project_profile=profile,
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

    Performance: the three heavy sections (grade, scope, moves) each used to
    re-scan the whole project independently. We now build ONE full profile here
    and thread it into all three — a superset of what grade/scope read and the
    exact flavor the idea engine builds — so the output is byte-identical while
    the project is scanned once instead of three times. If the shared build
    fails, ``profile`` is None and each section falls back to its own build,
    preserving the previous per-section failure isolation.
    """
    try:
        from app.tools.project_profile import ProjectProfiler

        profile = ProjectProfiler(str(root)).profile()
    except Exception:
        profile = None
    return {
        "project_root": str(root),
        "grade": _pulse_grade(root, profile),
        "scope": _pulse_scope(root, profile),
        "moves": _pulse_moves(root, profile),
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


# --- apex gate: zero-config deterministic CI quality gate --------------------
#
# The complement to `apex outcomes` (which gates on a USER-WRITTEN rubric):
# `apex gate` gates on Apex's OWN deterministic metrics with sensible defaults,
# so a user can drop it into CI with no setup. Every number is read from this
# repo's own structure (the health grade + ProjectProfile) — no time, no random,
# no tokens. A CI can depend on this verdict; an LLM cannot gate reproducibly.
#
# Default-check behaviour (DOCUMENTED): the two correctness/security checks are
# ON by conservative default — `--max-security 0` and `--max-bugs 0` — because a
# clean repo has neither, so a bare `apex gate` PASSES a clean repo yet FAILS the
# instant Apex's own detectors find a security finding or a likely-crash bug. The
# two "softer" checks (`--min-score`, `--max-out-of-scope`) default OFF (0 / -1)
# so they never spuriously fail and are opt-in for stricter pipelines.

_GATE_MIN_SCORE_OFF = 0       # --min-score 0 => check disabled
_GATE_MAX_OUT_OF_SCOPE_OFF = -1  # --max-out-of-scope < 0 => check disabled


def _gate_metrics(root: Path) -> dict:
    """Read Apex's own deterministic metrics for ``root``, defensively.

    Pulls the health score from ``health_score.grade`` and the security /
    correctness / scope counts from a light ``ProjectProfile``. Any failure on a
    given source collapses that source to a neutral, never-crash shape (score
    ``None``, empty module lists, ``0.0`` out-of-scope) so the gate always
    renders a verdict rather than aborting CI with a traceback.
    """
    score: int | None = None
    letter = ""
    try:
        from app.engine.health_score import grade

        h = grade(str(root))
        score = int(h.score)
        letter = h.letter
    except Exception:
        score, letter = None, ""

    security = 0
    bugs = 0
    out_of_scope = 0.0
    try:
        from app.tools.project_profile import ProjectProfiler

        profile = ProjectProfiler(str(root)).profile(light=True)
        security = len(getattr(profile, "security_finding_modules", []) or [])
        bugs = len(getattr(profile, "correctness_bug_modules", []) or [])
        out_of_scope = float(getattr(profile, "out_of_scope_ratio", 0.0) or 0.0)
    except Exception:
        security, bugs, out_of_scope = 0, 0, 0.0

    return {
        "score": score,
        "letter": letter,
        "security_modules": security,
        "bug_modules": bugs,
        "out_of_scope_pct": round(out_of_scope * 100, 1),
    }


def _gate_evaluate(metrics: dict, args: argparse.Namespace) -> dict:
    """Apply the enabled checks to ``metrics`` and return a deterministic verdict.

    A check is *skipped* (omitted from ``checks``) when its flag disables it. Each
    emitted check carries ``name``, ``passed``, ``actual``, ``threshold``, and a
    one-line ``detail``. The overall ``passed`` is the AND of every enabled check
    (an empty check set passes — a pure metrics read-out).
    """
    min_score = int(getattr(args, "min_score", _GATE_MIN_SCORE_OFF) or _GATE_MIN_SCORE_OFF)
    max_security = getattr(args, "max_security", 0)
    max_bugs = getattr(args, "max_bugs", 0)
    max_oos = getattr(args, "max_out_of_scope", _GATE_MAX_OUT_OF_SCOPE_OFF)

    checks: list[dict] = []

    # --min-score N (default 0 = off): fail if health score < N. A score of None
    # (grading failed) cannot satisfy a threshold, so it fails the check honestly.
    if min_score > _GATE_MIN_SCORE_OFF:
        score = metrics["score"]
        ok = score is not None and score >= min_score
        actual = "n/a" if score is None else str(score)
        checks.append({
            "name": "min-score",
            "passed": ok,
            "actual": actual,
            "threshold": min_score,
            "detail": f"health score {actual} (need >= {min_score})",
        })

    # --max-security N (default 0): fail if security-finding modules > N.
    if max_security is not None:
        max_security = int(max_security)
        actual = metrics["security_modules"]
        ok = actual <= max_security
        checks.append({
            "name": "max-security",
            "passed": ok,
            "actual": actual,
            "threshold": max_security,
            "detail": f"{actual} security-finding module(s) (allow <= {max_security})",
        })

    # --max-bugs N (default 0): fail if correctness-bug modules > N.
    if max_bugs is not None:
        max_bugs = int(max_bugs)
        actual = metrics["bug_modules"]
        ok = actual <= max_bugs
        checks.append({
            "name": "max-bugs",
            "passed": ok,
            "actual": actual,
            "threshold": max_bugs,
            "detail": f"{actual} correctness-bug module(s) (allow <= {max_bugs})",
        })

    # --max-out-of-scope PCT (default -1 = off): fail if out_of_scope% > PCT.
    if max_oos is not None and float(max_oos) >= 0:
        max_oos = float(max_oos)
        actual = metrics["out_of_scope_pct"]
        ok = actual <= max_oos
        checks.append({
            "name": "max-out-of-scope",
            "passed": ok,
            "actual": actual,
            "threshold": max_oos,
            "detail": f"{actual}% out of scope (allow <= {max_oos}%)",
        })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "metrics": metrics}


# --- baseline (regression) mode ---------------------------------------------
#
# Absolute thresholds answer "is this repo good enough?"; a *baseline* answers
# the more useful CI question "did THIS change make the project worse?". We
# snapshot the same `_gate_metrics` shape to `.apex/gate-baseline.json` and, on
# a later run, FAIL on any regression: a lower score (beyond `--tolerance`), more
# security-finding or correctness-bug modules, or a higher out-of-scope ratio
# (beyond a small epsilon for float noise). Everything is deterministic and
# stdlib-only — baseline mode is opt-in (`--save-baseline` / `--baseline`) so a
# bare `apex gate` stays byte-identical.

_GATE_BASELINE_REL = Path(".apex") / "gate-baseline.json"
_GATE_OOS_EPSILON = 0.05  # out-of-scope% noise floor: ignore drifts <= this


def _gate_baseline_path(root: Path) -> Path:
    """The on-disk baseline location for ``root`` (``<root>/.apex/gate-baseline.json``)."""
    return root / _GATE_BASELINE_REL


def _gate_save_baseline(root: Path, metrics: dict) -> Path:
    """Write ``metrics`` to ``root``'s baseline file as deterministic JSON.

    Creates ``.apex/`` if needed; keys are sorted and the file ends in a newline
    so a committed baseline diffs cleanly. Returns the path written.
    """
    path = _gate_baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _gate_load_baseline(root: Path) -> dict | None:
    """Load ``root``'s baseline metrics, or ``None`` if absent/unreadable.

    Defensive: a missing or corrupt baseline returns ``None`` rather than
    raising, so the caller decides the CI contract (we choose non-zero rc).
    """
    path = _gate_baseline_path(root)
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _gate_classify(name: str, before, after, regressed: bool, improved: bool, detail: str) -> dict:
    """Build one classified comparison row (REGRESSED / IMPROVED / SAME)."""
    if regressed:
        status = "REGRESSED"
    elif improved:
        status = "IMPROVED"
    else:
        status = "SAME"
    return {
        "name": name,
        "status": status,
        "before": before,
        "after": after,
        "regressed": regressed,
        "detail": detail,
    }


def _gate_compare_score(baseline: dict, current: dict, tolerance: int) -> dict:
    """Compare the health score: regress if it dropped by MORE than ``tolerance``.

    None (grading failed) is treated as -1 so a vanished score reads as a
    regression, not a tie.
    """
    b_score = baseline.get("score")
    c_score = current.get("score")
    b_num = -1 if b_score is None else int(b_score)
    c_num = -1 if c_score is None else int(c_score)
    suffix = f" (tolerance {tolerance})" if tolerance else ""
    return _gate_classify(
        "score",
        "n/a" if b_score is None else b_score,
        "n/a" if c_score is None else c_score,
        (b_num - c_num) > tolerance, c_num > b_num,
        f"health score {b_score if b_score is not None else 'n/a'} -> "
        f"{c_score if c_score is not None else 'n/a'}{suffix}",
    )


def _gate_compare_count(name: str, baseline: dict, current: dict, key: str, noun: str) -> dict:
    """Compare a module-count metric: regress if the count increased."""
    before = int(baseline.get(key, 0) or 0)
    after = int(current.get(key, 0) or 0)
    return _gate_classify(
        name, before, after, after > before, after < before,
        f"{before} -> {after} {noun}",
    )


def _gate_compare_out_of_scope(baseline: dict, current: dict) -> dict:
    """Compare out-of-scope%: regress if it rose by more than ``_GATE_OOS_EPSILON``."""
    before = float(baseline.get("out_of_scope_pct", 0.0) or 0.0)
    after = float(current.get("out_of_scope_pct", 0.0) or 0.0)
    delta = after - before
    return _gate_classify(
        "out-of-scope", before, after,
        delta > _GATE_OOS_EPSILON, delta < -_GATE_OOS_EPSILON,
        f"{before}% -> {after}% out of scope",
    )


def _gate_compare_baseline(baseline: dict, current: dict, tolerance: int) -> dict:
    """Compare ``current`` metrics against ``baseline`` and return a verdict.

    Each comparison is classified IMPROVED / SAME / REGRESSED with its
    before→after values. ``regressed`` is True iff any comparison regressed;
    ``tolerance`` (>= 0) absorbs a score drop of at most that many points. The
    out-of-scope check ignores drifts within ``_GATE_OOS_EPSILON`` so float
    noise never trips CI. Defensive: missing baseline keys read as neutral.
    """
    tolerance = max(0, int(tolerance))
    comparisons = [
        _gate_compare_score(baseline, current, tolerance),
        _gate_compare_count(
            "security-modules", baseline, current,
            "security_modules", "security-finding module(s)",
        ),
        _gate_compare_count(
            "bug-modules", baseline, current,
            "bug_modules", "correctness-bug module(s)",
        ),
        _gate_compare_out_of_scope(baseline, current),
    ]

    regressions = sum(1 for c in comparisons if c["regressed"])
    return {
        "regressed": regressions > 0,
        "regressions": regressions,
        "tolerance": tolerance,
        "comparisons": comparisons,
    }


def render_gate_baseline(baseline_verdict: dict) -> str:
    """Render the baseline comparison as a concise, deterministic report."""
    comps = baseline_verdict["comparisons"]
    n = baseline_verdict["regressions"]
    lines = ["## Regression vs baseline", ""]
    for c in comps:
        lines.append(f"[{c['status']}] {c['name']}: {c['detail']}")
    lines.append("")
    if n:
        lines.append(f"GATE FAILED ({n} regression(s))")
    else:
        lines.append("GATE PASSED (no regressions)")
    return "\n".join(lines)


def render_gate(verdict: dict) -> str:
    """Render the gate verdict as a concise, deterministic CI-friendly report."""
    metrics = verdict["metrics"]
    checks = verdict["checks"]
    lines = ["# Apex gate", ""]

    letter = metrics.get("letter") or "—"
    score = metrics.get("score")
    score_str = "n/a" if score is None else f"{score}/100"
    lines.append(f"Grade: {letter} ({score_str})")
    lines.append("")

    if checks:
        for c in checks:
            mark = "PASS" if c["passed"] else "FAIL"
            lines.append(f"[{mark}] {c['name']}: {c['detail']}")
    else:
        lines.append("(no checks enabled — metrics read-out only)")
    lines.append("")

    lines.append("GATE PASSED" if verdict["passed"] else "GATE FAILED")

    # Baseline (regression) section, when in baseline mode — composed with the
    # absolute checks above so a run can fail on EITHER signal.
    baseline = verdict.get("baseline")
    if baseline is not None:
        lines.append("")
        lines.append(render_gate_baseline(baseline))

    lines.append("")
    lines.append(
        "_Deterministic, stdlib-only, zero-token — every number read from this "
        "repo's own structure. CI can depend on this verdict; an LLM can't gate "
        "reproducibly._"
    )
    return "\n".join(lines)


def _gate_run_save_baseline(args: argparse.Namespace, target: Path, metrics: dict) -> int:
    """--save-baseline: snapshot current metrics and exit 0. Opt-in, side-effect
    only — it does not evaluate any check."""
    path = _gate_save_baseline(target, metrics)
    if getattr(args, "json", False):
        print(json.dumps(
            {"saved": True, "path": str(path), "metrics": metrics},
            indent=2, sort_keys=True, default=str,
        ))
    else:
        print(f"Saved gate baseline to {path}")
    return 0


def _gate_apply_baseline(args: argparse.Namespace, target: Path, metrics: dict, verdict: dict) -> int | None:
    """--baseline: compose a regression check over the absolute checks, mutating
    ``verdict`` in place. A missing baseline is a misconfigured CI — we surface it
    with a clear message and return rc 2 so it can't pass silently. Returns None
    when the regression check was composed (caller renders the verdict normally).
    """
    baseline = _gate_load_baseline(target)
    if baseline is None:
        msg = (
            "no baseline saved — run `apex gate --save-baseline` first"
        )
        if getattr(args, "json", False):
            print(json.dumps(
                {"error": msg, "baseline_missing": True},
                indent=2, sort_keys=True, default=str,
            ))
        else:
            print(msg)
        return 2
    tolerance = int(getattr(args, "tolerance", 0) or 0)
    comparison = _gate_compare_baseline(baseline, metrics, tolerance)
    verdict["baseline"] = comparison
    # A run fails on EITHER an absolute threshold OR a regression.
    verdict["passed"] = verdict["passed"] and not comparison["regressed"]
    return None


def cmd_gate(args: argparse.Namespace) -> int:
    """The zero-config, deterministic CI quality gate: it gates on Apex's OWN
    metrics (health grade + ProjectProfile) with sensible defaults, so a bare
    `apex gate` passes a clean repo yet fails the instant Apex's detectors find a
    security finding or a likely-crash bug. Each check is configurable via a flag
    and skipped when that flag disables it. Returns 0 when all enabled checks
    pass, 1 when any fails — the CI contract. Deterministic, stdlib-only, zero
    tokens: a prover CI can depend on; an LLM cannot gate reproducibly."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    metrics = _gate_metrics(target)

    if getattr(args, "save_baseline", False):
        return _gate_run_save_baseline(args, target, metrics)

    verdict = _gate_evaluate(metrics, args)

    if getattr(args, "baseline", False):
        rc = _gate_apply_baseline(args, target, metrics, verdict)
        if rc is not None:
            return rc

    if getattr(args, "json", False):
        print(json.dumps(verdict, indent=2, default=str))
    else:
        print(render_gate(verdict))
    return 0 if verdict["passed"] else 1


def cmd_deps(args: argparse.Namespace) -> int:
    """Audit the project's DEPENDENCIES — a real Apex blind spot: it grades its
    host's code in depth yet never cross-checks declared deps against what the
    code actually imports. Reports possibly-unused, possibly-undeclared, and
    unpinned deps. Deterministic, stdlib-only, LLM-free, no network. A HEURISTIC
    (extras/optional imports can cause false positives) so it never fails a build
    unless you opt in with --strict. Reads defensively; never crashes."""
    from app.engine.dependency_audit import (
        audit_dependencies,
        render_dependency_audit_markdown,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    try:
        findings = audit_dependencies(str(target))
    except Exception:
        # Defensive: an unexpected read failure degrades to an empty audit
        # rather than aborting with a traceback.
        from app.engine.dependency_audit import DependencyFindings

        findings = DependencyFindings(
            declared=[], imported_third_party=[], unused=[], undeclared=[], unpinned=[]
        )

    if getattr(args, "json", False):
        print(json.dumps(
            {
                "declared": findings.declared,
                "imported_third_party": findings.imported_third_party,
                "unused": findings.unused,
                "undeclared": findings.undeclared,
                "unpinned": findings.unpinned,
            },
            indent=2, sort_keys=True, default=str,
        ))
    else:
        print(render_dependency_audit_markdown(findings))

    # --strict (opt-in): non-zero rc when any heuristic signal fires, so a
    # pipeline that trusts the audit can gate on it. Off by default — the audit
    # is a surfaced signal, not a build-breaker.
    if getattr(args, "strict", False) and (
        findings.unused or findings.undeclared or findings.unpinned
    ):
        return 1
    return 0


def register_parsers(subparsers) -> None:
    """Register the reporting family's subcommands: dashboard, hotspots,
    deadcode, city, report, fractal, debug, pulse, gate, deps."""
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

    # gate — zero-config deterministic CI quality gate. Gates on Apex's OWN
    # metrics with conservative defaults (no security findings, no correctness
    # bugs); score-floor and out-of-scope ceiling are opt-in. Exit 0 pass / 1 fail.
    gate_parser = subparsers.add_parser(
        "gate",
        help="Zero-config deterministic CI quality gate: PASS/FAIL on Apex's own "
             "metrics (exit 0/1). Deterministic, zero-token — CI can depend on it, "
             "an LLM can't gate reproducibly",
    )
    gate_parser.add_argument("--target", default="", help="Target project root")
    gate_parser.add_argument(
        "--min-score", type=int, default=_GATE_MIN_SCORE_OFF, dest="min_score",
        help="Fail if health score < N (default 0 = off)",
    )
    gate_parser.add_argument(
        "--max-security", type=int, default=0, dest="max_security",
        help="Fail if security-finding modules > N (default 0)",
    )
    gate_parser.add_argument(
        "--max-bugs", type=int, default=0, dest="max_bugs",
        help="Fail if correctness-bug modules > N (default 0)",
    )
    gate_parser.add_argument(
        "--max-out-of-scope", type=float, default=_GATE_MAX_OUT_OF_SCOPE_OFF,
        dest="max_out_of_scope",
        help="Fail if out-of-scope%% > PCT (default off)",
    )
    gate_parser.add_argument(
        "--save-baseline", action="store_true", dest="save_baseline",
        help="Snapshot current gate metrics to .apex/gate-baseline.json and exit 0 "
             "(opt-in regression baseline; no checks run)",
    )
    gate_parser.add_argument(
        "--baseline", action="store_true", dest="baseline",
        help="Fail on any REGRESSION vs .apex/gate-baseline.json (lower score, more "
             "security/bug modules, higher out-of-scope) in addition to the absolute "
             "checks; missing baseline -> rc 2",
    )
    gate_parser.add_argument(
        "--tolerance", type=int, default=0, dest="tolerance",
        help="With --baseline: absorb a health-score drop of up to N points "
             "before calling it a regression (default 0)",
    )
    gate_parser.add_argument("--json", action="store_true", help="Emit JSON")
    gate_parser.set_defaults(func=cmd_gate)

    # deps — deterministic dependency audit: cross-check declared deps against
    # the third-party modules the code actually imports. Heuristic (extras /
    # optional imports may false-positive) so it returns 0 by default; --strict
    # makes any finding non-zero for pipelines that trust it.
    deps_parser = subparsers.add_parser(
        "deps",
        help="Audit dependencies: possibly-unused / undeclared / unpinned deps "
             "(deterministic, stdlib-only, LLM-free, no network). Heuristic — "
             "returns 0 unless --strict",
    )
    deps_parser.add_argument("--target", default="", help="Target project root")
    deps_parser.add_argument("--json", action="store_true", help="Emit JSON")
    deps_parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero (1) if any unused/undeclared/unpinned dep is found "
             "(opt-in; default off — the audit is a surfaced signal, not a gate)",
    )
    deps_parser.set_defaults(func=cmd_deps)
