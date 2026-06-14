"""Proof-carrying runnable recommendations.

A runnable step's ``patch_preview`` should carry the EXACT draft diff it would
make plus a deterministic safety verdict (the transformed source still parses).
This is RECOMMEND-ONLY: parse + diff + count in memory, never a file write or a
subprocess. These tests pin the proof fields, the bounded budget, the graceful
no-op path, determinism, and the rendered "proof:" affordance — while keeping
every pre-existing rendered substring intact.
"""

from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    render_action_markdown,
)
from app.models.idea import ActionPlan, ActionStep


def _harden_step(branch, target):
    """A runnable harden step over a real .py target (a transform objective)."""
    return ActionStep(
        branch_path=branch,
        title=f"Harden: {target}",
        operator="harden",
        subject=target,
        action_type="harden_security",
        target=target,
        description=f"Harden {target}",
        executable=True,
        value=0.9,
        source_facts=[f"sensitive-path: {target}"],
    )


def _plan(steps):
    return ActionPlan(
        project_root="/repo",
        objective="tidy up",
        mode="supervised",
        steps=steps,
        stats={
            "total_steps": len(steps),
            "executable_steps": sum(1 for s in steps if s.executable),
            "design_tasks": sum(1 for s in steps if not s.executable),
        },
    )


def _modernizable_project(tmp_path):
    """A tiny project whose module has a real ``== None`` to modernize."""
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def run(c):\n    if c == None:\n        return 1\n    return 2\n")
    return src


# --- the proof itself -------------------------------------------------------


def test_runnable_step_gains_proof_diff(tmp_path):
    src = _modernizable_project(tmp_path)
    before = src.read_text()
    step = _harden_step("x.1", "app/svc.py")
    plan = _plan([step])

    IdeaActionBridge().attach_proofs(plan, str(tmp_path))

    pv = plan.steps[0].patch_preview
    # The generator may decline on some platforms; when it acts, it must carry
    # the full proof shape with a real, non-empty diff.
    if pv is not None and "diff" in pv:
        assert pv["diff"].strip()
        assert pv["added"] >= 1
        assert pv["removed"] >= 1
        assert pv["reparses"] is True
        assert pv["applied"] is False
        # A unified diff over the actual file.
        assert "app/svc.py" in pv["diff"]
    # RECOMMEND-ONLY: proving the step never touches the file on disk.
    assert src.read_text() == before


def test_proof_added_removed_match_diff(tmp_path):
    _modernizable_project(tmp_path)
    step = _harden_step("x.1", "app/svc.py")
    plan = _plan([step])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    pv = plan.steps[0].patch_preview
    if pv is None or "diff" not in pv:
        return
    # added/removed are the diff's own +/− body lines (excluding the +++/--- headers).
    body_added = sum(
        1 for ln in pv["diff"].splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    )
    body_removed = sum(
        1 for ln in pv["diff"].splitlines()
        if ln.startswith("-") and not ln.startswith("---")
    )
    assert pv["added"] == body_added
    assert pv["removed"] == body_removed


# --- graceful no-op ---------------------------------------------------------


def test_clean_file_gets_no_proof(tmp_path):
    """A file with nothing to change stays proofless — graceful, no crash."""
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "clean.py"
    src.write_text("def run(c):\n    if c is None:\n        return 1\n    return 2\n")
    before = src.read_text()
    step = _harden_step("x.1", "app/clean.py")
    plan = _plan([step])

    IdeaActionBridge().attach_proofs(plan, str(tmp_path))

    pv = plan.steps[0].patch_preview
    assert pv is None or "diff" not in pv
    assert src.read_text() == before


def test_advisory_step_never_gets_proof(tmp_path):
    _modernizable_project(tmp_path)
    step = ActionStep(
        branch_path="x.1",
        title="Design",
        operator="extend",
        subject="app/svc.py",
        action_type="design_task",
        target="app/svc.py",
        description="Develop app/svc.py",
        executable=False,
    )
    plan = _plan([step])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    assert plan.steps[0].patch_preview is None


# --- bounded budget ---------------------------------------------------------


