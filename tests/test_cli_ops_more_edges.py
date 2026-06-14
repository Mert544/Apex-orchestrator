"""Edge-path coverage for app.cli_ops cmd_* dispatch functions.

Deterministic, stdlib-only, no network. Heavy/external work (scanners,
agents, servers, subprocess) is monkeypatched so tests stay fast.
"""

from __future__ import annotations

import argparse

import app.cli_ops as cli_ops


# --- cmd_agents: per-branch print paths ---------------------------------

def test_cmd_agents_docstring_reports_patched_files(monkeypatch, capsys):
    class FakeDocstringAgent:
        def run(self, *, project_root, patch):
            return {"gaps_found": 2, "patched_files": ["a.py", "b.py"]}

    monkeypatch.setattr("app.agents.skills.DocstringAgent", FakeDocstringAgent)
    args = argparse.Namespace(target="", agent_type="docstring", patch=True)
    assert cli_ops.cmd_agents(args) == 0
    out = capsys.readouterr().out
    assert "Patched 2 files" in out


def test_cmd_agents_test_stub_reports_generated(monkeypatch, capsys):
    class FakeTestStubAgent:
        def run(self, *, project_root, generate):
            return {
                "coverage_ratio": 0.5,
                "tested_functions": 1,
                "total_functions": 2,
                "stubs_generated": ["t_a.py"],
            }

    monkeypatch.setattr("app.agents.skills.TestStubAgent", FakeTestStubAgent)
    args = argparse.Namespace(target="", agent_type="test-stub", generate=True)
    assert cli_ops.cmd_agents(args) == 0
    out = capsys.readouterr().out
    assert "Generated 1 test stubs" in out
    assert "Coverage: 50%" in out


def test_cmd_agents_dependency_reports_circular_and_orphans(monkeypatch, capsys):
    class FakeDependencyAgent:
        def run(self, *, project_root):
            return {
                "total_modules": 3,
                "total_edges": 4,
                "circular_imports": [["a", "b"]],
                "orphaned_modules": ["c"],
            }

    monkeypatch.setattr("app.agents.skills.DependencyAgent", FakeDependencyAgent)
    args = argparse.Namespace(target="", agent_type="dependency")
    assert cli_ops.cmd_agents(args) == 0
    out = capsys.readouterr().out
    assert "Circular imports detected: 1" in out
    assert "Orphaned modules: ['c']" in out


# --- cmd_scan: threads CLI flags into environment variables -------------

def test_cmd_scan_sets_environment_and_calls_main(monkeypatch):
    calls = {"main": 0}
    monkeypatch.setattr("app.main.main", lambda: calls.__setitem__("main", calls["main"] + 1))

    args = argparse.Namespace(
        target="",
        plan="project_scan",
        focus_branch="feature/x",
        objective="harden",
        auto_patch=True,
        auto_commit=False,
        max_fractal_budget=7,
        safety_policy="strict",
        mode="autonomous",
    )
    assert cli_ops.cmd_scan(args) == 0
    assert calls["main"] == 1
    import os
    assert os.environ["EPISTEMIC_AUTOMATION_PLAN"] == "project_scan"
    assert os.environ["EPISTEMIC_FOCUS_BRANCH"] == "feature/x"
    assert os.environ["EPISTEMIC_OBJECTIVE"] == "harden"
    assert os.environ["APEX_AUTO_PATCH"] == "1"
    assert os.environ["APEX_AUTO_COMMIT"] == "0"
    assert os.environ["APEX_MAX_FRACTAL_BUDGET"] == "7"
    assert os.environ["APEX_SAFETY_POLICY"] == "strict"
    assert os.environ["APEX_MODE"] == "autonomous"


def test_cmd_scan_omits_optional_flags(monkeypatch):
    monkeypatch.setattr("app.main.main", lambda: None)
    args = argparse.Namespace(
        target="",
        plan="p",
        focus_branch="",
        objective="",
        auto_patch=None,
        auto_commit=None,
        max_fractal_budget=None,
        safety_policy=None,
        mode=None,
    )
    assert cli_ops.cmd_scan(args) == 0


# --- cmd_daemon: start / stop / status / unknown ------------------------

def _patch_daemon(monkeypatch, *, running, stop_running=False, started=None):
    class FakeDaemon:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            if started is not None:
                started.update(kwargs)

        @staticmethod
        def is_running():
            return running

        @staticmethod
        def stop_running():
            return stop_running

        def start(self):
            if started is not None:
                started["started"] = True

    monkeypatch.setattr("app.daemon.ApexDaemon", FakeDaemon)


def test_cmd_daemon_start_when_already_running(monkeypatch, capsys):
    _patch_daemon(monkeypatch, running=True)
    args = argparse.Namespace(action="start", goal="g", interval=10, target="", mode="report")
    assert cli_ops.cmd_daemon(args) == 1
    assert "Already running" in capsys.readouterr().out


def test_cmd_daemon_start_launches(monkeypatch):
    started: dict = {}
    _patch_daemon(monkeypatch, running=False, started=started)
    args = argparse.Namespace(action="start", goal="g", interval=10, target="/tmp/x", mode="report", legacy=False)
    assert cli_ops.cmd_daemon(args) == 0
    assert started.get("started") is True
    assert started["autonomous"] is True


