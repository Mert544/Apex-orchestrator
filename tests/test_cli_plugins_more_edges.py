"""Edge-path coverage for app.cli_plugins cmd_* functions.

Deterministic, stdlib-only, no network. Network (urllib) and the
marketplace server are monkeypatched. Project root is redirected at tmp_path.
"""

from __future__ import annotations

import argparse

import app.cli_plugins as cli_plugins


def _redirect_root(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_plugins, "_get_project_root", lambda: tmp_path)


# --- cmd_plugin_install: URL branch -------------------------------------

def test_plugin_install_from_url_then_validates(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)

    def fake_urlretrieve(url, dest):
        from pathlib import Path
        Path(dest).write_text("# plugin\n")

    monkeypatch.setattr(cli_plugins.urllib.request, "urlretrieve", fake_urlretrieve)

    class Loaded:
        name = "demo"
        version = "1.0"

    monkeypatch.setattr(cli_plugins.PluginRegistry, "load", lambda self, dest: Loaded())

    args = argparse.Namespace(name="https://example.com/demo.git")
    assert cli_plugins.cmd_plugin_install(args) == 0
    out = capsys.readouterr().out
    assert "Downloaded plugin to" in out
    assert "Validated plugin: demo v1.0" in out


def test_plugin_install_from_url_download_fails(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)

    def boom(url, dest):
        raise OSError("network down")

    monkeypatch.setattr(cli_plugins.urllib.request, "urlretrieve", boom)
    args = argparse.Namespace(name="http://example.com/x.py")
    assert cli_plugins.cmd_plugin_install(args) == 1
    assert "Failed to download" in capsys.readouterr().out


def test_plugin_install_validation_failed(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)

    def fake_urlretrieve(url, dest):
        from pathlib import Path
        Path(dest).write_text("# plugin\n")

    monkeypatch.setattr(cli_plugins.urllib.request, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(cli_plugins.PluginRegistry, "load", lambda self, dest: None)

    args = argparse.Namespace(name="https://example.com/bad.git")
    assert cli_plugins.cmd_plugin_install(args) == 1
    assert "validation failed" in capsys.readouterr().out


# --- cmd_plugin_install: registry branch --------------------------------

def test_plugin_install_from_registry(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    import json

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        cli_plugins.urllib.request, "urlopen",
        lambda req, timeout=10: FakeResp({"download_url": "https://x/demo.py"}),
    )

    def fake_urlretrieve(url, dest):
        from pathlib import Path
        Path(dest).write_text("# plugin\n")

    monkeypatch.setattr(cli_plugins.urllib.request, "urlretrieve", fake_urlretrieve)

    class Loaded:
        name = "demo"
        version = "2.0"

    monkeypatch.setattr(cli_plugins.PluginRegistry, "load", lambda self, dest: Loaded())

    args = argparse.Namespace(name="demo")
    assert cli_plugins.cmd_plugin_install(args) == 0
    out = capsys.readouterr().out
    assert "Installed plugin 'demo'" in out
    assert "Validated plugin: demo v2.0" in out


def test_plugin_install_registry_not_found(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    import json

    class FakeResp:
        def read(self):
            return json.dumps({}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        cli_plugins.urllib.request, "urlopen",
        lambda req, timeout=10: FakeResp(),
    )
    args = argparse.Namespace(name="ghost")
    assert cli_plugins.cmd_plugin_install(args) == 1
    assert "not found in registry" in capsys.readouterr().out


def test_plugin_install_registry_request_error(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)

    def boom(req, timeout=10):
        raise OSError("connection refused")

    monkeypatch.setattr(cli_plugins.urllib.request, "urlopen", boom)
    args = argparse.Namespace(name="demo")
    assert cli_plugins.cmd_plugin_install(args) == 1
    assert "Failed to install from registry" in capsys.readouterr().out


# --- cmd_plugin_list ----------------------------------------------------

def test_plugin_list_no_directory(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    assert cli_plugins.cmd_plugin_list(argparse.Namespace()) == 0
    assert "No plugins directory found" in capsys.readouterr().out


def test_plugin_list_empty_directory(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    (tmp_path / "plugins").mkdir()
    assert cli_plugins.cmd_plugin_list(argparse.Namespace()) == 0
    assert "No plugins installed" in capsys.readouterr().out


def test_plugin_list_valid_and_invalid(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    pdir = tmp_path / "plugins"
    pdir.mkdir()
    (pdir / "good.py").write_text("# good\n")
    (pdir / "bad.py").write_text("# bad\n")

    class Loaded:
        name = "good"
        version = "1.0"
        description = "a good plugin"

    def fake_load(self, f):
        return Loaded() if f.name == "good.py" else None

    monkeypatch.setattr(cli_plugins.PluginRegistry, "load", fake_load)
    assert cli_plugins.cmd_plugin_list(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "good (1.0) — a good plugin" in out
    assert "bad.py (invalid)" in out


# --- cmd_plugin_uninstall -----------------------------------------------

def test_plugin_uninstall_found(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    pdir = tmp_path / "plugins"
    pdir.mkdir()
    (pdir / "demo.py").write_text("# demo\n")
    args = argparse.Namespace(name="demo")
    assert cli_plugins.cmd_plugin_uninstall(args) == 0
    assert "Uninstalled plugin 'demo'" in capsys.readouterr().out
    assert not (pdir / "demo.py").exists()


def test_plugin_uninstall_missing(monkeypatch, tmp_path, capsys):
    _redirect_root(monkeypatch, tmp_path)
    (tmp_path / "plugins").mkdir()
    args = argparse.Namespace(name="ghost")
    assert cli_plugins.cmd_plugin_uninstall(args) == 1
    assert "not found" in capsys.readouterr().out


# --- cmd_marketplace: serve loop interrupted, then stop -----------------

def test_cmd_marketplace_serves_then_stops(monkeypatch, capsys):
    stopped = {"n": 0}

    class FakeServer:
        def __init__(self, *, host, port, plugin_dir):
            self.host = host
            self.port = port
            self.plugin_dir = plugin_dir

        def start(self):
            pass

        def stop(self):
            stopped["n"] += 1

    monkeypatch.setattr("app.plugins.marketplace_server.PluginMarketplaceServer", FakeServer)

    # Make the idle loop's sleep raise immediately so we exit deterministically.
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))

    args = argparse.Namespace(port=8799, plugin_dir="plugins")
    assert cli_plugins.cmd_marketplace(args) == 0
    assert stopped["n"] == 1
    assert "Marketplace server" in capsys.readouterr().out


# --- cmd_hook -----------------------------------------------------------

def test_cmd_hook_install_failure(monkeypatch, tmp_path, capsys):
    def boom(target):
        raise RuntimeError("not a git repo")

    monkeypatch.setattr("app.hook_installer.GitHookInstaller.install", staticmethod(boom))
    args = argparse.Namespace(target=str(tmp_path), action="install")
    assert cli_plugins.cmd_hook(args) == 1
    assert "Failed to install" in capsys.readouterr().out


def test_cmd_hook_uninstall_no_hook(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "app.hook_installer.GitHookInstaller.uninstall", staticmethod(lambda target: False)
    )
    args = argparse.Namespace(target=str(tmp_path), action="uninstall")
    assert cli_plugins.cmd_hook(args) == 1
    assert "No Apex hook found" in capsys.readouterr().out
