from app.engine.idea_action_bridge import render_action_markdown
from app.models.idea import ActionPlan, ActionStep

RUNNABLE = "▶ runnable"
ADVISORY = "✎ advisory"


def _step_markers(md):
    """Per-step marker lines only (indented), excluding the legend header."""
    return [ln for ln in md.splitlines() if ln.startswith("    ")]


def _step(branch, action, executable, phase="", description="do the thing"):
    return ActionStep(
        branch_path=branch,
        title="t",
        operator="o",
        subject="app/a.py",
        action_type=action,
        executable=executable,
        description=description,
        phase=phase,
    )


def _mixed_plan():
    steps = [
        _step("x.1", "create_test_stub", True, "Stabilize"),
        _step("x.2", "harden_security", True, "Secure"),
        _step("x.3", "design_task", False),
        _step("x.4", "refactor", False),
    ]
    return ActionPlan(
        project_root="/repo",
        objective="tidy up",
        steps=steps,
        stats={"total_steps": 4, "executable_steps": 2, "design_tasks": 2},
    )


def test_executable_steps_get_runnable_marker():
    md = render_action_markdown(_mixed_plan())
    lines = md.splitlines()
    # Each executable step's bullet is followed by the runnable marker.
    for branch in ("x.1", "x.2"):
        idx = next(i for i, ln in enumerate(lines) if f"`{branch}`" in ln)
        assert RUNNABLE in lines[idx + 1]
        assert "auto-rollback on failure" in lines[idx + 1]
        assert ADVISORY not in lines[idx + 1]


def test_advisory_steps_get_advisory_marker():
    md = render_action_markdown(_mixed_plan())
    lines = md.splitlines()
    for branch in ("x.3", "x.4"):
        idx = next(i for i, ln in enumerate(lines) if f"`{branch}`" in ln)
        assert ADVISORY in lines[idx + 1]
        assert "recommend-only" in lines[idx + 1]
        assert RUNNABLE not in lines[idx + 1]


def test_summary_header_counts_runnable():
    md = render_action_markdown(_mixed_plan())
    assert "**2 of 4 steps are runnable now**" in md


def test_summary_header_with_no_runnable_steps():
    plan = ActionPlan(
        project_root="/repo",
        steps=[_step("x.1", "design_task", False), _step("x.2", "refactor", False)],
        stats={"total_steps": 2, "executable_steps": 0, "design_tasks": 2},
    )
    md = render_action_markdown(plan)
    assert "**0 of 2 steps are runnable now**" in md
    markers = _step_markers(md)
    assert all(RUNNABLE not in ln for ln in markers)
    assert sum(ADVISORY in ln for ln in markers) == 2


def test_summary_header_with_all_runnable_steps():
    plan = ActionPlan(
        project_root="/repo",
        steps=[_step("x.1", "create_test_stub", True), _step("x.2", "harden_security", True)],
        stats={"total_steps": 2, "executable_steps": 2, "design_tasks": 0},
    )
    md = render_action_markdown(plan)
    assert "**2 of 2 steps are runnable now**" in md
    markers = _step_markers(md)
    assert all(ADVISORY not in ln for ln in markers)
    assert md.count("auto-rollback on failure") == 2


def test_empty_plan_summary():
    plan = ActionPlan(project_root="/repo", steps=[],
                      stats={"total_steps": 0, "executable_steps": 0, "design_tasks": 0})
    md = render_action_markdown(plan)
    assert "**0 of 0 steps are runnable now**" in md
    markers = _step_markers(md)
    assert markers == []


def test_existing_substrings_preserved():
    # Substrings asserted by tests/test_idea_action_bridge.py must remain.
    plan = _mixed_plan()
    plan.mode = "supervised"
    plan.steps[0].phase = "Secure"
    md = render_action_markdown(plan)
    assert "Action Plan" in md
    assert "not applied" in md
    assert "[Secure]" in md
    # Per-step content is untouched: action_type, description, value.
    assert "**create_test_stub**" in md
    assert "do the thing" in md
    assert "(v 0.0)" in md


def test_marker_is_additive_not_replacing_bullet():
    md = render_action_markdown(_mixed_plan())
    lines = md.splitlines()
    bullet = next(ln for ln in lines if "`x.1`" in ln)
    # The original bullet line keeps its content; the marker is a separate line.
    assert bullet.startswith("- ")
    assert "**create_test_stub**" in bullet
    assert RUNNABLE not in bullet


def test_render_is_deterministic():
    plan = _mixed_plan()
    assert render_action_markdown(plan) == render_action_markdown(plan)
    assert render_action_markdown(_mixed_plan()) == render_action_markdown(_mixed_plan())
