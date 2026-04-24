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
        if result['patched_files']:
            print(f"Patched {len(result['patched_files'])} files: {result['patched_files']}")
        print(json.dumps(result, indent=2))

    elif agent_type == "test-stub":
        from app.agents.skills import TestStubAgent
        agent = TestStubAgent()
        result = agent.run(project_root=target, generate=args.generate)
        print(f"Coverage: {result['coverage_ratio'] * 100:.0f}% ({result['tested_functions']}/{result['total_functions']})")
        if result['stubs_generated']:
            print(f"Generated {len(result['stubs_generated'])} test stubs: {result['stubs_generated']}")
        print(json.dumps(result, indent=2))

    elif agent_type == "dependency":
        from app.agents.skills import DependencyAgent
        agent = DependencyAgent()
        result = agent.run(project_root=target)
        print(f"Modules: {result['total_modules']}, Edges: {result['total_edges']}")
        if result['circular_imports']:
            print(f"Circular imports detected: {len(result['circular_imports'])}")
        if result['orphaned_modules']:
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
    # Delegate to main
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
    evaluator = ClaimEvaluator(consensus_strategy=args.strategy, quorum=args.quorum, memory_dir=memory_dir)
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
    print(f"Total: {len(results)} | Approved: {len(approved)} | Rejected: {len(rejected)} | Abstained: {len(abstained)}")
    if args.use_memory:
        print(f"Cached: {len(cached)} | Memory entries: {evaluator.memory.stats()['total_entries']}")
    print(f"Time: {elapsed:.3f}s")
    print()

    for result in results:
        cached_mark = " [CACHED]" if result.metadata.get("cached") else ""
        status_icon = "[OK]" if result.final_verdict.name == "APPROVE" else "[NO]" if result.final_verdict.name == "REJECT" else "[--]"
        print(f"{status_icon}{cached_mark} {result.claim[:80]}...")
        print(f"   Verdict: {result.final_verdict.name} (confidence: {result.confidence:.2f})")
        for vote in result.votes:
            icon = "+" if vote.verdict.name == result.final_verdict.name else "-"
            print(f"   {icon} {vote.agent_name} ({vote.agent_role}): {vote.verdict.name} @ {vote.confidence:.2f} — {vote.reasoning[:60]}")
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


def cmd_run(args: argparse.Namespace) -> int:
    from app.intent.parser import IntentParser

    target = Path(args.target).resolve() if args.target else _get_project_root()
    parser = IntentParser()
    intent = parser.parse(args.goal, explicit_mode=args.mode)

    print(f"\n=== APEX ORCHESTRATOR — AUTONOMOUS RUN ===")
    print(f"Goal: {intent.goal}")
    print(f"Plan: {intent.plan_type}")
    print(f"Agents: {', '.join(intent.agents) if intent.agents else 'all available'}")
    print(f"Mode: {intent.mode}")
    print(f"Rationale: {intent.rationale}")
    print()

    # Adjust plan for report mode (no patching)
    plan = intent.plan_type
    if intent.mode == "report" and plan in ("full_autonomous_loop", "semantic_patch_loop", "self_directed_loop"):
        plan = "project_scan"
        print("[report mode] Patching disabled. Using project_scan instead.")

    os.environ["EPISTEMIC_TARGET_ROOT"] = str(target)
    os.environ["EPISTEMIC_AUTOMATION_PLAN"] = plan
    os.environ["EPISTEMIC_OBJECTIVE"] = intent.goal

    # TODO: supervised mode interactive confirmation (Phase C)
    if intent.mode == "supervised":
        print("[supervised mode] Running with human oversight. Patches will be staged, not committed.")

    if intent.mode == "autonomous":
        print("[autonomous mode] Full automation enabled. Changes will be applied automatically.")

    from app.main import main
    main()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="apex", description="Apex Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Run an automation plan")
    scan_parser.add_argument("--plan", default="project_scan", help="Automation plan name")
    scan_parser.add_argument("--target", default="", help="Target project root")
    scan_parser.add_argument("--focus-branch", default="", help="Focus branch path")
    scan_parser.add_argument("--objective", default="", help="Scan objective")
    scan_parser.set_defaults(func=cmd_scan)

    # agents
    agents_parser = subparsers.add_parser("agents", help="Run helper agents")
    agents_parser.add_argument("agent_type", choices=["security", "docstring", "test-stub", "dependency"], help="Agent type")
    agents_parser.add_argument("--target", default="", help="Target project root")
    agents_parser.add_argument("--patch", action="store_true", help="Apply patches (docstring agent)")
    agents_parser.add_argument("--generate", action="store_true", help="Generate stubs (test-stub agent)")
    agents_parser.set_defaults(func=cmd_agents)

    # consensus
    consensus_parser = subparsers.add_parser("consensus", help="Evaluate claims via agent consensus")
    consensus_parser.add_argument("--claims", required=True, help="Semicolon-separated claims to evaluate")
    consensus_parser.add_argument("--strategy", default="majority", choices=["unanimous", "majority", "supermajority", "weighted", "threshold"], help="Consensus strategy")
    consensus_parser.add_argument("--quorum", type=int, default=2, help="Minimum votes required")
    consensus_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    consensus_parser.add_argument("--use-memory", action="store_true", help="Enable persistent agent memory for caching and learning")
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
    run_parser = subparsers.add_parser("run", help="Run Apex autonomously based on a natural-language goal")
    run_parser.add_argument("--goal", required=True, help="Natural-language goal, e.g. 'security audit', 'fix docstrings'")
    run_parser.add_argument("--target", default="", help="Target project root")
    run_parser.add_argument("--mode", default="supervised", choices=["report", "supervised", "autonomous"], help="Execution mode")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
