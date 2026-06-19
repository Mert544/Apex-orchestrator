from __future__ import annotations

import pytest

from app.agents.base import Agent, AgentMessage, AgentState
from app.agents.bus import AgentBus
from app.agents.consensus import ConsensusResult, Verdict
from app.agents.swarm_coordinator import SwarmCoordinator


class FakeSecurityAgent(Agent):
    def __init__(self, bus=None):
        super().__init__(name="security-1", role="security_agent", bus=bus)

    def _execute(self, **kwargs):
        return {"risks": [{"file": "app/auth.py", "issue": "eval() found"}]}


class FakeEvaluatorAgent(Agent):
    def __init__(self, bus=None):
        super().__init__(name="eval-1", role="claim_evaluator", bus=bus)
        self.ran = False

    def _execute(self, **kwargs):
        self.ran = True
        claims = kwargs.get("claims", [])
        return claims


class FakePatcherAgent(Agent):
    # Role contains the substring "patcher" so registry.get_by_role("patcher")
    # finds it — that is the lookup the coordinator performs.
    def __init__(self, bus=None):
        super().__init__(name="patch-1", role="patcher", bus=bus)
        self.ran = False

    def _execute(self, **kwargs):
        self.ran = True
        return {"patched": True}


class FakeApprovingEvaluator(Agent):
    """Evaluator that returns a consensus APPROVE for each claim."""

    def __init__(self, bus=None):
        super().__init__(name="eval-approve", role="claim_evaluator", bus=bus)

    def run(self, **kwargs):  # bypass base run/_execute to return ConsensusResults
        self.state = AgentState.COMPLETED
        claims = kwargs.get("claims", [])
        return [
            ConsensusResult(claim=c, final_verdict=Verdict.APPROVE, confidence=0.9)
            for c in claims
        ]

    def _execute(self, **kwargs):  # pragma: no cover - run() overridden
        return []


class FakeTesterAgent(Agent):
    def __init__(self, bus=None, passed=True):
        super().__init__(name="test-1", role="test_verifier", bus=bus)
        self._passed = passed

    def _execute(self, **kwargs):
        return {"all_passed": self._passed, "success": self._passed}


class TestSwarmCoordinator:
    def test_register_and_wire(self):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        sec = FakeSecurityAgent(bus=bus)
        coord.register_agents([sec])
        assert "security-1" in coord.registry.list_instances()

    def test_security_alert_triggers_evaluator(self):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        sec = FakeSecurityAgent(bus=bus)
        ev = FakeEvaluatorAgent(bus=bus)
        coord.register_agents([sec, ev])

        # Manually run scan → alert chain
        msg = AgentMessage(sender="test", recipient=None, topic="scan.complete", payload={"project_root": "."})
        coord._handle_scan_complete(sec, msg)

        assert sec.state == AgentState.COMPLETED
        # Coordinator should be subscribed to security.alert
        assert "security.alert" in bus.stats()["topics"]

    def test_run_autonomous_security_goal(self):
        coord = SwarmCoordinator()
        sec = FakeSecurityAgent()
        coord.register_agents([sec])
        results = coord.run_autonomous("security audit", target=".", mode="report")
        assert isinstance(results, list)
        assert coord.stats()["results_count"] >= 0

    def test_stats(self):
        coord = SwarmCoordinator()
        sec = FakeSecurityAgent()
        coord.register_agents([sec])
        stats = coord.stats()
        assert "agents" in stats
        assert "bus" in stats
        assert stats["bus"]["message_count"] >= 0

    def test_shutdown(self):
        coord = SwarmCoordinator()
        coord._running = True
        coord._shutdown()
        assert coord._running is False


def test_record_outcome_adapts_timeouts():
    coord = SwarmCoordinator()
    base_patch = coord._timeouts["patch"]
    # Drive many failures on "patch" -> success rate drops -> timeout widens.
    for _ in range(20):
        coord.record_outcome("patch", success=False)
    assert coord._failure_count > 0
    assert coord._success_rates["patch"] < 1.0
    # Timeouts stay within the documented [0.5x, 2x] band of base.
    assert base_patch * 0.5 <= coord._timeouts["patch"] <= base_patch * 2.0


def test_record_outcome_unknown_op_maps_to_patch():
    coord = SwarmCoordinator()
    for _ in range(6):
        coord.record_outcome("totally-unknown", success=True)
    # Should not raise and should have updated the "patch" bucket.
    assert 0.0 <= coord._success_rates["patch"] <= 1.0


def test_get_stability_status_shape():
    coord = SwarmCoordinator()
    status = coord.get_stability_status()
    assert set(status) == {"shutdown_requested", "timeouts", "active_agents", "pending_results"}
    assert status["shutdown_requested"] is False


def test_run_autonomous_skips_after_shutdown():
    coord = SwarmCoordinator()
    coord._shutdown()
    # A run requested after shutdown returns immediately with no results.
    assert coord.run_autonomous("any goal", target=".", mode="report") == []


