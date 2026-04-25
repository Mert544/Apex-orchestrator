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
    assert "safety_gate_check" in names
    assert "apply_patch" in names
    apply_idx = names.index("apply_patch")
    gate_idx = names.index("safety_gate_check")
    assert gate_idx < apply_idx, "safety_gate must come before apply_patch"


def test_full_autonomous_loop_has_safety_gates():
    plan = DEFAULT_AUTOMATION_PLANS["full_autonomous_loop"]
    names = [step.name for step in plan]
    assert "safety_gate_check" in names
    gate_idx = names.index("safety_gate_check")
    apply_idx = names.index("apply_patch")
    assert gate_idx < apply_idx


def test_self_directed_loop_has_safety_gates():
    plan = DEFAULT_AUTOMATION_PLANS["self_directed_loop"]
    names = [step.name for step in plan]
    assert "safety_gate_check" in names
    apply_idx = names.index("apply_patch")
    gate_idx = names.index("safety_gate_check")
    assert gate_idx < apply_idx


def test_all_plans_have_steps():
    for name, steps in DEFAULT_AUTOMATION_PLANS.items():
        assert len(steps) > 0, f"Plan {name} has no steps"


def test_safety_gate_before_apply_in_patch_plans():
    for plan_name in [
        "supervised_patch_loop",
        "semantic_patch_loop",
        "full_autonomous_loop",
        "self_directed_loop",
    ]:
        plan = DEFAULT_AUTOMATION_PLANS[plan_name]
        names = [s.name for s in plan]
        if "apply_patch" in names:
            assert "safety_gate_check" in names, f"Plan {plan_name} missing safety gate"
            assert names.index("safety_gate_check") < names.index("apply_patch")
