from __future__ import annotations

"""Agent Registry — discovery, factory, team composition."""

from typing import Any, Callable

from .base import Agent


class AgentRegistry:
    """Registry for agent types and instances.

    Allows dynamic agent creation and team assembly.
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., Agent]] = {}
        self._instances: dict[str, Agent] = {}

    def register(self, agent_type: str, factory: Callable[..., Agent] | None = None) -> None:
        """Register an agent factory by type name, or an instance directly."""
        if factory is None:
            return
        self._factories[agent_type] = factory

    def register_instance(self, agent: Agent) -> None:
        """Register an existing agent instance."""
        self._instances[agent.name] = agent

    def get_by_role(self, role_substring: str) -> Agent | None:
        """Find first agent whose role contains the substring."""
        for agent in self._instances.values():
            if role_substring.lower() in agent.role.lower():
                return agent
        return None

    def create(self, agent_type: str, name: str, **kwargs: Any) -> Agent:
        """Create a new agent instance."""
        factory = self._factories.get(agent_type)
        if not factory:
            raise ValueError(f"Unknown agent type: {agent_type}")
        agent = factory(name=name, **kwargs)
        self._instances[name] = agent
        return agent

    def get(self, name: str) -> Agent | None:
        return self._instances.get(name)

    def list_types(self) -> list[str]:
        return list(self._factories.keys())

    def list_instances(self) -> list[str]:
        return list(self._instances.keys())

    @property
    def agents(self) -> dict[str, Agent]:
        return self._instances

    def remove(self, name: str) -> None:
        if name not in self._instances:
            return
        del self._instances[name]

    def reset_all(self) -> None:
        self._instances.clear()

    def team(self, names: list[str]) -> list[Agent]:
        """Get a team of agents by name."""
        return [self._instances[n] for n in names if n in self._instances]
