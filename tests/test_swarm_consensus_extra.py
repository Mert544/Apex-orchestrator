from __future__ import annotations

from app.agents.base import Agent, AgentMessage, AgentState
from app.agents.bus import AgentBus
from app.agents.consensus import ConsensusEngine, Verdict, Vote
from app.agents.swarm_coordinator import SwarmCoordinator


# ---------------------------------------------------------------------------
# consensus.py — strategy edge / error paths
# ---------------------------------------------------------------------------


def _vote(agent: str, verdict: str, confidence: float, weight: float = 1.0) -> Vote:
    return Vote(
        agent_name=agent,
        agent_role="test",
        verdict=Verdict[verdict],
        confidence=confidence,
        reasoning="r",
        weight=weight,
    )


def test_unanimous_all_abstain_returns_abstain():
    engine = ConsensusEngine(strategy="unanimous", quorum=2)
    votes = [_vote("a1", "ABSTAIN", 0.9), _vote("a2", "ABSTAIN", 0.8)]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.ABSTAIN
    assert result.confidence == 0.0


def test_majority_only_abstains_returns_abstain():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    votes = [_vote("a1", "ABSTAIN", 0.9), _vote("a2", "ABSTAIN", 0.8)]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.ABSTAIN
    assert result.confidence == 0.0


def test_supermajority_approve_threshold_met():
    engine = ConsensusEngine(strategy="supermajority", quorum=2)
    votes = [
        _vote("a1", "APPROVE", 0.9),
        _vote("a2", "APPROVE", 0.7),
        _vote("a3", "REJECT", 0.5),
    ]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.APPROVE
    assert result.confidence > 0.0


def test_supermajority_reject_threshold_met():
    engine = ConsensusEngine(strategy="supermajority", quorum=2)
    votes = [
        _vote("a1", "REJECT", 0.9),
        _vote("a2", "REJECT", 0.8),
        _vote("a3", "APPROVE", 0.5),
    ]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.REJECT
    assert result.confidence > 0.0


def test_supermajority_all_abstain_returns_abstain():
    engine = ConsensusEngine(strategy="supermajority", quorum=2)
    votes = [_vote("a1", "ABSTAIN", 0.9), _vote("a2", "ABSTAIN", 0.8)]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.ABSTAIN


def test_weighted_all_abstain_returns_abstain():
    engine = ConsensusEngine(strategy="weighted", quorum=2)
    votes = [_vote("a1", "ABSTAIN", 0.9), _vote("a2", "ABSTAIN", 0.8)]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.ABSTAIN
    assert result.confidence == 0.0


def test_weighted_negative_returns_reject():
    engine = ConsensusEngine(strategy="weighted", quorum=2)
    votes = [
        _vote("a1", "REJECT", 0.9, weight=2.0),
        _vote("a2", "APPROVE", 0.4, weight=1.0),
    ]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.REJECT
    assert result.confidence > 0.0


def test_weighted_tie_returns_abstain():
    engine = ConsensusEngine(strategy="weighted", quorum=2)
    votes = [
        _vote("a1", "APPROVE", 0.5, weight=1.0),
        _vote("a2", "REJECT", 0.5, weight=1.0),
    ]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.ABSTAIN
    assert result.confidence == 0.0


def test_threshold_reject_path():
    engine = ConsensusEngine(strategy="threshold", quorum=1, min_confidence=0.8)
    votes = [_vote("a1", "REJECT", 0.9)]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.REJECT
    assert result.confidence == 0.9


def test_threshold_below_confidence_returns_abstain():
    engine = ConsensusEngine(strategy="threshold", quorum=1, min_confidence=0.8)
    votes = [_vote("a1", "APPROVE", 0.5)]
    result = engine.evaluate("c", votes)
    assert result.final_verdict == Verdict.ABSTAIN


def test_create_vote_builds_vote_from_strings():
    vote = ConsensusEngine.create_vote(
        agent_name="x",
        agent_role="security",
        verdict="approve",
        confidence=0.7,
        reasoning="why",
        weight=2.0,
    )
    assert isinstance(vote, Vote)
    assert vote.verdict == Verdict.APPROVE
    assert vote.weight == 2.0
    assert vote.agent_name == "x"


