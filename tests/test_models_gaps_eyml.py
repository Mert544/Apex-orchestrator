from __future__ import annotations

from pathlib import Path

from app.automation.models import (
    AutomationContext,
    AutomationRunResult,
    AutomationStep,
    AutomationStepResult,
)


def test_to_dict_serializes_steps_and_final_output():
    # Covers the to_dict body (models.py:42) plus the step comprehension.
    result = AutomationRunResult(
        plan_name="semantic_patch_loop",
        steps=[
            AutomationStepResult(
                step_name="run_research",
                skill_name="run_research",
                status="ok",
                output={"found": 1},
            ),
            AutomationStepResult(
                step_name="apply_patch",
                skill_name="apply_patch",
                status="error",
                output=None,
                error="boom",
                error_type="ValueError",
            ),
        ],
        final_output="done",
    )

    data = result.to_dict()

    assert data["plan_name"] == "semantic_patch_loop"
    assert data["final_output"] == "done"
    assert len(data["steps"]) == 2
    first, second = data["steps"]
    assert first == {
        "step_name": "run_research",
        "skill_name": "run_research",
        "status": "ok",
        "output": {"found": 1},
        "error": None,
        "error_type": None,
    }
    assert second["status"] == "error"
    assert second["error"] == "boom"
    assert second["error_type"] == "ValueError"


def test_to_dict_with_no_steps_returns_empty_list():
    result = AutomationRunResult(plan_name="telemetry_only")

    data = result.to_dict()

    assert data == {
        "plan_name": "telemetry_only",
        "steps": [],
        "final_output": None,
    }


def test_run_result_defaults_are_independent_lists():
    a = AutomationRunResult(plan_name="a")
    b = AutomationRunResult(plan_name="b")
    a.steps.append(
        AutomationStepResult(step_name="s", skill_name="s", status="ok")
    )
    assert a.steps != b.steps
    assert b.steps == []


def test_automation_context_optional_fields_default():
    ctx = AutomationContext(
        project_root=Path("/tmp/project"),
        objective="raise coverage",
        config={"k": "v"},
    )
    assert ctx.focus_branch is None
    assert ctx.repo_url is None
    assert ctx.workspace_dir is None
    assert ctx.state == {}
    assert ctx.config == {"k": "v"}


def test_automation_context_state_default_is_independent():
    first = AutomationContext(project_root=Path("."), objective="o", config={})
    second = AutomationContext(project_root=Path("."), objective="o", config={})
    first.state["seen"] = True
    assert second.state == {}


def test_automation_step_holds_name_and_skill():
    step = AutomationStep(name="profile_project", skill_name="profile_project")
    assert step.name == "profile_project"
    assert step.skill_name == "profile_project"


def test_step_result_defaults_are_none():
    r = AutomationStepResult(step_name="x", skill_name="x", status="ok")
    assert r.output is None
    assert r.error is None
    assert r.error_type is None
