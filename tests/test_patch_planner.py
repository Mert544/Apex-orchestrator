from app.execution.patch_planner import PatchPlanner, PatchPlan


def test_patch_planner_basic():
    planner = PatchPlanner()
    plan = planner.plan({
        "id": "task-1",
        "title": "Add docstrings",
        "branch": "x.a",
        "suggested_files": ["app/main.py"],
    })

    assert isinstance(plan, PatchPlan)
    assert plan.task_id == "task-1"
    assert plan.title == "Add docstrings"
    assert plan.branch == "x.a"
    assert plan.target_files == ["app/main.py"]


def test_patch_planner_strategy_for_docstring():
    planner = PatchPlanner()
    plan = planner.plan({"title": "Add missing docstrings", "id": "t1"})

    strategy_text = " ".join(plan.change_strategy).lower()
    assert "document" in strategy_text or "docstring" in strategy_text


def test_patch_planner_warnings_for_security_task():
    planner = PatchPlanner()
    plan = planner.plan({"title": "Remove eval() usage", "id": "t1"})

    assert len(plan.warnings) > 0


def test_patch_plan_to_dict():
    plan = PatchPlan(task_id="t1", title="Test", branch=None)
    d = plan.to_dict()
    assert d["task_id"] == "t1"
    assert d["title"] == "Test"
    assert d["branch"] is None