# ---------------------------------------------------------------------------
# swarm_coordinator.py — fake agents and routing paths
# ---------------------------------------------------------------------------


class FakeSecurity(Agent):
    def __init__(self, bus=None):
        super().__init__(name="sec-1", role="security_agent", bus=bus)

    def _execute(self, **kwargs):
        return {
            "risks": [{"file": "a.py", "issue": "eval"}],
            "findings_count": 1,
        }


class FakeEvaluator(Agent):
    def __init__(self, bus=None, verdict="APPROVE"):
        super().__init__(name="eval-1", role="claim_evaluator", bus=bus)
        self._verdict = verdict
        self.run_calls = 0

    def _execute(self, **kwargs):
        self.run_calls += 1

        class _CR:
            def __init__(self, claim, verdict):
                self.claim = claim
                self.confidence = 0.9
                self.final_verdict = Verdict[verdict]

        claims = kwargs.get("claims", [])
        return [_CR(c, self._verdict) for c in claims]


class FakePatcher(Agent):
    def __init__(self, bus=None):
        # role contains "patcher" so registry.get_by_role("patcher") finds it,
        # and "patch" so _wire_agent subscribes it to patch.request.
        super().__init__(name="patch-1", role="patcher_generator", bus=bus)

    def _execute(self, **kwargs):
        return {"patched": True}


class FakeTester(Agent):
    def __init__(self, bus=None):
        super().__init__(name="test-1", role="test_verifier", bus=bus)
        self.run_calls = 0

    def _execute(self, **kwargs):
        self.run_calls += 1
        return {"success": True}


def test_route_to_evaluator_approves_and_broadcasts():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    ev = FakeEvaluator(bus=bus, verdict="APPROVE")
    coord.register_agents([ev])
    seen = []
    bus.subscribe("probe", "claim.approved", lambda m: seen.append(m))
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="security.alert",
        payload={"risks": [{"file": "a.py", "issue": "x"}]},
    )
    coord._route_to_evaluator(msg)
    assert ev.run_calls == 1
    assert len(seen) == 1
    assert seen[0].payload["confidence"] == 0.9


def test_route_to_evaluator_rejects_no_broadcast():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    ev = FakeEvaluator(bus=bus, verdict="REJECT")
    coord.register_agents([ev])
    seen = []
    bus.subscribe("probe", "claim.approved", lambda m: seen.append(m))
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="security.alert",
        payload={"risks": [{"file": "a.py", "issue": "x"}]},
    )
    coord._route_to_evaluator(msg)
    assert seen == []


def test_route_to_evaluator_no_evaluator_noop():
    coord = SwarmCoordinator()
    msg = AgentMessage(sender="t", recipient=None, topic="security.alert", payload={})
    # No evaluator registered -> early return, no error.
    coord._route_to_evaluator(msg)
    assert coord._results == []


def test_handle_claim_submit_runs_evaluator():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    ev = FakeEvaluator(bus=bus)
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="claim.submit",
        payload={"claims": ["claim one"]},
    )
    coord._handle_claim_submit(ev, msg)
    assert ev.run_calls == 1


def test_handle_claim_submit_no_claims_noop():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    ev = FakeEvaluator(bus=bus)
    msg = AgentMessage(
        sender="t", recipient=None, topic="claim.submit", payload={"claims": []}
    )
    coord._handle_claim_submit(ev, msg)
    assert ev.run_calls == 0


def test_route_to_patcher_broadcasts_request():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    patcher = FakePatcher(bus=bus)
    coord.register_agents([patcher])
    seen = []
    bus.subscribe("probe", "patch.request", lambda m: seen.append(m))
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="claim.approved",
        payload={"claim": "fix it", "confidence": 0.8},
    )
    coord._route_to_patcher(msg)
    assert len(seen) == 1
    assert seen[0].payload["claim"] == "fix it"


def test_route_to_patcher_no_patcher_noop():
    coord = SwarmCoordinator()
    msg = AgentMessage(sender="t", recipient=None, topic="claim.approved", payload={})
    coord._route_to_patcher(msg)
    assert coord._results == []


