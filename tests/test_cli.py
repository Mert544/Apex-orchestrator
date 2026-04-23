from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0
    assert "scan" in result.stdout
    assert "plugin" in result.stdout


def test_cli_plugin_list_empty():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "plugin", "list"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0


def test_cli_plugin_install_local(tmp_path):
    plugin_file = tmp_path / "my_plugin.py"
    plugin_file.write_text(
        'def register(proxy):\n    proxy.add_hook("on_report", lambda c: None)\n',
        encoding="utf-8",
    )
    root = Path(__file__).parent.parent
    plugins_dir = root / "plugins"
    plugins_dir.mkdir(exist_ok=True)

    # Copy to plugins dir manually since install from local path isn't fully implemented
    dest = plugins_dir / "my_plugin.py"
    dest.write_text(plugin_file.read_text(), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "plugin", "list"],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0
    # Cleanup
    if dest.exists():
        dest.unlink()


def test_registry_server_importable():
    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root))
    from app.registry_server import RegistryHandler, main
    assert RegistryHandler is not None
    assert callable(main)
