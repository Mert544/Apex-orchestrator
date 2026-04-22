from __future__ import annotations

from app.engine.swarm import SwarmCoordinator, SwarmResult, SwarmTask


def test_swarm_runs_multiple_branches():
    def fake_runner(branch: str) -> dict:
        return {
            "branch_map": {branch: f"claim for {branch}"},
            "recommended_actions": [f"action-{branch}"],
        }

    coordinator = SwarmCoordinator(max_workers=2)
    result = coordinator.run(["x.a", "x.b", "x.c"], "test objective", fake_runner)

    assert result.completed_count == 3
    assert result.failed_count == 0
    assert len(result.aggregated_output["branches_covered"]) == 3
    assert "x.a" in result.aggregated_output["branch_map"]
    assert "x.b" in result.aggregated_output["branch_map"]
    assert "x.c" in result.aggregated_output["branch_map"]
    assert len(result.aggregated_output["recommended_actions"]) == 3


def test_swarm_handles_failure_gracefully():
    def fake_runner(branch: str) -> dict:
        if branch == "x.b":
            raise RuntimeError("simulated failure")
        return {"branch_map": {branch: "ok"}, "recommended_actions": []}

    coordinator = SwarmCoordinator(max_workers=2)
    result = coordinator.run(["x.a", "x.b", "x.c"], "test objective", fake_runner)

    assert result.completed_count == 2
    assert result.failed_count == 1
    assert "x.a" in result.aggregated_output["branches_covered"]
    assert "x.b" not in result.aggregated_output["branches_covered"]
    assert "x.c" in result.aggregated_output["branches_covered"]


def test_swarm_deduplicates_actions():
    def fake_runner(branch: str) -> dict:
        return {
            "branch_map": {},
            "recommended_actions": ["shared_action", f"action-{branch}"],
        }

    coordinator = SwarmCoordinator(max_workers=2)
    result = coordinator.run(["x.a", "x.b"], "test objective", fake_runner)

    actions = result.aggregated_output["recommended_actions"]
    assert actions.count("shared_action") == 1
    assert "action-x.a" in actions
    assert "action-x.b" in actions


def test_swarm_task_to_dict():
    task = SwarmTask(task_id="t-1", branch="x.a", objective="test", status="completed", result={"ok": True})
    d = task.to_dict()
    assert d["task_id"] == "t-1"
    assert d["branch"] == "x.a"
    assert d["status"] == "completed"


def test_swarm_result_to_dict():
    result = SwarmResult(
        tasks=[SwarmTask(task_id="t-1", branch="x.a", objective="test")],
        completed_count=1,
    )
    d = result.to_dict()
    assert d["completed_count"] == 1
    assert len(d["tasks"]) == 1
