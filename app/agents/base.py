from __future__ import annotations

"""Agent Base Class — lifecycle, messaging, state management."""

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class AgentState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class AgentMessage:
    sender: str
    recipient: str | None  # None = broadcast
    topic: str
    payload: dict[str, Any]
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class Agent:
    """Base class for all Apex agents.

    Agents have:
    - A unique name and role
    - A state machine (IDLE → RUNNING → COMPLETED/FAILED)
    - An inbox for messages
    - Hooks for lifecycle events
    - Access to shared context and bus
    """

    def __init__(
        self,
        name: str,
        role: str,
        bus: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.bus = bus
        self.context = context or {}
        self.state = AgentState.IDLE
        self.inbox: list[AgentMessage] = []
        self.results: list[dict[str, Any]] = []
        self._handlers: dict[str, Callable[[AgentMessage], None]] = {}

    def on(self, topic: str, handler: Callable[[AgentMessage], None]) -> None:
        """Register a message handler for a topic."""
        self._handlers[topic] = handler
        if self.bus:
            self.bus.subscribe(self.name, topic, self._dispatch)

    def _dispatch(self, msg: AgentMessage) -> None:
        """Internal dispatcher — routes messages to handlers."""
        if msg.recipient and msg.recipient != self.name:
            return
        handler = self._handlers.get(msg.topic)
        if handler:
            handler(msg)
        else:
            self.inbox.append(msg)

    def send(
        self,
        topic: str,
        payload: dict[str, Any],
        recipient: str | None = None,
    ) -> None:
        """Send a message via the bus."""
        if not (self.bus):
            return
        msg = AgentMessage(
            sender=self.name,
            recipient=recipient,
            topic=topic,
            payload=payload,
        )
        self.bus.publish(msg)

    def run(self, **kwargs: Any) -> dict[str, Any]:
        """Main execution hook. Override in subclasses."""
        self.state = AgentState.RUNNING
        try:
            result = self._execute(**kwargs)
            self.results.append(result)
            self.state = AgentState.COMPLETED
            return result
        except Exception as exc:
            self.state = AgentState.FAILED
            return {"error": str(exc), "agent": self.name}

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        """Override this in subclasses."""
        raise NotImplementedError

    def pause(self) -> None:
        self.state = AgentState.PAUSED

    def resume(self) -> None:
        if self.state != AgentState.PAUSED:
            return
        self.state = AgentState.RUNNING

    def reset(self) -> None:
        self.state = AgentState.IDLE
        self.inbox.clear()
        self.results.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "state": self.state.name,
            "inbox_count": len(self.inbox),
            "result_count": len(self.results),
        }
