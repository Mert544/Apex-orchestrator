from __future__ import annotations

import pytest

from app.agents.base import Agent
from app.agents.registry import AgentRegistry


def _make_agent(name: str, role: str = "worker") -> Agent:
    return Agent(name=name, role=role)


def _factory(name: str, role: str = "built", **kwargs) -> Agent:
    return Agent(name=name, role=role)


def test_register_factory_then_create():
    reg = AgentRegistry()
    reg.register("worker", _factory)
    assert reg.list_types() == ["worker"]
    agent = reg.create("worker", name="w1")
    assert agent.name == "w1"
    assert agent.role == "built"
    # create() also stores the instance
    assert reg.get("w1") is agent


def test_register_none_factory_is_ignored():
    reg = AgentRegistry()
    reg.register("noop", None)
    assert reg.list_types() == []
    assert "noop" not in reg._factories


def test_create_unknown_type_raises():
    reg = AgentRegistry()
    with pytest.raises(ValueError) as exc:
        reg.create("ghost", name="x")
    assert "Unknown agent type: ghost" in str(exc.value)


def test_register_instance_and_get():
    reg = AgentRegistry()
    agent = _make_agent("a1")
    reg.register_instance(agent)
    assert reg.get("a1") is agent
    assert reg.list_instances() == ["a1"]


def test_get_missing_instance_returns_none():
    reg = AgentRegistry()
    assert reg.get("nobody") is None


def test_get_by_role_substring_match_case_insensitive():
    reg = AgentRegistry()
    reviewer = _make_agent("rev", role="Code Reviewer")
    reg.register_instance(reviewer)
    reg.register_instance(_make_agent("builder", role="Builder"))
    found = reg.get_by_role("reviewer")
    assert found is reviewer


def test_get_by_role_no_match_returns_none():
    reg = AgentRegistry()
    reg.register_instance(_make_agent("a1", role="Builder"))
    assert reg.get_by_role("auditor") is None


def test_agents_property_exposes_instances():
    reg = AgentRegistry()
    agent = _make_agent("a1")
    reg.register_instance(agent)
    assert reg.agents == {"a1": agent}


def test_remove_existing_instance():
    reg = AgentRegistry()
    reg.register_instance(_make_agent("a1"))
    reg.remove("a1")
    assert reg.get("a1") is None
    assert reg.list_instances() == []


def test_remove_missing_instance_is_noop():
    reg = AgentRegistry()
    reg.register_instance(_make_agent("a1"))
    # Removing a non-existent name must not raise and must not touch others
    reg.remove("ghost")
    assert reg.list_instances() == ["a1"]


def test_reset_all_clears_only_instances():
    reg = AgentRegistry()
    reg.register("worker", _factory)
    reg.register_instance(_make_agent("a1"))
    reg.reset_all()
    assert reg.list_instances() == []
    # Factories survive reset_all
    assert reg.list_types() == ["worker"]


def test_team_returns_known_and_skips_unknown_names():
    reg = AgentRegistry()
    a1 = _make_agent("a1")
    a2 = _make_agent("a2")
    reg.register_instance(a1)
    reg.register_instance(a2)
    team = reg.team(["a1", "ghost", "a2"])
    assert team == [a1, a2]


def test_team_empty_when_no_names_match():
    reg = AgentRegistry()
    reg.register_instance(_make_agent("a1"))
    assert reg.team(["x", "y"]) == []


def test_create_passes_kwargs_to_factory():
    captured: dict = {}

    def capturing_factory(name: str, **kwargs) -> Agent:
        captured.update(kwargs)
        return Agent(name=name, role="r")

    reg = AgentRegistry()
    reg.register("custom", capturing_factory)
    reg.create("custom", name="c1", extra="value", count=3)
    assert captured == {"extra": "value", "count": 3}
