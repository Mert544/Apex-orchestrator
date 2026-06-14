from __future__ import annotations

from app.agents.base import AgentMessage
from app.agents.bus import AgentBus


def _msg(sender: str, topic: str, recipient: str | None = None, **payload) -> AgentMessage:
    return AgentMessage(sender=sender, recipient=recipient, topic=topic, payload=payload)


def test_subscribe_and_publish_delivers_to_handler():
    bus = AgentBus()
    received: list[AgentMessage] = []
    bus.subscribe("a1", "scan.complete", received.append)
    bus.publish(_msg("sender", "scan.complete", x=1))
    assert len(received) == 1
    assert received[0].payload["x"] == 1


def test_publish_creates_topic_for_stats_even_without_subscribers():
    bus = AgentBus()
    bus.publish(_msg("sender", "unsubscribed.topic"))
    stats = bus.stats()
    assert "unsubscribed.topic" in stats["topics"]
    assert stats["message_count"] == 1
    assert stats["subscriber_count"] == 0


def test_recipient_targeting_skips_non_addressed_subscriber():
    bus = AgentBus()
    got_a1: list[AgentMessage] = []
    got_a2: list[AgentMessage] = []
    bus.subscribe("a1", "task.assign", got_a1.append)
    bus.subscribe("a2", "task.assign", got_a2.append)
    bus.publish(_msg("boss", "task.assign", recipient="a2", job="x"))
    assert got_a1 == []
    assert len(got_a2) == 1


def test_broadcast_reaches_all_subscribers():
    bus = AgentBus()
    got_a1: list[AgentMessage] = []
    got_a2: list[AgentMessage] = []
    bus.subscribe("a1", "team.sync", got_a1.append)
    bus.subscribe("a2", "team.sync", got_a2.append)
    bus.broadcast("boss", "team.sync", {"v": 7})
    assert len(got_a1) == 1
    assert len(got_a2) == 1
    assert got_a1[0].recipient is None
    assert got_a1[0].payload == {"v": 7}


def test_unsubscribe_removes_handler():
    bus = AgentBus()
    received: list[AgentMessage] = []
    bus.subscribe("a1", "claim.new", received.append)
    bus.unsubscribe("a1", "claim.new")
    bus.publish(_msg("sender", "claim.new"))
    assert received == []


def test_unsubscribe_unknown_topic_is_noop():
    bus = AgentBus()
    # Topic was never subscribed; should hit the early return and not raise
    bus.unsubscribe("a1", "never.seen")
    assert "never.seen" not in bus.stats()["topics"]


def test_unsubscribe_leaves_other_agents_subscribed():
    bus = AgentBus()
    got_a1: list[AgentMessage] = []
    got_a2: list[AgentMessage] = []
    bus.subscribe("a1", "security.alert", got_a1.append)
    bus.subscribe("a2", "security.alert", got_a2.append)
    bus.unsubscribe("a1", "security.alert")
    bus.publish(_msg("scanner", "security.alert"))
    assert got_a1 == []
    assert len(got_a2) == 1


def test_handler_exception_does_not_crash_bus():
    bus = AgentBus()
    delivered_after: list[AgentMessage] = []

    def boom(_msg: AgentMessage) -> None:
        raise RuntimeError("handler exploded")

    bus.subscribe("bad", "patch.ready", boom)
    bus.subscribe("good", "patch.ready", delivered_after.append)
    # Must not raise even though the first handler throws
    bus.publish(_msg("sender", "patch.ready"))
    assert len(delivered_after) == 1


def test_history_is_trimmed_to_max():
    bus = AgentBus()
    bus._max_history = 3
    for i in range(5):
        bus.publish(_msg("sender", "scan.complete", i=i))
    history = bus.get_history(limit=100)
    assert len(history) == 3
    # Oldest entries dropped, newest retained in order
    assert [m.payload["i"] for m in history] == [2, 3, 4]


def test_get_history_filter_by_topic():
    bus = AgentBus()
    bus.publish(_msg("s", "topic.a"))
    bus.publish(_msg("s", "topic.b"))
    bus.publish(_msg("s", "topic.a"))
    results = bus.get_history(topic="topic.a")
    assert len(results) == 2
    assert all(m.topic == "topic.a" for m in results)


def test_get_history_filter_by_sender():
    bus = AgentBus()
    bus.publish(_msg("alice", "t"))
    bus.publish(_msg("bob", "t"))
    bus.publish(_msg("alice", "t"))
    results = bus.get_history(sender="alice")
    assert len(results) == 2
    assert all(m.sender == "alice" for m in results)


def test_get_history_combined_filters_and_limit():
    bus = AgentBus()
    bus.publish(_msg("alice", "t", n=1))
    bus.publish(_msg("alice", "other", n=2))
    bus.publish(_msg("bob", "t", n=3))
    bus.publish(_msg("alice", "t", n=4))
    results = bus.get_history(topic="t", sender="alice", limit=1)
    # alice+topic 't' => n=1 and n=4; limit=1 keeps the most recent
    assert len(results) == 1
    assert results[0].payload["n"] == 4


def test_stats_counts_subscribers_across_topics():
    bus = AgentBus()
    bus.subscribe("a1", "t1", lambda m: None)
    bus.subscribe("a2", "t1", lambda m: None)
    bus.subscribe("a1", "t2", lambda m: None)
    stats = bus.stats()
    assert stats["subscriber_count"] == 3
    assert set(stats["topics"]) == {"t1", "t2"}
    assert stats["message_count"] == 0