def test_handle_patch_request_marks_applied_and_broadcasts():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    patcher = FakePatcher(bus=bus)
    seen = []
    bus.subscribe("probe", "patch.applied", lambda m: seen.append(m))
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="patch.request",
        payload={"claim": "claim-x"},
    )
    coord._handle_patch_request(patcher, msg)
    assert patcher.results[-1] == {
        "claim": "claim-x",
        "patched": True,
        "agent": "patch-1",
    }
    assert len(seen) == 1


def test_handle_patch_applied_records_test_outcome():
    coord = SwarmCoordinator()
    tester = FakeTester()
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="patch.applied",
        payload={"project_root": "."},
    )
    coord._handle_patch_applied(tester, msg)
    assert tester.run_calls == 1
    assert {"success": True} in coord._results


def test_route_to_tester_dispatches_to_test_agent():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    tester = FakeTester(bus=bus)
    coord.register_agents([tester])
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="patch.applied",
        payload={"project_root": "."},
    )
    coord._route_to_tester(msg)
    assert tester.run_calls == 1


def test_route_to_tester_no_tester_noop():
    coord = SwarmCoordinator()
    msg = AgentMessage(sender="t", recipient=None, topic="patch.applied", payload={})
    coord._route_to_tester(msg)
    assert coord._results == []


def test_handle_fractal_complete_collects_result():
    coord = SwarmCoordinator()
    msg = AgentMessage(
        sender="frac-agent",
        recipient=None,
        topic="fractal.analysis.complete",
        payload={"finding": "f", "tree_depth": 3},
    )
    coord._handle_fractal_complete(msg)
    assert coord._results[-1] == {
        "type": "fractal_analysis",
        "finding": "f",
        "tree_depth": 3,
        "agent": "frac-agent",
    }


def test_handle_scan_complete_skips_non_idle_agent():
    coord = SwarmCoordinator()
    sec = FakeSecurity()
    sec.state = AgentState.RUNNING
    msg = AgentMessage(
        sender="t",
        recipient=None,
        topic="scan.complete",
        payload={"project_root": "."},
    )
    coord._handle_scan_complete(sec, msg)
    # Non-idle agent should not be run, no results appended.
    assert coord._results == []


def test_check_timeout_reflects_shutdown_state():
    coord = SwarmCoordinator()
    assert coord._check_timeout("scan") is False
    coord._shutdown()
    assert coord._check_timeout("scan") is True


# ---------------------------------------------------------------------------
# swarm_coordinator.py — adaptive timeout adjustment branches
# ---------------------------------------------------------------------------


def test_adjust_timeouts_low_success_widens():
    coord = SwarmCoordinator()
    coord._success_rates = {"scan": 0.3, "analyze": 0.6, "patch": 0.99, "test": 0.8}
    coord._adjust_timeouts()
    base_scan = coord._base_timeouts["scan"]
    # rate < 0.5 -> factor 1.5
    assert coord._timeouts["scan"] == base_scan * 1.5
    # 0.5 <= rate < 0.75 -> factor 1.2
    assert coord._timeouts["analyze"] == coord._base_timeouts["analyze"] * 1.2
    # rate > 0.95 -> factor 0.9
    assert coord._timeouts["patch"] == coord._base_timeouts["patch"] * 0.9
    # otherwise factor 1.0
    assert coord._timeouts["test"] == coord._base_timeouts["test"]


def test_adjust_timeouts_total_within_band():
    coord = SwarmCoordinator()
    coord._success_rates = {"scan": 0.99, "analyze": 0.99, "patch": 0.99, "test": 0.99}
    coord._adjust_timeouts()
    total_base = coord._base_timeouts["total"]
    assert total_base * 0.7 <= coord._timeouts["total"] <= total_base * 1.5


# ---------------------------------------------------------------------------
# swarm_coordinator.py — run_autonomous trigger branches & exit paths
# ---------------------------------------------------------------------------


class FakeDocstring(Agent):
    def __init__(self, bus=None):
        super().__init__(name="doc-1", role="docstring_agent", bus=bus)

    def _execute(self, **kwargs):
        return {"findings_count": 0}


def test_run_autonomous_docstring_trigger(capsys):
    coord = SwarmCoordinator()
    doc = FakeDocstring()
    coord.register_agents([doc])
    results = coord.run_autonomous("add docstrings", target=".", mode="report")
    assert isinstance(results, list)
    # `[swarm] ...` status lines are routed to STDERR for stdout determinism.
    out = capsys.readouterr().err
    assert "[swarm]" in out


