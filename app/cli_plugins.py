"""Plugin-family commands: install/list/uninstall, marketplace, hooks.

Extracted from the `app/cli.py` monolith — the engine's own #1 convergence
target (central dependency hub × high churn). Pure mechanical move:
`app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

from app.cli_common import _get_project_root
from app.plugins.registry import PluginRegistry

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


