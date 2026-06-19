"""Characterization tests for SwarmCoordinator.run_autonomous.

These lock the full observable behaviour of run_autonomous -- stdout, the
sequence of bus.broadcast calls, and the return value -- across every branch
(pre-shutdown, all four scan triggers, completion, timeout, and mid-wait
graceful shutdown). They guard the byte-identical decomposition of the method
into pure helpers (_select_scan_trigger / _all_agents_settled / _await_pipeline
/ _report_outcome).

A frozen monotonic clock (time.sleep / time.time) makes every elapsed string
deterministic, so the digests are stable across runs and machines.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr

import app.agents.swarm_coordinator as mod
from app.agents.base import Agent, AgentState
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


class _Stuck(Agent):
    def __init__(self):
        super().__init__(name="stuck", role="security_agent")
        self.state = AgentState.RUNNING

    def _execute(self, **kwargs):  # pragma: no cover - never runs in these tests
        return {}


def _make_coord(agents, plan_agents, goal):
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    coord.intent_parser.parse = lambda g, explicit_mode=None: _StubIntent(goal)
    coord.planner.build_plan = lambda intent: _StubPlan(plan_agents)
    for a in agents:
        a.bus = bus
        coord.registry.register_instance(a)
    trace: list[dict] = []
    orig = bus.broadcast

    def traced(**kwargs):
        trace.append({k: kwargs.get(k) for k in ("sender", "topic", "payload")})
        return orig(**kwargs)

    bus.broadcast = traced
    return coord, trace


def _run(monkeypatch, coord, goal, timeout=None, sleep_hook=None):
    clock = {"t": 1000.0}

    def fake_sleep(s):
        clock["t"] += s
        if sleep_hook is not None:
            sleep_hook(coord)

    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    # `[swarm] ...` progress/status lines are emitted to STDERR (the deterministic
    # findings/result are the only thing on STDOUT), so capture stderr for the
    # assertions that read `out`.
    buf = io.StringIO()
    with redirect_stderr(buf):
        ret = coord.run_autonomous(goal, target="/t", mode="report", timeout=timeout)
    return buf.getvalue(), ret


def _topics(trace):
    return [b["topic"] for b in trace]


def test_pre_shutdown_returns_empty(monkeypatch):
    coord, trace = _make_coord([], ["docstring"], "neutral goal")
    coord._shutdown()
    trace.clear()
    out, ret = _run(monkeypatch, coord, "neutral goal")
    assert ret == []
    assert ret is not coord._results
    assert trace == []
    assert out == "[swarm] Shutdown previously requested, ignoring new run\n"


def test_security_goal_trigger(monkeypatch):
    coord, trace = _make_coord([_Sec()], [], "do a security audit")
    out, ret = _run(monkeypatch, coord, "do a security audit")
    assert ret is coord._results
    assert _topics(trace) == ["scan.complete"]
    assert trace[0]["payload"] == {"project_root": "/t", "trigger": "security"}
    assert trace[0]["sender"] == "swarm"
    assert "[swarm] Goal: do a security audit" in out
    assert "[swarm] Completed in 0.1s" in out


def test_security_in_plan_agents_trigger(monkeypatch):
    coord, trace = _make_coord([_Sec()], ["security"], "neutral goal")
    _run(monkeypatch, coord, "neutral goal")
    assert trace[0]["payload"]["trigger"] == "security"


def test_uppercase_security_goal_trigger(monkeypatch):
    coord, trace = _make_coord([_Sec()], [], "SECURITY review")
    _run(monkeypatch, coord, "SECURITY review")
    assert trace[0]["payload"]["trigger"] == "security"


def test_docstring_trigger(monkeypatch):
    coord, trace = _make_coord([], ["docstring"], "neutral goal")
    _run(monkeypatch, coord, "neutral goal")
    assert trace[0]["payload"]["trigger"] == "docstring"


def test_test_trigger(monkeypatch):
    coord, trace = _make_coord([], ["test"], "neutral goal")
    _run(monkeypatch, coord, "neutral goal")
    assert trace[0]["payload"]["trigger"] == "test"


def test_generic_trigger(monkeypatch):
    coord, trace = _make_coord([], ["unrelated"], "neutral goal")
    _run(monkeypatch, coord, "neutral goal")
    assert trace[0]["payload"]["trigger"] == "general"


def test_security_precedence_over_docstring(monkeypatch):
    coord, trace = _make_coord([], ["security", "docstring"], "neutral")
    _run(monkeypatch, coord, "neutral")
    assert trace[0]["payload"]["trigger"] == "security"


def test_timeout_branch_shuts_down(monkeypatch):
    coord, trace = _make_coord([_Stuck()], ["docstring"], "neutral goal")
    out, ret = _run(monkeypatch, coord, "neutral goal", timeout=0.05)
    assert "[swarm] TIMEOUT after 0.1s" in out
    assert coord._stability.shutdown_manager.is_shutdown_requested() is True
    assert ret is coord._results


def test_timeout_none_uses_total_budget(monkeypatch):
    coord, trace = _make_coord([_Stuck()], ["docstring"], "neutral goal")
    coord._timeouts["total"] = 0.05
    out, _ = _run(monkeypatch, coord, "neutral goal", timeout=None)
    assert "[swarm] TIMEOUT after 0.1s" in out


def test_mid_wait_shutdown_branch(monkeypatch):
    coord, trace = _make_coord([_Stuck()], ["docstring"], "neutral goal")
    out, _ = _run(
        monkeypatch,
        coord,
        "neutral goal",
        timeout=10.0,
        sleep_hook=lambda c: c._stability.shutdown_manager.request_shutdown(),
    )
    assert "[swarm] Shutdown requested after 0.1s" in out
    assert "[swarm] Graceful shutdown after 0.1s" in out


def test_no_agents_completes_immediately(monkeypatch):
    coord, trace = _make_coord([], [], "neutral goal")
    out, ret = _run(monkeypatch, coord, "neutral goal")
    assert "[swarm] Completed in 0.1s with 0 result(s)" in out
    assert ret is coord._results


def test_select_scan_trigger_is_pure():
    fn = SwarmCoordinator._select_scan_trigger
    assert fn(["security"], "anything") == "security"
    assert fn([], "do a security audit") == "security"
    assert fn(["docstring"], "neutral") == "docstring"
    assert fn(["test"], "neutral") == "test"
    assert fn(["other"], "neutral") == "general"
    assert fn([], "neutral") == "general"
