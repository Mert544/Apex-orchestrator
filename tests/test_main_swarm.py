from __future__ import annotations

from pathlib import Path

import pytest

from app.main import _build_swarm_for_plan
from app.agents.swarm_coordinator import SwarmCoordinator


class TestMainSwarmIntegration:
    def test_build_swarm_security_plan(self):
        swarm = _build_swarm_for_plan("full_autonomous_loop")
        assert isinstance(swarm, SwarmCoordinator)
        assert len(swarm.registry.agents) >= 1

    def test_build_swarm_semantic_plan(self):
        swarm = _build_swarm_for_plan("semantic_patch_loop")
        assert len(swarm.registry.agents) >= 1

    def test_build_swarm_project_scan(self):
        swarm = _build_swarm_for_plan("project_scan")
        assert len(swarm.registry.agents) >= 1

    def test_build_swarm_includes_security_agent(self):
        swarm = _build_swarm_for_plan("security_audit")
        roles = [a.role for a in swarm.registry.agents.values()]
        assert "security_auditor" in roles

    def test_build_swarm_agents_have_bus(self):
        swarm = _build_swarm_for_plan("full_autonomous_loop")
        for agent in swarm.registry.agents.values():
            assert agent.bus is not None
