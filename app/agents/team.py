from __future__ import annotations

"""Team Orchestrator — coordinates multi-agent workflows."""

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any

from .base import Agent, AgentState
from .bus import AgentBus


@dataclass
class TeamResult:
    team_name: str
    agent_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    bus_stats: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_name": self.team_name,
            "agent_results": self.agent_results,
            "bus_stats": self.bus_stats,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


class AgentTeam:
    """A team of agents working together on a shared task."""

    def __init__(self, name: str, bus: AgentBus | None = None) -> None:
        self.name = name
        self.bus = bus or AgentBus()
        self.agents: dict[str, Agent] = {}

    def add(self, agent: Agent) -> None:
        agent.bus = self.bus
        self.agents[agent.name] = agent

    def remove(self, name: str) -> None:
        if name not in self.agents:
            return
        self.agents[name].bus = None
        del self.agents[name]

    def broadcast(self, topic: str, payload: dict[str, Any]) -> None:
        self.bus.broadcast(sender=self.name, topic=topic, payload=payload)

    def run_sequential(self, **kwargs: Any) -> TeamResult:
        """Run agents one by one, passing results forward."""
        import time

        start = time.perf_counter()
        result = TeamResult(team_name=self.name, bus_stats=self.bus.stats())
        shared_context = kwargs.copy()

        for agent in self.agents.values():
            agent.context.update(shared_context)
            agent_result = agent.run(**shared_context)
            result.agent_results[agent.name] = agent_result
            shared_context.update(agent_result)

        result.elapsed_seconds = time.perf_counter() - start
        result.bus_stats = self.bus.stats()
        return result

    def run_parallel(self, max_workers: int = 4, **kwargs: Any) -> TeamResult:
        """Run agents in parallel using ThreadPoolExecutor."""
        import time

        start = time.perf_counter()
        result = TeamResult(team_name=self.name, bus_stats=self.bus.stats())

        def run_agent(agent: Agent) -> tuple[str, dict[str, Any]]:
            agent.context.update(kwargs)
            return agent.name, agent.run(**kwargs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_agent, agent): agent.name
                for agent in self.agents.values()
            }
            for future in concurrent.futures.as_completed(futures):
                name, agent_result = future.result()
                result.agent_results[name] = agent_result

        result.elapsed_seconds = time.perf_counter() - start
        result.bus_stats = self.bus.stats()
        return result

    def run_pipeline(self, stages: list[list[str]], **kwargs: Any) -> TeamResult:
        """Run agents in staged pipelines.

        Each stage runs in parallel, stages run sequentially.
        Stage N receives outputs from all agents in stage N-1.
        """
        import time

        start = time.perf_counter()
        result = TeamResult(team_name=self.name, bus_stats=self.bus.stats())
        shared_context = kwargs.copy()

        for stage_names in stages:
            stage_agents = [self.agents[n] for n in stage_names if n in self.agents]

            def run_agent(agent: Agent) -> tuple[str, dict[str, Any]]:
                agent.context.update(shared_context)
                return agent.name, agent.run(**shared_context)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(stage_agents)) as executor:
                futures = {executor.submit(run_agent, a): a.name for a in stage_agents}
                for future in concurrent.futures.as_completed(futures):
                    name, agent_result = future.result()
                    result.agent_results[name] = agent_result
                    shared_context.update(agent_result)

        result.elapsed_seconds = time.perf_counter() - start
        result.bus_stats = self.bus.stats()
        return result

    def is_ready(self) -> bool:
        return all(a.state in (AgentState.IDLE, AgentState.COMPLETED) for a in self.agents.values())

    def reset(self) -> None:
        for agent in self.agents.values():
            agent.reset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "agent_count": len(self.agents),
            "agents": [a.to_dict() for a in self.agents.values()],
            "bus": self.bus.stats(),
        }


class TeamOrchestrator:
    """High-level orchestrator for managing multiple teams."""

    def __init__(self) -> None:
        self.teams: dict[str, AgentTeam] = {}

    def create_team(self, name: str) -> AgentTeam:
        team = AgentTeam(name)
        self.teams[name] = team
        return team

    def get_team(self, name: str) -> AgentTeam | None:
        return self.teams.get(name)

    def run_team(self, name: str, mode: str = "parallel", **kwargs: Any) -> TeamResult:
        team = self.teams.get(name)
        if not team:
            raise ValueError(f"Team not found: {name}")

        if mode == "sequential":
            return team.run_sequential(**kwargs)
        elif mode == "parallel":
            return team.run_parallel(**kwargs)
        elif mode == "pipeline":
            stages = kwargs.pop("stages", [list(team.agents.keys())])
            return team.run_pipeline(stages=stages, **kwargs)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def list_teams(self) -> list[str]:
        return list(self.teams.keys())
