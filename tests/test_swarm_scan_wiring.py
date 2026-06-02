"""Regression tests for the swarm scan-wiring fix.

Previously only the security agent was wired to `scan.complete`, so plans like
`project_scan` (docstring/dependency/coverage) produced zero results. These
tests lock in that every scanner runs on a scan.
"""
from __future__ import annotations

from app.agents.base import Agent, AgentState
from app.agents.bus import AgentBus
from app.agents.swarm_coordinator import SwarmCoordinator
from app.main import _build_swarm_for_plan


class _FakeDocAgent(Agent):
    def __init__(self, bus=None):
        super().__init__(name="doc-1", role="documentation_enforcer", bus=bus)

    def _execute(self, **kwargs):
        return {"role": self.role, "gaps_found": 3, "gaps": ["a", "b", "c"]}


class _FakeDepAgent(Agent):
    def __init__(self, bus=None):
        super().__init__(name="dep-1", role="architecture_analyst", bus=bus)

    def _execute(self, **kwargs):
        return {"role": self.role, "total_edges": 5}


def test_non_security_scanner_runs_on_scan_complete():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    doc = _FakeDocAgent(bus=bus)
    coord.register_agents([doc])

    results = coord.run_autonomous("scan the project", target=".", mode="report")

    assert doc.state == AgentState.COMPLETED
    assert len(results) >= 1
    assert any(r.get("role") == "documentation_enforcer" for r in results)


def test_multiple_scanners_all_produce_results():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    coord.register_agents([_FakeDocAgent(bus=bus), _FakeDepAgent(bus=bus)])

    results = coord.run_autonomous("scan the project", target=".", mode="report")

    roles = {r.get("role") for r in results}
    assert "documentation_enforcer" in roles
    assert "architecture_analyst" in roles


def test_project_scan_plan_yields_findings_on_flask_mini():
    """End-to-end: the real project_scan plan must return >0 results."""
    swarm = _build_swarm_for_plan("project_scan")
    roles = {a.role for a in swarm.registry.agents.values()}
    # Broad sweep should register all four scanners.
    assert {"security_auditor", "documentation_enforcer", "architecture_analyst"} <= roles

    results = swarm.run_autonomous(
        "scan the project", target="examples/flask_mini", mode="report"
    )
    assert len(results) >= 3  # was 0 before the wiring fix
    # The security scanner should flag the known issues in flask_mini.
    sec = next((r for r in results if r.get("role") == "security_auditor"), None)
    assert sec is not None
    assert sec.get("findings_count", 0) >= 1
