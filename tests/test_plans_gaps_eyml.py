from app.automation.models import AutomationStep
from app.automation.plans import DEFAULT_AUTOMATION_PLANS

# plans.py is already at 100% line coverage from tests/test_automation_plans.py;
# these are characterization/regression tests that pin structural invariants of
# the shipped plan catalogue (not coverage padding).


def test_every_plan_step_is_an_automation_step():
    for name, steps in DEFAULT_AUTOMATION_PLANS.items():
        for step in steps:
            assert isinstance(step, AutomationStep), name
            assert step.name
            assert step.skill_name


def test_safety_gate_step_has_expected_wiring():
    # The private _safety_gate_step() helper is exercised indirectly via the
    # plans that embed it; pin its exact name/skill pairing.
    for plan_name in (
        "supervised_patch_loop",
        "semantic_patch_loop",
        "full_autonomous_loop",
        "self_directed_loop",
    ):
        gate = [s for s in DEFAULT_AUTOMATION_PLANS[plan_name] if s.name == "safety_gate_check"]
        assert len(gate) == 1
        assert gate[0].skill_name == "enhanced_safety_check"


def test_expected_plan_names_present():
    expected = {
        "project_scan",
        "focused_branch",
        "verify_project",
        "prepare_repo",
        "clone_and_scan",
        "supervised_patch_loop",
        "supervised_apply_loop",
        "semantic_patch_loop",
        "semantic_apply_loop",
        "git_pr_loop",
        "full_autonomous_loop",
        "telemetry_only",
        "self_directed_loop",
    }
    assert expected <= set(DEFAULT_AUTOMATION_PLANS)


def test_full_autonomous_loop_ends_with_reporting_steps():
    names = [s.name for s in DEFAULT_AUTOMATION_PLANS["full_autonomous_loop"]]
    assert names[-2:] == ["record_telemetry", "export_token_report"]


def test_apply_loops_clone_before_research():
    for plan_name in ("supervised_apply_loop", "semantic_apply_loop", "clone_and_scan"):
        names = [s.name for s in DEFAULT_AUTOMATION_PLANS[plan_name]]
        assert names[0] == "clone_repo"


def test_verify_project_runs_profile_then_tests():
    names = [s.name for s in DEFAULT_AUTOMATION_PLANS["verify_project"]]
    assert names == ["profile_project", "run_tests"]
