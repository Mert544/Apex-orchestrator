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
import urllib.request
from pathlib import Path

from app.plugins.registry import PluginRegistry


from app.cli_autonomy import (  # noqa: F401  (re-exports: import surface unchanged)
    _working_tree_clean,
    cmd_auto,
    cmd_evolve,
    cmd_maintain,
    cmd_simulate,
)
from app.cli_common import _get_project_root  # noqa: F401  (re-export)
from app.cli_refactor import cmd_move, cmd_rename  # noqa: F401  (re-exports)


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


def cmd_plugin_install(args: argparse.Namespace) -> int:
    registry = PluginRegistry()
    name_or_url = args.name
    plugin_dir = _get_project_root() / "plugins"
    plugin_dir.mkdir(exist_ok=True)

    # Determine if URL or name
    if name_or_url.startswith(("http://", "https://", "git@")):
        # Download from URL
        dest = plugin_dir / f"{args.name.split('/')[-1].replace('.git', '')}.py"
        try:
            urllib.request.urlretrieve(name_or_url, str(dest))
            print(f"Downloaded plugin to {dest}")
        except Exception as exc:
            print(f"Failed to download: {exc}")
            return 1
    else:
        # Query registry index
        registry_url = os.getenv("APEX_REGISTRY_URL", "http://localhost:8765")
        try:
            req = urllib.request.Request(f"{registry_url}/plugins/{name_or_url}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
            download_url = meta.get("download_url", "")
            if not download_url:
                print(f"Plugin '{name_or_url}' not found in registry")
                return 1
            dest = plugin_dir / f"{name_or_url}.py"
            urllib.request.urlretrieve(download_url, str(dest))
            print(f"Installed plugin '{name_or_url}' to {dest}")
        except Exception as exc:
            print(f"Failed to install from registry: {exc}")
            return 1

    # Validate
    loaded = registry.load(dest)
    if loaded:
        print(f"Validated plugin: {loaded.name} v{loaded.version}")
        return 0
    print("Plugin loaded but validation failed — check for register() function")
    return 1


def cmd_plugin_list(_args: argparse.Namespace) -> int:
    plugin_dir = _get_project_root() / "plugins"
    if not plugin_dir.exists():
        print("No plugins directory found")
        return 0
    files = sorted(plugin_dir.glob("*.py"))
    if not files:
        print("No plugins installed")
        return 0
    registry = PluginRegistry()
    for f in files:
        loaded = registry.load(f)
        if loaded:
            print(f"  {loaded.name} ({loaded.version}) — {loaded.description}")
        else:
            print(f"  {f.name} (invalid)")
    return 0


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

    approved = [r for r in results if r.final_verdict.name == "APPROVE"]
    rejected = [r for r in results if r.final_verdict.name == "REJECT"]
    abstained = [r for r in results if r.final_verdict.name == "ABSTAIN"]
    cached = [r for r in results if r.metadata.get("cached")]

    print(f"\n=== CONSENSUS RESULTS ({args.strategy}) ===")
    print(
        f"Total: {len(results)} | Approved: {len(approved)} | Rejected: {len(rejected)} | Abstained: {len(abstained)}"
    )
    if args.use_memory:
        print(
            f"Cached: {len(cached)} | Memory entries: {evaluator.memory.stats()['total_entries']}"
        )
    print(f"Time: {elapsed:.3f}s")
    print()

    for result in results:
        cached_mark = " [CACHED]" if result.metadata.get("cached") else ""
        status_icon = (
            "[OK]"
            if result.final_verdict.name == "APPROVE"
            else "[NO]"
            if result.final_verdict.name == "REJECT"
            else "[--]"
        )
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

    if args.json:
        import json

        print(json.dumps([r.to_dict() for r in results], indent=2))

    return 0


def cmd_plugin_uninstall(args: argparse.Namespace) -> int:
    plugin_dir = _get_project_root() / "plugins"
    target = plugin_dir / f"{args.name}.py"
    if target.exists():
        target.unlink()
        print(f"Uninstalled plugin '{args.name}'")
        return 0
    print(f"Plugin '{args.name}' not found")
    return 1


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


def cmd_fix_docstrings(args: argparse.Namespace) -> int:
    from app.agents.skills import DocstringAgent

    target = Path(args.target).resolve() if args.target else _get_project_root()
    agent = DocstringAgent()
    result = agent.run(project_root=str(target), patch=not args.dry_run)
    print(f"Symbols scanned: {result['total_symbols']}")
    print(f"Gaps found: {result['gaps_found']}")
    if not args.dry_run:
        print(f"Files patched: {len(result['patched_files'])}")
        for f in result['patched_files']:
            print(f"  patched: {f}")
    else:
        print("(Dry run — no files modified)")
        for gap in result.get('gaps', [])[:20]:
            print(f"  {gap['file']}:{gap['line']} {gap['symbol_type']} '{gap['name']}'")
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


def cmd_marketplace(args: argparse.Namespace) -> int:
    from app.plugins.marketplace_server import PluginMarketplaceServer

    server = PluginMarketplaceServer(host="0.0.0.0", port=args.port, plugin_dir=args.plugin_dir)
    server.start()
    print(f"Marketplace server: http://0.0.0.0:{args.port}")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    from app.hook_installer import GitHookInstaller

    target = Path(args.target).resolve() if args.target else _get_project_root()

    if args.action == "install":
        try:
            path = GitHookInstaller.install(target)
            print(f"[hook] Installed pre-commit hook to {path}")
            return 0
        except Exception as exc:
            print(f"[hook] Failed to install: {exc}")
            return 1

    if args.action == "uninstall":
        if GitHookInstaller.uninstall(target):
            print("[hook] Uninstalled pre-commit hook.")
            return 0
        print("[hook] No Apex hook found.")
        return 1

    print(f"Unknown hook action: {args.action}")
    return 1


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
    rows = find_dead_code(str(target), limit=args.limit)
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
    html_doc = build_city(str(target), objective=args.objective or None)
    out_path = Path(args.out) if args.out else target / ".apex" / "city.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"[city] Written to {out_path}")
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


def cmd_review(args: argparse.Namespace) -> int:
    """Review only the lines changed since a base ref — Apex as a PR reviewer."""
    from app.engine.diff_review import render_review_markdown, review

    target = Path(args.target).resolve() if args.target else _get_project_root()
    result = review(str(target), base=getattr(args, "base", "HEAD") or "HEAD")

    # --fix: apply the auto-fixable findings on the changed files, test-verified.
    fix_report = None
    if getattr(args, "fix", False):
        fix_report = _apply_review_fixes(str(target), result)

    # --sarif: export findings for GitHub code scanning / CI dashboards.
    sarif_out = getattr(args, "sarif", "")
    if sarif_out:
        from app.engine.sarif_export import review_to_sarif

        sarif_path = Path(sarif_out)
        sarif_path.parent.mkdir(parents=True, exist_ok=True)
        sarif_path.write_text(json.dumps(review_to_sarif(result), indent=2) + "\n",
                              encoding="utf-8")

    if args.json:
        payload = result.to_dict()
        if fix_report is not None:
            payload["fixes"] = fix_report
        print(json.dumps(payload, indent=2))
    else:
        print(render_review_markdown(result))
        if fix_report is not None:
            print(_render_review_fixes_markdown(fix_report))
        if sarif_out:
            print(f"[review] SARIF written to {sarif_out}")
    # Non-zero exit when high-severity issues land in the diff (CI-friendly).
    if getattr(args, "fail_on_high", False) and any(f.severity == "high" for f in result.findings):
        return 1
    return 0


def _apply_review_fixes(target: str, result) -> dict:
    """Apply the auto-fixable review findings on the changed files (verified)."""
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionStep

    bridge = IdeaActionBridge()
    files = sorted({f.file for f in result.findings if f.auto_fixable and f.file.endswith(".py")})
    applied: list[dict] = []
    # harden_security runs the detection ladder (security → mutable-default →
    # modernization); add_docstring covers the docs findings. Loop a couple of
    # passes per file so multiple distinct issues in one file get fixed.
    for rel in files:
        # Re-run the harden ladder until it stops finding something to fix (it
        # fixes one issue per pass: eval, then mutable-default, then == None …),
        # capped to avoid any loop. Then one docstring pass.
        for _ in range(4):
            step = ActionStep(branch_path="review", title=f"fix {rel}", operator="harden",
                              subject=rel, action_type="harden_security", target=rel, executable=True)
            r = bridge.apply_step(step, target, mode="supervised", verify=True)
            if not r.get("applied"):
                break
            applied.append({"file": rel, "transform": r.get("transform_type")})
        doc = ActionStep(branch_path="review", title=f"doc {rel}", operator="document",
                         subject=rel, action_type="add_docstring", target=rel, executable=True)
        rd = bridge.apply_step(doc, target, mode="supervised", verify=True)
        if rd.get("applied"):
            applied.append({"file": rel, "transform": rd.get("transform_type")})
    return {"applied": applied, "applied_count": len(applied),
            "files_touched": sorted({a["file"] for a in applied})}


def _render_review_fixes_markdown(fix: dict) -> str:
    if not fix.get("applied"):
        return "\n_No auto-fixes applied (nothing verified cleanly, or nothing fixable)._\n"
    lines = [f"\n## 🔧 Applied {fix['applied_count']} fix(es) (test-verified)"]
    for a in fix["applied"]:
        lines.append(f"- `{a['file']}` — {a['transform']}")
    lines.append("")
    return "\n".join(lines)


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


def cmd_ideate(args: argparse.Namespace) -> int:
    """Generate a permutation tree of development ideas from the codebase."""
    from app.engine.idea_permutation import (
        IdeaPermutationEngine,
        render_markdown,
        render_mermaid,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()

    # Plugins may contribute extra development operators to the alphabet.
    from app.plugins.registry import PluginRegistry

    plugins = PluginRegistry()
    plugins.load_all()
    extra_operators = plugins.idea_operators()

    engine = IdeaPermutationEngine(
        config={
            "max_total_ideas": args.max_ideas,
            "max_idea_depth": args.depth,
            "breadth": args.breadth,
            "min_relevance": args.min_relevance,
            "fractal_facets": getattr(args, "facets", False),
            "facet_depth": getattr(args, "facet_depth", 1),
            "adaptive_depth": getattr(args, "adaptive", False),
        },
        project_root=str(target),
        extra_operators=extra_operators,
    )
    report = engine.run(objective=args.objective or None)

    # --roadmap (without --actions): view the prioritized, phase-ordered plan.
    # With --actions, the roadmap instead drives the *order* of the action plan
    # below (Stabilize first), so this view-only branch is skipped.
    if getattr(args, "roadmap", False) and not getattr(args, "actions", False):
        from app.engine.idea_roadmap import (
            RoadmapSynthesizer,
            render_roadmap_markdown,
        )

        roadmap = RoadmapSynthesizer().build(report)
        snapshot_path = target / ".apex" / "roadmap-snapshot.json"

        # --diff: compare this roadmap against the last saved snapshot.
        if getattr(args, "diff", False):
            from app.engine.roadmap_history import (
                diff_roadmaps,
                load_snapshot,
                render_diff_markdown,
            )

            previous = load_snapshot(snapshot_path)
            if previous is None:
                print(
                    "[ideate] No saved roadmap snapshot to diff against. "
                    "Run with --save first."
                )
                return 1
            diff = diff_roadmaps(previous, roadmap)
            if args.json:
                print(json.dumps(diff.to_dict(), indent=2))
            else:
                print(render_diff_markdown(diff))
            return 0

        body = render_roadmap_markdown(roadmap)
        if args.json:
            print(json.dumps(roadmap.to_dict(), indent=2))
        else:
            print(body)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(body, encoding="utf-8")
            print(f"\n[ideate] Roadmap written to {out_path}")
        # --save: snapshot for future --diff comparisons.
        if getattr(args, "save", False):
            from app.engine.roadmap_history import snapshot_roadmap

            saved = snapshot_roadmap(roadmap, snapshot_path)
            print(f"\n[ideate] Roadmap snapshot saved to {saved}")
        return 0

    # --invest: the impact-vs-effort investment curve + diminishing-returns knee.
    if getattr(args, "invest", False):
        from app.engine.idea_investment import (
            investment_curve,
            render_investment_markdown,
        )

        points = investment_curve(report)
        if args.json:
            print(json.dumps([p.to_dict() for p in points], indent=2))
        else:
            print(render_investment_markdown(points))
        return 0

    # --budget: optimal portfolio of ideas for an effort budget (knapsack).
    if getattr(args, "budget", 0.0):
        from app.engine.idea_portfolio import (
            optimize_portfolio,
            render_portfolio_markdown,
        )

        portfolio = optimize_portfolio(report, float(args.budget))
        if args.json:
            print(json.dumps(portfolio.to_dict(), indent=2))
        else:
            print(render_portfolio_markdown(portfolio))
        return 0

    # --sequence: dependency-ordered execution plan (prerequisites first).
    if getattr(args, "sequence", False):
        from app.engine.idea_dependencies import (
            execution_order,
            render_execution_markdown,
        )

        steps = execution_order(report.ideas)
        if args.json:
            print(json.dumps([s.to_dict() for s in steps], indent=2))
        else:
            print(render_execution_markdown(steps))
        return 0

    # --pareto: the efficient frontier of ideas across impact/effort/value.
    if getattr(args, "pareto", False):
        from app.engine.idea_pareto import frontier_from_roadmap, render_pareto_markdown
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = RoadmapSynthesizer().build(report)
        points = frontier_from_roadmap(roadmap)
        if args.json:
            print(json.dumps([p.to_dict() for p in points], indent=2))
        else:
            print(render_pareto_markdown(points, total_ideas=len(report.ideas)))
        return 0

    # --shape: report on the shape/health of the tree the engine just produced.
    if getattr(args, "shape", False):
        from app.engine.idea_tree_shape import (
            analyze_tree_shape,
            render_tree_shape_markdown,
        )

        shape = analyze_tree_shape(report)
        if args.json:
            print(json.dumps(shape.to_dict(), indent=2))
        else:
            print(render_tree_shape_markdown(shape))
        return 0

    # --kind: list only ideas of a given kind (permutation/synthesis/pair),
    # value-sorted. A focused view onto what the engine surfaced.
    kind = getattr(args, "kind", "") or ""
    if kind and kind != "all":
        selected = sorted(
            (i for i in report.ideas if i.kind == kind),
            key=lambda n: n.value,
            reverse=True,
        )
        if args.json:
            print(json.dumps([i.to_dict() for i in selected], indent=2))
        else:
            print(f"# {kind} ideas for `{target}`  ({len(selected)} found)")
            for i in selected:
                caveat = f"  ⚠ {i.caveats[0]}" if i.caveats else ""
                print(f"- `{i.branch_path}` [{i.operator}] {i.title}  (v {i.value}){caveat}")
        return 0

    # Optionally bridge ideas into a supervised, never-applied action plan.
    action_plan = None
    apply_results = None
    if getattr(args, "actions", False):
        from app.engine.idea_action_bridge import (
            IdeaActionBridge,
            render_action_markdown,
        )

        bridge = IdeaActionBridge()
        _plan_mode = getattr(args, "mode", None) or "supervised"
        _draft = getattr(args, "draft", False) or getattr(args, "apply", False)
        if getattr(args, "roadmap", False):
            # Roadmap-ordered plan: apply Stabilize→Secure→Evolve→Refine, with an
            # optional --phase filter to act on a single phase.
            action_plan = bridge.plan_roadmap(
                report,
                phase=getattr(args, "phase", None) or None,
                mode=_plan_mode,
                top=args.top or None,
                draft=_draft,
                project_root=str(target),
            )
        else:
            action_plan = bridge.plan_tree(
                report,
                mode=_plan_mode,
                top=args.top or None,
                draft=_draft,
                project_root=str(target),
            )
        # Strictly opt-in apply: only when --apply is passed; gated by mode + safety.
        if getattr(args, "apply", False):
            apply_results = bridge.apply_plan(
                action_plan,
                str(target),
                mode=getattr(args, "mode", None) or "supervised",
                verify=getattr(args, "verify", False),
                max_apply=(args.max_apply or None) if getattr(args, "max_apply", 0) else None,
                commit=getattr(args, "commit", False),
            )

    if args.json:
        payload = report.model_dump()
        if action_plan is not None:
            payload["action_plan"] = action_plan.model_dump()
        if apply_results is not None:
            payload["apply_results"] = apply_results
        print(json.dumps(payload, indent=2))
    elif action_plan is not None:
        print(render_action_markdown(action_plan))
        if apply_results is not None:
            verify_note = " · verified" if apply_results.get("verify") else ""
            commit_note = (
                f" · committed {apply_results.get('committed', 0)}"
                if apply_results.get("commit") else ""
            )
            print(
                f"\n## Maintenance run (mode: {apply_results.get('mode')}{verify_note}{commit_note})\n"
                f"applied {apply_results['applied']} · rolled back "
                f"{apply_results['rolled_back']} · blocked {apply_results['blocked']} "
                f"of {apply_results['total_executable']} executable steps"
            )
            for r in apply_results["results"]:
                if r.get("rolled_back"):
                    status = "↩️"
                elif r.get("applied"):
                    status = "✅"
                else:
                    status = "⛔"
                detail = r.get("reason") or ", ".join(r.get("changed_files", []))
                if r.get("verified") is True:
                    detail += "  (tests pass)"
                if r.get("committed"):
                    detail += f"  [committed {r.get('commit_hash', '')}]"
                print(f"- {status} `{r['branch']}` {r['action']} — {detail}")
    else:
        print(render_markdown(report))
        if args.mermaid:
            print()
            print(render_mermaid(report))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if action_plan is not None:
            body = render_action_markdown(action_plan)
        else:
            body = render_markdown(report)
            if args.mermaid:
                body += "\n\n" + render_mermaid(report)
        out_path.write_text(body, encoding="utf-8")
        print(f"\n[ideate] Written to {out_path}")
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
