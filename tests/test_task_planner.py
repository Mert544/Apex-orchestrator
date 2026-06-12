"""TaskPlanner: claims become prioritized engineering tasks — real behavior."""

from __future__ import annotations

from app.execution.task_planner import TaskPlanner


def _report(**overrides) -> dict:
    base = {
        "branch_map": {
            "b1": "auth surface is security sensitive",
            "b2": "dependency hub pressure in core",
            "b3": "config drift between environments",
        },
        "claim_types": {
            "auth surface is security sensitive": "security",
            "dependency hub pressure in core": "architecture",
            "config drift between environments": "general",
        },
        "claim_priorities": {
            "auth surface is security sensitive": 0.9,
            "dependency hub pressure in core": 0.6,
            "config drift between environments": 0.3,
        },
        "recommended_actions": ["Harden app/auth/token_service.py first, then app/core.py"],
        "key_risks": ["token leakage on the auth path"],
    }
    base.update(overrides)
    return base


def test_tasks_are_sorted_by_priority_and_titled_by_category():
    tasks = TaskPlanner().plan(_report()).tasks
    assert [t.priority for t in tasks] == sorted((t.priority for t in tasks), reverse=True)
    assert tasks[0].title == "Harden sensitive surface"           # security claim wins
    titles = {t.title for t in tasks}
    assert "Reduce dependency hub pressure" in titles
    assert "Stabilize configuration surface" in titles
    # Every task is traceable: branch + rationale carrying the claim and risk.
    assert tasks[0].branch == "b1"
    assert "token leakage" in tasks[0].rationale
    assert "Claim type: security" in tasks[0].rationale


def test_file_inference_from_actions_and_claim_keywords():
    tasks = TaskPlanner().plan(_report()).tasks
    auth_task = next(t for t in tasks if t.branch == "b1")
    # Path-like tokens in recommended actions are picked up and deduped;
    # the auth keyword adds its conventional file exactly once.
    assert "app/auth/token_service.py" in auth_task.suggested_files
    assert "app/core.py" in auth_task.suggested_files
    assert len(auth_task.suggested_files) == len(set(auth_task.suggested_files)) <= 5


def test_acceptance_criteria_follow_claim_type():
    tasks = TaskPlanner().plan(_report()).tasks
    security = next(t for t in tasks if t.branch == "b1")
    assert any("safety checks" in c for c in security.acceptance_criteria)
    architecture = next(t for t in tasks if t.branch == "b2")
    assert any("coupling point" in c for c in architecture.acceptance_criteria)
    # Defaults are always present.
    for t in tasks:
        assert any("documented" in c for c in t.acceptance_criteria)


def test_plan_caps_at_eight_tasks_and_to_dict_round_trips():
    branch_map = {f"b{i}": f"claim {i}" for i in range(12)}
    result = TaskPlanner().plan({"branch_map": branch_map})
    assert len(result.tasks) == 8
    payload = result.to_dict()
    assert len(payload["tasks"]) == 8
    assert payload["tasks"][0]["id"].startswith("task-")


def test_empty_report_yields_empty_plan():
    result = TaskPlanner().plan({})
    assert result.tasks == [] and result.to_dict() == {"tasks": []}