def test_cmd_daemon_start_legacy_disables_autonomous(monkeypatch):
    started: dict = {}
    _patch_daemon(monkeypatch, running=False, started=started)
    args = argparse.Namespace(action="start", goal="g", interval=10, target="", mode="report", legacy=True)
    assert cli_ops.cmd_daemon(args) == 0
    assert started["autonomous"] is False


def test_cmd_daemon_stop_when_running(monkeypatch, capsys):
    _patch_daemon(monkeypatch, running=False, stop_running=True)
    args = argparse.Namespace(action="stop")
    assert cli_ops.cmd_daemon(args) == 0
    assert "Stopped" in capsys.readouterr().out


def test_cmd_daemon_stop_when_not_running(monkeypatch, capsys):
    _patch_daemon(monkeypatch, running=False, stop_running=False)
    args = argparse.Namespace(action="stop")
    assert cli_ops.cmd_daemon(args) == 1
    assert "Not running" in capsys.readouterr().out


def test_cmd_daemon_status_running(monkeypatch, capsys):
    _patch_daemon(monkeypatch, running=True)
    args = argparse.Namespace(action="status")
    assert cli_ops.cmd_daemon(args) == 0
    assert "Running" in capsys.readouterr().out


def test_cmd_daemon_status_not_running(monkeypatch, capsys):
    _patch_daemon(monkeypatch, running=False)
    args = argparse.Namespace(action="status")
    assert cli_ops.cmd_daemon(args) == 0
    assert "Not running" in capsys.readouterr().out


def test_cmd_daemon_unknown_action(monkeypatch, capsys):
    _patch_daemon(monkeypatch, running=False)
    args = argparse.Namespace(action="bogus")
    assert cli_ops.cmd_daemon(args) == 1
    assert "Unknown daemon action" in capsys.readouterr().out


# --- cmd_fix_docstrings / cmd_fix_coverage: patched/generated branches --

def test_cmd_fix_docstrings_patches_files(monkeypatch, capsys):
    class FakeDocstringAgent:
        def run(self, *, project_root, patch):
            return {"total_symbols": 5, "gaps_found": 2, "patched_files": ["a.py", "b.py"]}

    monkeypatch.setattr("app.agents.skills.DocstringAgent", FakeDocstringAgent)
    args = argparse.Namespace(target="", dry_run=False)
    assert cli_ops.cmd_fix_docstrings(args) == 0
    out = capsys.readouterr().out
    assert "Files patched: 2" in out
    assert "patched: a.py" in out


def test_cmd_fix_coverage_generates_stubs(monkeypatch, capsys):
    class FakeTestStubAgent:
        def run(self, *, project_root, generate):
            return {
                "total_functions": 4,
                "tested_functions": 2,
                "coverage_ratio": 0.5,
                "gaps_found": 2,
                "stubs_generated": ["t_a.py", "t_b.py"],
            }

    monkeypatch.setattr("app.agents.skills.TestStubAgent", FakeTestStubAgent)
    args = argparse.Namespace(target="", generate=True)
    assert cli_ops.cmd_fix_coverage(args) == 0
    out = capsys.readouterr().out
    assert "Stubs generated: 2" in out
    assert "created: t_a.py" in out


# --- cmd_lsp: delegates to lsp server main ------------------------------

def test_cmd_lsp_returns_server_main_rc(monkeypatch):
    monkeypatch.setattr("app.lsp.server.main", lambda: 0)
    assert cli_ops.cmd_lsp(argparse.Namespace()) == 0


# --- cmd_metrics: serve loop interrupted, then shut down ----------------

def test_cmd_metrics_serves_then_shuts_down(monkeypatch, capsys):
    shutdown_calls = {"n": 0}
    captured = {}

    class FakeServer:
        def __init__(self, addr, handler):
            self.addr = addr
            captured["handler"] = handler

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            shutdown_calls["n"] += 1

    monkeypatch.setattr("http.server.HTTPServer", FakeServer)

    class FakeMW:
        def record_run(self, *a, **k):
            pass

        def render(self):
            return "metric 1"

    monkeypatch.setattr("app.metrics.exporter.MetricsMiddleware", lambda: FakeMW())

    args = argparse.Namespace(port=9099)
    assert cli_ops.cmd_metrics(args) == 0
    assert shutdown_calls["n"] == 1
    assert "Metrics endpoint" in capsys.readouterr().out

    # Exercise the closure-defined request handler without a real socket.
    Handler = captured["handler"]
    handler = Handler.__new__(Handler)
    sent = {"status": None, "headers": [], "ended": False, "body": b""}

    class FakeWFile:
        def write(self, data):
            sent["body"] += data

    handler.wfile = FakeWFile()
    handler.send_response = lambda code: sent.__setitem__("status", code)
    handler.send_header = lambda k, v: sent["headers"].append((k, v))
    handler.end_headers = lambda: sent.__setitem__("ended", True)

    handler.do_GET()
    assert sent["status"] == 200
    assert sent["ended"] is True
    assert sent["body"] == b"metric 1"
    assert ("Content-Type", "text/plain; version=0.0.4") in sent["headers"]

    # log_message is a no-op override that must not raise.
    handler.log_message("%s", "ignored")
