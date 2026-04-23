from app.automation.plans import DEFAULT_AUTOMATION_PLANS


def test_default_plans_exist():
    assert "project_scan" in DEFAULT_AUTOMATION_PLANS
    assert "focused_branch" in DEFAULT_AUTOMATION_PLANS
    assert "verify_project" in DEFAULT_AUTOMATION_PLANS
    assert "supervised_patch_loop" in DEFAULT_AUTOMATION_PLANS


def test_project_scan_has_steps():
    plan = DEFAULT_AUTOMATION_PLANS["project_scan"]
    assert len(plan) >= 3
    assert plan[0].name == "profile_project"
    assert plan[1].name == "decompose_objective"
    assert plan[2].name == "run_research"


def test_semantic_patch_loop_order():
    plan = DEFAULT_AUTOMATION_PLANS["semantic_patch_loop"]
    names = [step.name for step in plan]
    assert "run_research" in names
    assert "plan_patch" in names
    assert "apply_patch" in names


def test_all_plans_have_steps():
    for name, steps in DEFAULT_AUTOMATION_PLANS.items():
        assert len(steps) > 0, f"Plan {name} has no steps"