class TestRoutingHandlers:
    def test_fractal_complete_collects_result(self):
        coord = SwarmCoordinator()
        msg = AgentMessage(
            sender="frac-1", recipient=None, topic="fractal.analysis.complete",
            payload={"finding": "eval", "tree_depth": 3},
        )
        coord._handle_fractal_complete(msg)
        assert coord._results == [
            {"type": "fractal_analysis", "finding": "eval", "tree_depth": 3, "agent": "frac-1"}
        ]

    def test_scan_complete_skips_non_idle_agent(self):
        coord = SwarmCoordinator()
        sec = FakeSecurityAgent()
        coord.register_agents([sec])
        sec.state = AgentState.RUNNING  # not IDLE -> handler returns early
        msg = AgentMessage(sender="t", recipient=None, topic="scan.complete", payload={})
        coord._handle_scan_complete(sec, msg)
        # No result recorded because the agent never ran.
        assert coord._results == []

    def test_route_to_evaluator_approves_and_broadcasts(self):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        ev = FakeApprovingEvaluator(bus=bus)
        coord.register_agents([ev])

        seen = []
        bus.subscribe("_probe", "claim.approved", lambda m: seen.append(m))

        msg = AgentMessage(
            sender="sec", recipient=None, topic="security.alert",
            payload={"risks": [{"file": "a.py", "issue": "eval"}]},
        )
        coord._route_to_evaluator(msg)
        assert len(seen) == 1
        assert seen[0].payload["confidence"] == 0.9
        assert "a.py" in seen[0].payload["claim"]

    def test_route_to_evaluator_without_evaluator_is_noop(self):
        coord = SwarmCoordinator()
        msg = AgentMessage(sender="s", recipient=None, topic="security.alert", payload={"risks": []})
        # No evaluator registered -> early return, no exception, no results.
        coord._route_to_evaluator(msg)
        assert coord._results == []

    def test_handle_claim_submit_runs_evaluator(self):
        coord = SwarmCoordinator()
        ev = FakeEvaluatorAgent()
        msg = AgentMessage(
            sender="s", recipient=None, topic="claim.submit",
            payload={"claims": ["claim-1"]},
        )
        coord._handle_claim_submit(ev, msg)
        assert ev.ran is True

    def test_handle_claim_submit_empty_claims_skips(self):
        coord = SwarmCoordinator()
        ev = FakeEvaluatorAgent()
        msg = AgentMessage(sender="s", recipient=None, topic="claim.submit", payload={})
        coord._handle_claim_submit(ev, msg)
        assert ev.ran is False

    def test_route_to_patcher_broadcasts_patch_request(self):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        patcher = FakePatcherAgent(bus=bus)
        coord.register_agents([patcher])

        seen = []
        bus.subscribe("_probe", "patch.request", lambda m: seen.append(m))
        msg = AgentMessage(
            sender="s", recipient=None, topic="claim.approved",
            payload={"claim": "c1", "confidence": 0.8},
        )
        coord._route_to_patcher(msg)
        assert seen and seen[0].payload["claim"] == "c1"

    def test_route_to_patcher_without_patcher_is_noop(self):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        seen = []
        bus.subscribe("_probe", "patch.request", lambda m: seen.append(m))
        coord._route_to_patcher(
            AgentMessage(sender="s", recipient=None, topic="claim.approved", payload={"claim": "c"})
        )
        assert seen == []

    def test_handle_patch_request_broadcasts_applied(self):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        patcher = FakePatcherAgent(bus=bus)
        coord.register_agents([patcher])
        seen = []
        bus.subscribe("_probe", "patch.applied", lambda m: seen.append(m))
        msg = AgentMessage(
            sender="s", recipient=None, topic="patch.request",
            payload={"claim": "c2"},
        )
        coord._handle_patch_request(patcher, msg)
        assert patcher.results[-1] == {"claim": "c2", "patched": True, "agent": "patch-1"}
        assert seen and seen[0].payload["patched"] is True

    def test_handle_patch_applied_records_test_outcome(self):
        coord = SwarmCoordinator()
        tester = FakeTesterAgent(passed=True)
        msg = AgentMessage(sender="s", recipient=None, topic="patch.applied", payload={})
        coord._handle_patch_applied(tester, msg)
        assert coord._results[-1]["all_passed"] is True

    def test_route_to_tester_dispatches_to_test_role(self):
        coord = SwarmCoordinator()
        tester = FakeTesterAgent(passed=True)
        coord.register_agents([tester])
        msg = AgentMessage(sender="s", recipient=None, topic="patch.applied", payload={})
        coord._route_to_tester(msg)
        assert coord._results and coord._results[-1].get("all_passed") is True

    def test_route_to_tester_without_tester_is_noop(self):
        coord = SwarmCoordinator()
        coord._route_to_tester(
            AgentMessage(sender="s", recipient=None, topic="patch.applied", payload={})
        )
        assert coord._results == []


