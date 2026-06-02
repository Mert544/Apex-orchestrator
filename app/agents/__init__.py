from __future__ import annotations

"""Agent Swarm Architecture for Apex Orchestrator.

Agents are specialized skills that communicate via a shared message bus.
They can form teams, share context, and coordinate on complex tasks.
"""

from .base import Agent, AgentState, AgentMessage
from .bus import AgentBus
from .registry import AgentRegistry
from .team import AgentTeam, TeamOrchestrator

__all__ = [
    "Agent",
    "AgentState",
    "AgentMessage",
    "AgentBus",
    "AgentRegistry",
    "AgentTeam",
    "TeamOrchestrator",
]
