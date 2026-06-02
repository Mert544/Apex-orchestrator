from __future__ import annotations

import argparse

import app.cli as cli
from app.cli import (
    cmd_consensus,
    cmd_daemon,
    cmd_lsp,
    cmd_marketplace,
    cmd_metrics,
    cmd_plugin_install,
    cmd_plugin_uninstall,
)


def test_plugin_install_url_download_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    args = argparse.Namespace(name="https://example.invalid/p.git")
    # No network in the sandbox -> urlretrieve raises -> graceful failure.
    rc = cmd_plugin_install(args)
    assert rc == 1
    assert "Failed to download" in capsys.readouterr().out


def test_plugin_install_registry_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    monkeypatch.setenv("APEX_REGISTRY_URL", "http://localhost:1")  # nothing listening
    rc = cmd_plugin_install(argparse.Namespace(name="some-plugin"))
    assert rc == 1
    assert "Failed to install from registry" in capsys.readouterr().out


def test_plugin_uninstall_not_found(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    rc = cmd_plugin_uninstall(argparse.Namespace(name="ghost"))
    assert rc == 1
    assert "not found" in capsys.readouterr().out


def test_consensus_no_claims(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    args = argparse.Namespace(
        claims="", strategy="majority", quorum=2, use_memory=False, json=False
    )
    rc = cmd_consensus(args)
    assert rc == 1
    assert "No claims" in capsys.readouterr().out


def test_consensus_with_claims_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    args = argparse.Namespace(
        claims="The function is documented;The code has no eval",
        strategy="majority",
        quorum=2,
        use_memory=False,
        json=True,
    )
    rc = cmd_consensus(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "CONSENSUS RESULTS" in out


def test_daemon_status_not_running(monkeypatch, capsys):
    from app.daemon import ApexDaemon

    monkeypatch.setattr(ApexDaemon, "is_running", staticmethod(lambda: False))
    rc = cmd_daemon(argparse.Namespace(action="status"))
    assert rc == 0
    assert "Not running" in capsys.readouterr().out


def test_daemon_unknown_action(capsys):
    rc = cmd_daemon(argparse.Namespace(action="frobnicate"))
    assert rc == 1
    assert "Unknown daemon action" in capsys.readouterr().out


def test_lsp_delegates_to_server_main(monkeypatch):
    import app.lsp.server as lsp_server

    monkeypatch.setattr(lsp_server, "main", lambda: 0)
    assert cmd_lsp(argparse.Namespace()) == 0


def test_metrics_serves_then_shuts_down(monkeypatch, capsys):
    import http.server as hs

    class _Server:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

    monkeypatch.setattr(hs, "HTTPServer", _Server)
    rc = cmd_metrics(argparse.Namespace(port=0))
    assert rc == 0
    assert "Metrics endpoint" in capsys.readouterr().out


def test_marketplace_serves_then_shuts_down(monkeypatch, capsys):
    import app.plugins.marketplace_server as ms

    class _Server:
        def __init__(self, host, port, plugin_dir):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(ms, "PluginMarketplaceServer", _Server)
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt))
    rc = cmd_marketplace(argparse.Namespace(port=0, plugin_dir=""))
    assert rc == 0
    assert "Marketplace server" in capsys.readouterr().out
