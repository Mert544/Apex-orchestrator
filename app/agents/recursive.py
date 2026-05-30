from __future__ import annotations

from typing import Any

from app.agents.base import Agent, AgentState


class RecursiveAgent(Agent):
    """Agent that can spawn sub-agents for parallel/delegated work.

    Usage:
        class SecurityAgent(RecursiveAgent):
            def _execute(self, **kwargs):
                files = find_risky_files(kwargs["project_root"])
                # Spawn one sub-agent per file
                for f in files:
                    self.spawn_sub_agent(
                        name=f"security-{f.stem}",
                        role="security_auditor",
                        task={"file": str(f)},
                    )
                results = self.wait_for_sub_agents(timeout=30.0)
                return {"risks": merge_results(results)}
    """

    def __init__(self, name: str, role: str, bus=None, context=None) -> None:
        super().__init__(name, role, bus, context)
        self.sub_agents: list[Agent] = []
        self._sub_results: list[dict[str, Any]] = []

    def spawn_sub_agent(
        self,
        name: str,
        role: str,
        task: dict[str, Any],
        agent_class: type[Agent] | None = None,
    ) -> Agent:
        """Create and register a sub-agent, then trigger it."""
        cls = agent_class or self.__class__
        sub = cls(name=name, role=role, bus=self.bus, context=self.context)
        self.sub_agents.append(sub)
        # Notify via bus that a sub-agent was spawned
        if self.bus:
            self.bus.broadcast(
                sender=self.name,
                topic="agent.spawned",
                payload={"parent": self.name, "child": name, "role": role, "task": task},
            )
        # Run sub-agent immediately (simplified synchronous version)
        try:
            result = sub.run(**task)
            self._sub_results.append(result)
        except Exception as exc:
            self._sub_results.append({"error": str(exc), "agent": name})
        return sub

    def wait_for_sub_agents(self, timeout: float = 30.0) -> list[dict[str, Any]]:
        """Wait until all sub-agents complete or timeout."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            done = all(
                a.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.IDLE)
                for a in self.sub_agents
            )
            if done:
                break
            time.sleep(0.05)
        return list(self._sub_results)

    def reset(self) -> None:
        super().reset()
        self.sub_agents.clear()
        self._sub_results.clear()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["sub_agent_count"] = len(self.sub_agents)
        d["sub_results_count"] = len(self._sub_results)
        return d