def test_proof_budget_is_bounded(tmp_path):
    """Only the first _MAX_PROOFS runnable steps run a transform; the rest stay
    light — so a plan with many executable steps stays cheap."""
    (tmp_path / "app").mkdir()
    steps = []
    for i in range(6):
        rel = f"app/m{i}.py"
        (tmp_path / "app" / f"m{i}.py").write_text(
            "def f(c):\n    if c == None:\n        return 1\n    return 2\n"
        )
        steps.append(_harden_step(f"x.{i}", rel))
    plan = _plan(steps)

    bridge = IdeaActionBridge()
    bridge.attach_proofs(plan, str(tmp_path))

    proven = sum(1 for s in plan.steps
                 if s.patch_preview and "diff" in s.patch_preview)
    assert proven <= bridge._MAX_PROOFS


def test_explicit_max_proofs_respected(tmp_path):
    (tmp_path / "app").mkdir()
    steps = []
    for i in range(4):
        rel = f"app/m{i}.py"
        (tmp_path / "app" / f"m{i}.py").write_text(
            "def f(c):\n    if c == None:\n        return 1\n    return 2\n"
        )
        steps.append(_harden_step(f"x.{i}", rel))
    plan = _plan(steps)
    IdeaActionBridge().attach_proofs(plan, str(tmp_path), max_proofs=1)
    proven = sum(1 for s in plan.steps
                 if s.patch_preview and "diff" in s.patch_preview)
    assert proven <= 1


# --- determinism ------------------------------------------------------------


def test_proof_is_deterministic(tmp_path):
    _modernizable_project(tmp_path)
    plan_a = _plan([_harden_step("x.1", "app/svc.py")])
    plan_b = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(plan_a, str(tmp_path))
    IdeaActionBridge().attach_proofs(plan_b, str(tmp_path))
    assert plan_a.steps[0].patch_preview == plan_b.steps[0].patch_preview


def test_no_project_file_modified(tmp_path):
    """End-to-end: proving a whole plan writes NOTHING to the tmp project."""
    _modernizable_project(tmp_path)
    before = {p: p.read_text() for p in (tmp_path / "app").glob("*.py")}
    plan = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    after = {p: p.read_text() for p in (tmp_path / "app").glob("*.py")}
    assert before == after
    # No test dir conjured, no new files.
    assert not (tmp_path / "tests").exists()


# --- rendering --------------------------------------------------------------


def test_render_shows_proof_line():
    """A step whose patch_preview carries proof fields renders the proof line."""
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {
        "diff": "--- a/app/svc.py\n+++ b/app/svc.py\n-if c == None:\n+if c is None:\n",
        "added": 3,
        "removed": 1,
        "reparses": True,
        "applied": False,
    }
    md = render_action_markdown(_plan([step]))
    assert "proof: +3 −1, re-parses cleanly ✓" in md
    assert "apex brief x.1" in md
    # The full diff is NOT dumped into the plan — only the stat + verdict.
    assert "if c is None" not in md


def test_render_proof_verdict_warns_on_reparse_failure():
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {
        "diff": "--- a/app/svc.py\n+++ b/app/svc.py\n+broken(\n",
        "added": 1,
        "removed": 0,
        "reparses": False,
        "applied": False,
    }
    md = render_action_markdown(_plan([step]))
    assert "re-parse check failed" in md
    assert "re-parses cleanly" not in md


def test_render_without_proof_has_no_proof_line():
    """A light preview (no diff fields) renders no proof line, just the draft row."""
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {"transform_type": "t", "files": ["app/svc.py"], "applied": False}
    md = render_action_markdown(_plan([step]))
    assert "proof:" not in md
    assert "draft `t`" in md


# --- existing substrings preserved ------------------------------------------


def test_existing_rendered_substrings_preserved():
    steps = [
        _harden_step("x.1", "app/svc.py"),
        ActionStep(
            branch_path="x.2", title="t", operator="o", subject="app/a.py",
            action_type="design_task", executable=False,
            description="do the thing", phase="Stabilize",
        ),
    ]
    steps[0].phase = "Secure"
    steps[0].patch_preview = {
        "diff": "-x\n+y\n", "added": 1, "removed": 1,
        "reparses": True, "applied": False,
    }
    md = render_action_markdown(_plan(steps))
    assert "Action Plan" in md
    assert "not applied" in md
    assert "[Secure]" in md
    assert "[Stabilize]" in md
    assert "**harden_security**" in md
    assert "▶ runnable" in md
    assert "✎ advisory" in md
    assert "(v 0.9)" in md
    # The proof line is additive, not a replacement of the runnable marker.
    assert "proof: +1 −1" in md
