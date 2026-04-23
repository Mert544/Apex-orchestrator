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


def cmd_plugin_uninstall(args: argparse.Namespace) -> int:
    plugin_dir = _get_project_root() / "plugins"
    target = plugin_dir / f"{args.name}.py"
    if target.exists():
        target.unlink()
        print(f"Uninstalled plugin '{args.name}'")
        return 0
    print(f"Plugin '{args.name}' not found")
    return 1


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

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
