from __future__ import annotations

from app.agents.base import AgentState
from app.agents.bus import AgentBus
from app.agents.recursive import RecursiveAgent


class FakeSubAgent(RecursiveAgent):
    def _execute(self, **kwargs):
        # P4 (docs/rnd/context-fragile-tests.md #5): synchronous fake, no sleep —
        # spawn_sub_agent runs sub-agents inline, so a sleep here only added
        # load-sensitive wall time to the wait deadline.
        return {"value": kwargs.get("x", 0) * 2}


class TestRecursiveAgent:
    def test_spawn_sub_agent(self):
        bus = AgentBus()
        parent = FakeSubAgent(name="p", role="parent", bus=bus)
        sub = parent.spawn_sub_agent("sub-1", "child", {"x": 5})
        assert len(parent.sub_agents) == 1
        assert sub.name == "sub-1"

    def test_wait_for_sub_agents(self):
        bus = AgentBus()
        parent = FakeSubAgent(name="p", role="parent", bus=bus)
        parent.spawn_sub_agent("sub-1", "child", {"x": 5}, agent_class=FakeSubAgent)
        parent.spawn_sub_agent("sub-2", "child", {"x": 10}, agent_class=FakeSubAgent)
        # P4 (docs/rnd/context-fragile-tests.md #5): spawn runs sub-agents
        # synchronously, so completion is a STATE fact asserted directly — the
        # wait's timeout is only a hang-guard, never a completion deadline.
        assert all(a.state is AgentState.COMPLETED for a in parent.sub_agents)
        results = parent.wait_for_sub_agents(timeout=30.0)
        assert len(results) == 2
        values = [r["value"] for r in results]
        assert 10 in values
        assert 20 in values

    def test_spawn_broadcasts_event(self):
        bus = AgentBus()
        parent = FakeSubAgent(name="p", role="parent", bus=bus)
        parent.spawn_sub_agent("sub-1", "child", {"x": 1})
        assert bus.stats()["message_count"] >= 1
        assert "agent.spawned" in bus.stats()["topics"]

    def test_reset_clears_subs(self):
        parent = FakeSubAgent(name="p", role="parent")
        parent.spawn_sub_agent("sub-1", "child", {"x": 1})
        parent.reset()
        assert not parent.sub_agents
        assert not parent._sub_results

    def test_to_dict_includes_subs(self):
        parent = FakeSubAgent(name="p", role="parent")
        parent.spawn_sub_agent("sub-1", "child", {"x": 1})
        d = parent.to_dict()
        assert d["sub_agent_count"] == 1
