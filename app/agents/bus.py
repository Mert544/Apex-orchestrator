from __future__ import annotations

"""Agent Bus — publish/subscribe message passing between agents."""

from typing import Any, Callable

from .base import AgentMessage


class AgentBus:
    """Shared message bus for inter-agent communication.

    Topics:
    - scan.complete — scan finished, results available
    - security.alert — security issue found
    - patch.ready — patch generated
    - claim.new — new claim discovered
    - task.assign — task assigned to agent
    - team.sync — team-wide synchronization
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[str, Callable[[AgentMessage], None]]]] = {}
        self._history: list[AgentMessage] = []
        self._max_history = 1000

    def subscribe(
        self,
        agent_name: str,
        topic: str,
        handler: Callable[[AgentMessage], None],
    ) -> None:
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append((agent_name, handler))

    def unsubscribe(self, agent_name: str, topic: str) -> None:
        if topic not in self._subscribers:
            return
        self._subscribers[topic] = [
            (a, h) for a, h in self._subscribers[topic] if a != agent_name
        ]

    def publish(self, msg: AgentMessage) -> None:
        self._history.append(msg)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        # Ensure topic exists in subscriber map so stats reflect it
        if msg.topic not in self._subscribers:
            self._subscribers[msg.topic] = []

        subscribers = self._subscribers.get(msg.topic, [])
        for agent_name, handler in subscribers:
            if msg.recipient is None or msg.recipient == agent_name:
                try:
                    handler(msg)
                except Exception:
                    pass  # Bus never crashes subscribers

    def get_history(
        self,
        topic: str | None = None,
        sender: str | None = None,
        limit: int = 100,
    ) -> list[AgentMessage]:
        results = self._history
        if topic:
            results = [m for m in results if m.topic == topic]
        if sender:
            results = [m for m in results if m.sender == sender]
        return results[-limit:]

    def broadcast(
        self,
        sender: str,
        topic: str,
        payload: dict[str, Any],
    ) -> None:
        self.publish(AgentMessage(sender=sender, recipient=None, topic=topic, payload=payload))

    def stats(self) -> dict[str, Any]:
        return {
            "topics": list(self._subscribers.keys()),
            "subscriber_count": sum(len(s) for s in self._subscribers.values()),
            "message_count": len(self._history),
        }
