import pytest

from app.agents.base import Agent
from app.agents.team import AgentTeam, TeamOrchestrator


class _Echo(Agent):
    def __init__(self, name, value):
        super().__init__(name=name, role="echo")
        self._value = value

    def _execute(self, **kwargs):
        return {self.name: self._value, "seen": sorted(kwargs.keys())}


def _team():
    t = AgentTeam("t")
    t.add(_Echo("a", 1))
    t.add(_Echo("b", 2))
    return t


def test_add_remove_and_to_dict():
    t = _team()
    assert t.to_dict()["agent_count"] == 2
    t.remove("a")
    assert "a" not in t.agents
    assert t.to_dict()["agent_count"] == 1


def test_run_sequential_passes_context_forward():
    t = _team()
    result = t.run_sequential()
    assert result.agent_results["a"]["a"] == 1
    assert result.agent_results["b"]["b"] == 2
    # b should see a's output in its kwargs (context passed forward).
    assert "a" in result.agent_results["b"]["seen"]
    assert result.elapsed_seconds >= 0


def test_run_parallel_collects_all():
    result = _team().run_parallel(max_workers=2)
    assert set(result.agent_results) == {"a", "b"}
    assert result.agent_results["a"]["a"] == 1


def test_run_pipeline_stages():
    t = _team()
    result = t.run_pipeline(stages=[["a"], ["b"]])
    assert set(result.agent_results) == {"a", "b"}
    # Stage 2 (b) receives stage 1 (a) output.
    assert "a" in result.agent_results["b"]["seen"]


def test_is_ready_and_reset():
    t = _team()
    assert t.is_ready()  # all IDLE
    t.run_parallel()
    t.reset()
    assert t.is_ready()


def test_team_result_to_dict():
    result = _team().run_parallel()
    d = result.to_dict()
    assert d["team_name"] == "t"
    assert "agent_results" in d


def test_orchestrator_create_get_list():
    orch = TeamOrchestrator()
    team = orch.create_team("alpha")
    team.add(_Echo("a", 1))
    assert orch.get_team("alpha") is team
    assert orch.get_team("missing") is None
    assert "alpha" in orch.list_teams()


def test_orchestrator_run_modes():
    orch = TeamOrchestrator()
    team = orch.create_team("alpha")
    team.add(_Echo("a", 1))
    team.add(_Echo("b", 2))
    assert set(orch.run_team("alpha", mode="parallel").agent_results) == {"a", "b"}
    assert set(orch.run_team("alpha", mode="sequential").agent_results) == {"a", "b"}
    assert set(orch.run_team("alpha", mode="pipeline", stages=[["a", "b"]]).agent_results) == {"a", "b"}


def test_orchestrator_errors():
    orch = TeamOrchestrator()
    orch.create_team("alpha")
    with pytest.raises(ValueError):
        orch.run_team("missing")
    with pytest.raises(ValueError):
        orch.run_team("alpha", mode="bogus")
