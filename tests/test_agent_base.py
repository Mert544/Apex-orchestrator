"""Tests for app.agents.base — Agent lifecycle, messaging, and dispatch.

The neighbouring test_base.py characterizes a DIFFERENT module
(app.execution.semantic.transforms.base); this file targets the agent
base class directly, pinning the lifecycle/state-machine edge paths
(dispatch routing, no-bus send, pause/resume/reset).
"""

from app.agents.base import Agent, AgentMessage, AgentState
from app.agents.bus import AgentBus


def _msg(sender="alice", recipient=None, topic="t", payload=None):
    return AgentMessage(
        sender=sender,
        recipient=recipient,
        topic=topic,
        payload=payload if payload is not None else {},
    )


def test_message_id_is_short_and_present():
    m = AgentMessage(sender="a", recipient="b", topic="t", payload={})
    assert isinstance(m.msg_id, str)
    assert len(m.msg_id) == 8


def test_run_returns_execute_result_and_completes():
    class Echo(Agent):
        def _execute(self, **kwargs):
            return {"ok": True, "kw": kwargs}

    agent = Echo(name="echo", role="tester")
    result = agent.run(x=1)
    assert result == {"ok": True, "kw": {"x": 1}}
    assert agent.state == AgentState.COMPLETED
    assert agent.results == [result]


def test_run_failure_sets_failed_state_and_error_payload():
    class Boom(Agent):
        def _execute(self, **kwargs):
            raise ValueError("kaboom")

    agent = Boom(name="boom", role="tester")
    result = agent.run()
    assert agent.state == AgentState.FAILED
    assert result == {"error": "kaboom", "agent": "boom"}
    # Failed runs do not append a result.
    assert agent.results == []


def test_base_execute_raises_not_implemented_via_run():
    # The default _execute raises NotImplementedError, caught by run().
    agent = Agent(name="bare", role="tester")
    result = agent.run()
    assert agent.state == AgentState.FAILED
    assert result["agent"] == "bare"


def test_dispatch_ignores_message_for_other_recipient():
    # Line 63-64: recipient set and != self.name -> dropped silently.
    agent = Agent(name="bob", role="r")
    seen = []
    agent.on("topic", lambda msg: seen.append(msg))
    agent._dispatch(_msg(recipient="charlie", topic="topic"))
    assert seen == []
    assert agent.inbox == []


def test_dispatch_delivers_message_addressed_to_self():
    agent = Agent(name="bob", role="r")
    seen = []
    agent.on("topic", lambda msg: seen.append(msg.payload))
    agent._dispatch(_msg(recipient="bob", topic="topic", payload={"v": 1}))
    assert seen == [{"v": 1}]


def test_dispatch_without_handler_appends_to_inbox():
    # Line 69: no handler registered for topic -> message buffered in inbox.
    agent = Agent(name="bob", role="r")
    m = _msg(recipient=None, topic="unhandled", payload={"k": "v"})
    agent._dispatch(m)
    assert agent.inbox == [m]


def test_send_without_bus_is_noop():
    # Line 78-79: no bus -> send returns early, nothing raised.
    agent = Agent(name="lonely", role="r")
    assert agent.bus is None
    # Should not raise even though there is no bus to publish to.
    assert agent.send("topic", {"x": 1}) is None


def test_send_with_bus_publishes_message():
    bus = AgentBus()
    sender = Agent(name="alice", role="s", bus=bus)
    receiver = Agent(name="bob", role="r", bus=bus)
    got = []
    receiver.on("greet", lambda msg: got.append((msg.sender, msg.payload)))
    sender.send("greet", {"hi": True}, recipient="bob")
    assert got == [("alice", {"hi": True})]


def test_on_without_bus_registers_handler_locally():
    # on() with no bus must still register the handler (no subscribe call).
    agent = Agent(name="solo", role="r")
    agent.on("topic", lambda msg: None)
    assert "topic" in agent._handlers


def test_pause_sets_paused_state():
    # Line 105: pause().
    agent = Agent(name="p", role="r")
    agent.pause()
    assert agent.state == AgentState.PAUSED


def test_resume_from_paused_goes_running():
    # Line 108-110: resume() only transitions out of PAUSED.
    agent = Agent(name="p", role="r")
    agent.pause()
    agent.resume()
    assert agent.state == AgentState.RUNNING


def test_resume_when_not_paused_is_noop():
    # Line 108-109: early return when not PAUSED.
    agent = Agent(name="p", role="r")
    assert agent.state == AgentState.IDLE
    agent.resume()
    assert agent.state == AgentState.IDLE


def test_reset_clears_inbox_results_and_state():
    class Echo(Agent):
        def _execute(self, **kwargs):
            return {"ok": True}

    agent = Echo(name="e", role="r")
    agent.run()
    agent.inbox.append(_msg())
    assert agent.results and agent.inbox
    agent.reset()
    assert agent.state == AgentState.IDLE
    assert agent.inbox == []
    assert agent.results == []


def test_to_dict_reports_counts_and_state_name():
    class Echo(Agent):
        def _execute(self, **kwargs):
            return {"ok": True}

    agent = Echo(name="e", role="worker")
    agent.run()
    agent.inbox.append(_msg())
    d = agent.to_dict()
    assert d == {
        "name": "e",
        "role": "worker",
        "state": "COMPLETED",
        "inbox_count": 1,
        "result_count": 1,
    }


def test_context_defaults_to_empty_dict():
    agent = Agent(name="c", role="r")
    assert agent.context == {}
    seeded = Agent(name="c2", role="r", context={"k": "v"})
    assert seeded.context == {"k": "v"}
