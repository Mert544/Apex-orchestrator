"""Determinism guard: SwarmCoordinator must not write wall-clock progress to STDOUT.

`apex scan` promises "same repo state -> same bytes" on STDOUT so CI can diff scan
output. The coordinator's `[swarm] ...` progress/status lines carry wall-clock
elapsed timing (e.g. `Completed in {elapsed:.1f}s`) and are therefore
non-deterministic. They must land on STDERR via the single `_emit_status`
chokepoint, leaving STDOUT byte-identical run-to-run.

These tests pin that contract:
  * STDOUT is byte-identical across two runs whose wall-clocks differ.
  * The non-deterministic `Completed in Xs` line appears on STDERR, not STDOUT.
  * Every `[swarm] ...` line is emitted through `_emit_status` to STDERR.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import app.agents.swarm_coordinator as mod
from app.agents.base import Agent
from app.agents.bus import AgentBus
from app.agents.swarm_coordinator import SwarmCoordinator


class _StubPlan:
    def __init__(self, agents, plan_name="stub", mode="report"):
        self.plan_name = plan_name
        self.agents = agents
        self.mode = mode


class _StubIntent:
    def __init__(self, goal):
        self.goal = goal


class _Sec(Agent):
    def __init__(self):
        super().__init__(name="sec", role="security_agent")

    def _execute(self, **kwargs):
        return {"risks": [{"file": "a.py", "issue": "eval"}], "findings_count": 1}


def _make_coord(goal="security audit"):
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    coord.intent_parser.parse = lambda g, explicit_mode=None: _StubIntent(goal)
    coord.planner.build_plan = lambda intent: _StubPlan(["security"])
    agent = _Sec()
    agent.bus = bus
    coord.registry.register_instance(agent)
    return coord


def _run_capturing(monkeypatch, start_clock):
    """Run the coordinator with a fixed monotonic clock; return (stdout, stderr)."""
    clock = {"t": float(start_clock)}
    monkeypatch.setattr(mod.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    coord = _make_coord()
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        coord.run_autonomous("security audit", target="/repo", mode="report")
    return out_buf.getvalue(), err_buf.getvalue()


def test_scan_stdout_byte_identical_across_runs(monkeypatch):
    # Two runs whose wall-clocks differ (1000.0 vs 9999.0) must yield the SAME
    # STDOUT bytes -- nothing time-dependent may leak onto stdout.
    out_a, _ = _run_capturing(monkeypatch, 1000.0)
    out_b, _ = _run_capturing(monkeypatch, 9999.0)
    assert out_a == out_b


def test_completed_timing_line_on_stderr_not_stdout(monkeypatch):
    out, err = _run_capturing(monkeypatch, 1000.0)
    # The non-deterministic timing line lives on STDERR only.
    assert "[swarm] Completed in" in err
    assert "[swarm]" not in out
    assert "Completed in" not in out


def test_no_swarm_progress_leaks_to_stdout(monkeypatch):
    out, err = _run_capturing(monkeypatch, 1000.0)
    # Goal/Plan progress + the terminal status all route through _emit_status.
    assert "[swarm] Goal:" in err
    assert "[swarm] Plan:" in err
    assert out == ""


def test_emit_status_writes_to_stderr(monkeypatch, capsys):
    coord = _make_coord()
    coord._emit_status("hello")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[swarm] hello\n"