class TestTimeoutAdaptation:
    def test_check_timeout_reflects_shutdown_state(self):
        coord = SwarmCoordinator()
        assert coord._check_timeout("scan") is False
        coord._shutdown()
        assert coord._check_timeout("scan") is True

    def test_adjust_timeouts_widens_for_low_success_rate(self):
        coord = SwarmCoordinator()
        base = coord._base_timeouts["patch"]
        coord._success_rates["patch"] = 0.2  # < 0.5 -> factor 1.5
        coord._adjust_timeouts()
        assert coord._timeouts["patch"] == pytest.approx(base * 1.5)

    def test_adjust_timeouts_mid_band_factor(self):
        coord = SwarmCoordinator()
        base = coord._base_timeouts["analyze"]
        coord._success_rates["analyze"] = 0.6  # 0.5 <= rate < 0.75 -> factor 1.2
        coord._adjust_timeouts()
        assert coord._timeouts["analyze"] == pytest.approx(base * 1.2)

    def test_adjust_timeouts_shrinks_for_high_success_rate(self):
        coord = SwarmCoordinator()
        base = coord._base_timeouts["scan"]
        coord._success_rates["scan"] = 0.99  # > 0.95 -> factor 0.9
        coord._adjust_timeouts()
        assert coord._timeouts["scan"] == pytest.approx(base * 0.9)

    def test_adjust_timeouts_neutral_band_keeps_base(self):
        coord = SwarmCoordinator()
        base = coord._base_timeouts["test"]
        coord._success_rates["test"] = 0.85  # 0.75..0.95 -> factor 1.0
        coord._adjust_timeouts()
        assert coord._timeouts["test"] == pytest.approx(base)


class _StubPlan:
    def __init__(self, agents):
        self.plan_name = "stub"
        self.agents = agents
        self.mode = "report"


class TestRunAutonomousTriggers:
    """run_autonomous picks the scan trigger from the plan's exact agent tokens
    and finishes promptly because no agent stays non-idle."""

    def _trigger_for_plan(self, agents, goal="do work"):
        bus = AgentBus()
        coord = SwarmCoordinator(bus=bus)
        # Pin the plan so the trigger branch is selected deterministically by the
        # exact membership checks in run_autonomous (e.g. "docstring" in agents).
        coord.planner.build_plan = lambda intent: _StubPlan(agents)
        seen = []
        bus.subscribe("_probe", "scan.complete", lambda m: seen.append(m.payload.get("trigger")))
        coord.run_autonomous(goal, target=".", mode="report")
        return seen

    def test_security_goal_triggers_security_scan(self):
        # "security" in the goal text drives the security branch.
        triggers = self._trigger_for_plan([], goal="security audit")
        assert triggers == ["security"]

    def test_docstring_plan_triggers_docstring_scan(self):
        triggers = self._trigger_for_plan(["docstring"])
        assert triggers == ["docstring"]

    def test_test_plan_triggers_test_scan(self):
        triggers = self._trigger_for_plan(["test"])
        assert triggers == ["test"]

    def test_generic_plan_triggers_general_scan(self):
        triggers = self._trigger_for_plan(["unrelated"])
        assert triggers == ["general"]

    def test_run_autonomous_completes_with_idle_agents(self, capsys):
        coord = SwarmCoordinator()
        sec = FakeSecurityAgent()
        coord.register_agents([sec])
        results = coord.run_autonomous("security audit", target=".", mode="report")
        # `[swarm] ...` status lines are routed to STDERR for stdout determinism.
        out = capsys.readouterr().err
        assert "[swarm] Completed" in out
        assert isinstance(results, list)


class _StuckAgent(Agent):
    """An agent that never leaves RUNNING, so the wait loop cannot short-circuit
    on the all-idle check — forcing the timeout / shutdown branches to run."""

    def __init__(self):
        super().__init__(name="stuck", role="security_agent")
        self.state = AgentState.RUNNING

    def _execute(self, **kwargs):  # pragma: no cover - never run by these tests
        return {}


class TestRunAutonomousLoopExits:
    def test_timeout_branch_shuts_down(self, capsys, monkeypatch):
        import app.agents.swarm_coordinator as mod

        coord = SwarmCoordinator()
        coord.registry.register_instance(_StuckAgent())
        # Make each loop iteration instant and deterministic.
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)
        results = coord.run_autonomous("security audit", target=".", mode="report", timeout=0.05)
        out = capsys.readouterr().err
        assert "[swarm] TIMEOUT" in out
        # The timeout branch requests shutdown.
        assert coord._stability.shutdown_manager.is_shutdown_requested() is True
        assert results == coord._results

    def test_mid_wait_shutdown_breaks_loop(self, capsys, monkeypatch):
        import app.agents.swarm_coordinator as mod

        coord = SwarmCoordinator()
        coord.registry.register_instance(_StuckAgent())

        # The first sleep call requests shutdown; the next loop guard sees it and
        # breaks, exercising the graceful-shutdown branch (lines 356-357, 375).
        def shutdown_then_noop(_seconds):
            coord._stability.shutdown_manager.request_shutdown()

        monkeypatch.setattr(mod.time, "sleep", shutdown_then_noop)
        coord.run_autonomous("security audit", target=".", mode="report", timeout=10.0)
        out = capsys.readouterr().err
        assert "[swarm] Shutdown requested after" in out
        assert "[swarm] Graceful shutdown" in out
