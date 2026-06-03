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
from app.utils.yaml_utils import load_yaml


def _get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_config() -> dict:
    root = _get_project_root()
    return load_yaml(root / "config" / "default.yaml")


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
    try:
        from app.agents.skills import SecurityAgent

        sec_n = int(SecurityAgent().run(project_root=str(target)).get("findings_count", 0) or 0)
    except Exception:
        sec_n = 0

    # --- Narrative: the state of the project ---------------------------------
    lines = [f"# Apex — autonomous review of `{target}`", ""]
    if goal:
        lines.append(f"_goal: {goal}_\n")
    headline = (
        f"**State:** {shape.total_ideas} development ideas across "
        f"{shape.distinct_subjects} modules · {sec_n} security finding(s)"
    )
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
    md = render_maintenance_markdown(summary, str(target), objective=goal)
    if emit_json:
        print(json.dumps({**summary, "decision": decision.to_dict()}, indent=2))
    else:
        print(f"_Apex is applying autonomously: {decision.reason}._\n")
        print(md)
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
