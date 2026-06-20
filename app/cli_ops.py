"""Ops-family commands: agents, scan, consensus, daemon, audits, metrics.

Extracted from the `app/cli.py` monolith — the engine's own #1 convergence
target (central dependency hub × high churn). Pure mechanical move:
`app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.cli_common import _get_project_root

def cmd_agents(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve() if args.target else _get_project_root()
    agent_type = args.agent_type

    if agent_type == "security":
        from app.agents.skills import SecurityAgent

        agent = SecurityAgent()
        result = agent.run(project_root=target)
        print(json.dumps(result, indent=2))

    elif agent_type == "docstring":
        from app.agents.skills import DocstringAgent

        agent = DocstringAgent()
        result = agent.run(project_root=target, patch=args.patch)
        print(f"Found {result['gaps_found']} missing docstrings")
        if result["patched_files"]:
            print(
                f"Patched {len(result['patched_files'])} files: {result['patched_files']}"
            )
        print(json.dumps(result, indent=2))

    elif agent_type == "test-stub":
        from app.agents.skills import TestStubAgent

        agent = TestStubAgent()
        result = agent.run(project_root=target, generate=args.generate)
        print(
            f"Coverage: {result['coverage_ratio'] * 100:.0f}% ({result['tested_functions']}/{result['total_functions']})"
        )
        if result["stubs_generated"]:
            print(
                f"Generated {len(result['stubs_generated'])} test stubs: {result['stubs_generated']}"
            )
        print(json.dumps(result, indent=2))

    elif agent_type == "dependency":
        from app.agents.skills import DependencyAgent

        agent = DependencyAgent()
        result = agent.run(project_root=target)
        print(f"Modules: {result['total_modules']}, Edges: {result['total_edges']}")
        if result["circular_imports"]:
            print(f"Circular imports detected: {len(result['circular_imports'])}")
        if result["orphaned_modules"]:
            print(f"Orphaned modules: {result['orphaned_modules']}")
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown agent type: {agent_type}")
        return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve() if args.target else _get_project_root()
    os.environ["EPISTEMIC_TARGET_ROOT"] = str(target)
    os.environ["EPISTEMIC_AUTOMATION_PLAN"] = args.plan
    if args.focus_branch:
        os.environ["EPISTEMIC_FOCUS_BRANCH"] = args.focus_branch
    if args.objective:
        os.environ["EPISTEMIC_OBJECTIVE"] = args.objective
    if args.auto_patch is not None:
        os.environ["APEX_AUTO_PATCH"] = "1" if args.auto_patch else "0"
    if args.auto_commit is not None:
        os.environ["APEX_AUTO_COMMIT"] = "1" if args.auto_commit else "0"
    if args.max_fractal_budget is not None:
        os.environ["APEX_MAX_FRACTAL_BUDGET"] = str(args.max_fractal_budget)
    if args.safety_policy is not None:
        os.environ["APEX_SAFETY_POLICY"] = args.safety_policy
    if args.mode is not None:
        os.environ["APEX_MODE"] = args.mode
    from app.main import main

    main()
    return 0


def _consensus_status_icon(verdict_name: str) -> str:
    if verdict_name == "APPROVE":
        return "[OK]"
    if verdict_name == "REJECT":
        return "[NO]"
    return "[--]"


def _print_consensus_summary(args, evaluator, results, elapsed) -> None:
    counts = {n: 0 for n in ("APPROVE", "REJECT", "ABSTAIN")}
    cached = 0
    for r in results:
        if r.final_verdict.name in counts:
            counts[r.final_verdict.name] += 1
        if r.metadata.get("cached"):
            cached += 1

    print(f"\n=== CONSENSUS RESULTS ({args.strategy}) ===")
    print(
        f"Total: {len(results)} | Approved: {counts['APPROVE']} | Rejected: {counts['REJECT']} | Abstained: {counts['ABSTAIN']}"
    )
    if args.use_memory:
        print(
            f"Cached: {cached} | Memory entries: {evaluator.memory.stats()['total_entries']}"
        )
    print(f"Time: {elapsed:.3f}s")
    print()


def _print_consensus_result(result) -> None:
    cached_mark = " [CACHED]" if result.metadata.get("cached") else ""
    status_icon = _consensus_status_icon(result.final_verdict.name)
    print(f"{status_icon}{cached_mark} {result.claim[:80]}...")
    print(
        f"   Verdict: {result.final_verdict.name} (confidence: {result.confidence:.2f})"
    )
    for vote in result.votes:
        icon = "+" if vote.verdict.name == result.final_verdict.name else "-"
        print(
            f"   {icon} {vote.agent_name} ({vote.agent_role}): {vote.verdict.name} @ {vote.confidence:.2f} — {vote.reasoning[:60]}"
        )
    print()


def cmd_consensus(args: argparse.Namespace) -> int:
    from app.agents.evaluator import ClaimEvaluator

    import time

    memory_dir = str(_get_project_root() / ".apex") if args.use_memory else None
    evaluator = ClaimEvaluator(
        consensus_strategy=args.strategy, quorum=args.quorum, memory_dir=memory_dir
    )
    claims = args.claims.split(";") if args.claims else []
    if not claims:
        print("No claims provided. Use --claims='claim1;claim2;claim3'")
        return 1

    start = time.perf_counter()
    results = evaluator.evaluate_batch(claims)
    elapsed = time.perf_counter() - start

    _print_consensus_summary(args, evaluator, results, elapsed)
    for result in results:
        _print_consensus_result(result)

    if args.json:
        import json

        print(json.dumps([r.to_dict() for r in results], indent=2))

    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    from app.daemon import ApexDaemon

    if args.action == "start":
        if ApexDaemon.is_running():
            print("[daemon] Already running.")
            return 1
        daemon = ApexDaemon(
            goal=args.goal,
            interval_sec=args.interval,
            target=args.target or str(_get_project_root()),
            mode=args.mode,
            autonomous=not getattr(args, "legacy", False),
        )
        daemon.start()
        return 0

    if args.action == "stop":
        if ApexDaemon.stop_running():
            print("[daemon] Stopped.")
            return 0
        print("[daemon] Not running.")
        return 1

    if args.action == "status":
        if ApexDaemon.is_running():
            print("[daemon] Running.")
            return 0
        print("[daemon] Not running.")
        return 0

    print(f"Unknown daemon action: {args.action}")
    return 1


def cmd_self_audit(args: argparse.Namespace) -> int:
    from app.agents.skills.self_audit_agent import SelfAuditAgent

    target = Path(args.target).resolve() if args.target else _get_project_root()
    agent = SelfAuditAgent()
    result = agent.run(project_root=str(target))

    if args.format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        print("# Apex Self-Audit Report")
        print(f"**Target:** {target}")
        print()
        print(f"- Risks found: {len(result.get('findings', []))}")
        print(f"- Missing docstrings: {result.get('missing_docstrings_count', 0)}")
        print(f"- Long functions (>50 lines): {result.get('long_functions_count', 0)}")
        print(f"- TODOs: {result.get('todos_count', 0)}")
        cov = result.get("coverage_gap", {})
        print(f"- Tested modules: {', '.join(cov.get('tested_modules', []))}")
        print(f"- Untested modules: {', '.join(cov.get('untested_modules', []))}")
    return 0


def _docstring_write_is_sound(original: str, patched: str) -> bool:
    """True if a docstring patch is both syntactically and semantically sound.

    A bare ``ast.parse`` gate is necessary but NOT sufficient: a docstring
    mis-inserted *before* a multi-line ``def`` can land a detached module-level
    string that still parses, yet leaves the target undocumented and the file
    semantically wrong (and, with the wrong indentation, an ``IndentationError``).
    So we require, in addition to a clean parse, that the edit only ADDED
    docstrings: documented def/class count did not drop, undocumented count did
    not rise, and NO new detached (phantom) string statement appeared. A broken
    write fails one of these and is rolled back.
    """
    import ast

    def _analyze(text: str) -> tuple[int, int, int] | None:
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError, MemoryError, ValueError):
            return None
        documented = undocumented = 0
        docstring_ids: set[int] = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(getattr(body[0], "value", None), ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstring_ids.add(id(body[0]))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if ast.get_docstring(node) is None:
                    undocumented += 1
                else:
                    documented += 1
        phantom = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
            and isinstance(getattr(node, "value", None), ast.Constant)
            and isinstance(node.value.value, str)
            and id(node) not in docstring_ids
        )
        return documented, undocumented, phantom

    before = _analyze(original)
    after = _analyze(patched)
    if before is None or after is None:
        return False
    doc_b, undoc_b, phantom_b = before
    doc_a, undoc_a, phantom_a = after
    return doc_a >= doc_b and undoc_a <= undoc_b and phantom_a <= phantom_b


def _rollback_broken_docstring_writes(
    target: Path, snapshots: dict[Path, str], patched: list[str],
) -> list[str]:
    """Revert any docstring patch that is syntactically or semantically broken.

    The CLI's :class:`DocstringAgent` writes in place without a soundness gate, so
    a mishandled (e.g. multi-line) signature could land broken Python — even
    Python that still parses but detaches the docstring and corrupts the body. We
    snapshot each gap file's original bytes *before* patching, then after the run
    roll back (restore) any patched file whose new content is not a sound
    docstring-only addition (see :func:`_docstring_write_is_sound`). Returns the
    files that survived validation, so the report never claims a write that was
    reverted. Files with no snapshot / not on disk (e.g. a faked agent in tests)
    are left untouched.
    """
    survived: list[str] = []
    for rel in patched:
        full = (target / rel).resolve()
        original = snapshots.get(full)
        if original is None or not full.exists():
            survived.append(rel)
            continue
        try:
            current = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            survived.append(rel)
            continue
        if _docstring_write_is_sound(original, current):
            survived.append(rel)
            continue
        # Broken write — roll back to the pre-patch snapshot.
        try:
            full.write_text(original, encoding="utf-8")
        except OSError:
            pass
    return survived


def cmd_fix_docstrings(args: argparse.Namespace) -> int:
    from app.agents.skills import DocstringAgent

    target = Path(args.target).resolve() if args.target else _get_project_root()
    agent = DocstringAgent()

    if args.dry_run:
        result = agent.run(project_root=str(target), patch=False)
        print(f"Symbols scanned: {result['total_symbols']}")
        print(f"Gaps found: {result['gaps_found']}")
        print("(Dry run — no files modified)")
        for gap in result.get('gaps', [])[:20]:
            print(f"  {gap['file']}:{gap['line']} {gap['symbol_type']} '{gap['name']}'")
        return 0

    # Snapshot every gap file BEFORE the in-place patch so a broken write can be
    # rolled back. The agent's writer is not syntax-gated, so we validate after.
    scan = agent.run(project_root=str(target), patch=False)
    snapshots: dict[Path, str] = {}
    for gap in scan.get('gaps', []):
        full = (target / gap['file']).resolve()
        if full in snapshots or not full.exists():
            continue
        try:
            snapshots[full] = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

    result = agent.run(project_root=str(target), patch=True)
    patched = _rollback_broken_docstring_writes(
        target, snapshots, list(result['patched_files']),
    )

    print(f"Symbols scanned: {result['total_symbols']}")
    print(f"Gaps found: {result['gaps_found']}")
    print(f"Files patched: {len(patched)}")
    for f in patched:
        print(f"  patched: {f}")
    return 0


def cmd_fix_coverage(args: argparse.Namespace) -> int:
    from app.agents.skills import TestStubAgent

    target = Path(args.target).resolve() if args.target else _get_project_root()
    agent = TestStubAgent()
    result = agent.run(project_root=str(target), generate=args.generate)
    print(f"Functions scanned: {result['total_functions']}")
    print(f"Tested functions: {result['tested_functions']}")
    print(f"Coverage: {result['coverage_ratio']:.1%}")
    print(f"Gaps found: {result['gaps_found']}")
    if args.generate:
        print(f"Stubs generated: {len(result['stubs_generated'])}")
        for s in result['stubs_generated']:
            print(f"  created: {s}")
    else:
        print("(Dry run — use --generate to create test files)")
    return 0


def cmd_lsp(args: argparse.Namespace) -> int:
    from app.lsp.server import main as lsp_main

    return lsp_main()


def cmd_metrics(args: argparse.Namespace) -> int:
    from http.server import HTTPServer, BaseHTTPRequestHandler

    from app.metrics.exporter import MetricsMiddleware

    mw = MetricsMiddleware()
    mw.record_run("cli_serve", 0.0, 0, 0)

    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(mw.render().encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", args.port), MetricsHandler)
    print(f"Metrics endpoint: http://0.0.0.0:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0




def register_parsers(subparsers) -> None:
    """Register the ops family's subcommands: scan, agents, consensus, daemon,
    self-audit, fix-docstrings, fix-coverage, lsp, metrics."""
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