def test_run_autonomous_test_trigger():
    coord = SwarmCoordinator()
    tester = FakeTester()
    coord.register_agents([tester])
    results = coord.run_autonomous("write tests", target=".", mode="report")
    assert isinstance(results, list)


def test_run_autonomous_generic_trigger_completes():
    coord = SwarmCoordinator()
    # No agents at all -> loop sees empty registry and exits via the
    # all()-over-empty short-circuit, hitting the generic branch.
    results = coord.run_autonomous("refactor things", target=".", mode="report")
    assert results == []


class _StubPlan:
    def __init__(self, agents):
        self.plan_name = "stub"
        self.agents = agents
        self.mode = "report"


def test_run_autonomous_docstring_branch(monkeypatch):
    # Plan whose agents list contains the exact "docstring" token so the
    # docstring scan.complete broadcast branch fires.
    coord = SwarmCoordinator()
    monkeypatch.setattr(
        coord.planner, "build_plan", lambda intent: _StubPlan(["docstring"])
    )
    seen = []
    coord.bus.subscribe("probe", "scan.complete", lambda m: seen.append(m))
    coord.run_autonomous("docs", target="/tmp/x", mode="report")
    assert seen and seen[0].payload["trigger"] == "docstring"


def test_run_autonomous_test_branch(monkeypatch):
    coord = SwarmCoordinator()
    monkeypatch.setattr(
        coord.planner, "build_plan", lambda intent: _StubPlan(["test"])
    )
    seen = []
    coord.bus.subscribe("probe", "scan.complete", lambda m: seen.append(m))
    coord.run_autonomous("verify", target="/tmp/x", mode="report")
    assert seen and seen[0].payload["trigger"] == "test"


class StuckAgent(Agent):
    """Agent whose run() leaves it in RUNNING so the wait loop keeps iterating."""

    def __init__(self, name="stuck"):
        super().__init__(name=name, role="security_agent")

    def run(self, **kwargs):
        self.state = AgentState.RUNNING
        return {"risks": [], "findings_count": 0}

    def _execute(self, **kwargs):
        return {"risks": [], "findings_count": 0}


def test_run_autonomous_timeout_path(monkeypatch, capsys):
    # An agent stuck RUNNING forces the wait loop; a tiny timeout plus a no-op
    # sleep drives the TIMEOUT branch deterministically (no real waiting).
    coord = SwarmCoordinator()
    coord.register_agents([StuckAgent("stuck-1")])
    monkeypatch.setattr("app.agents.swarm_coordinator.time.sleep", lambda s: None)
    coord.run_autonomous("security audit", target=".", mode="report", timeout=0.2)
    out = capsys.readouterr().err
    assert "TIMEOUT" in out
    assert coord._graceful_shutdown.is_shutdown_requested()


def test_run_autonomous_graceful_shutdown_in_loop(monkeypatch, capsys):
    # Agent stays RUNNING but a shutdown is requested mid-loop -> in-loop break.
    coord = SwarmCoordinator()
    coord.register_agents([StuckAgent("stuck-2")])

    calls = {"n": 0}

    def fake_sleep(_s):
        calls["n"] += 1
        if calls["n"] == 1:
            coord._stability.shutdown_manager.request_shutdown()

    monkeypatch.setattr("app.agents.swarm_coordinator.time.sleep", fake_sleep)
    coord.run_autonomous("security audit", target=".", mode="report", timeout=10.0)
    out = capsys.readouterr().err
    assert "Shutdown requested after" in out


def test_run_autonomous_shutdown_during_loop(capsys):
    coord = SwarmCoordinator()

    class SlowAgent(Agent):
        def __init__(self, coord_ref):
            super().__init__(name="slow-1", role="security_agent")
            self._coord = coord_ref

        def _execute(self, **kwargs):
            # Trigger a shutdown so the wait loop takes the graceful path.
            self._coord._shutdown()
            self.state = AgentState.RUNNING
            return {"risks": [], "findings_count": 0}

    agent = SlowAgent(coord)
    coord.register_agents([agent])
    results = coord.run_autonomous("security audit", target=".", mode="report")
    assert isinstance(results, list)
    out = capsys.readouterr().err
    assert "Shutdown" in out or "shutdown" in out
