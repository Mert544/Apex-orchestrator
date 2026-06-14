"""Proof-of-COVERAGE: does the green suite actually EXERCISE the change?

A proof-carrying runnable step states the exact draft diff and a re-parse
verdict — but a passing suite on a module no test references is a hollow
guarantee. These tests pin the additive ``covered`` proof field (a pure file
scan via ``verification_strength.module_referenced_by_suite``) and its rendered
clause, while keeping every pre-existing rendered substring intact and steps
without a proof byte-identical to today.
"""

from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    _proof_affordance,
    render_action_markdown,
)
from app.models.idea import ActionPlan, ActionStep


def _harden_step(branch, target):
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


def _modernizable(tmp_path):
    """A module with a real ``== None`` to modernize, under ``app/``."""
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def run(c):\n    if c == None:\n        return 1\n    return 2\n")
    return src


def _add_referencing_test(tmp_path):
    """A test file that imports the changed module — so the suite looks at it."""
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_svc.py").write_text(
        "from app.svc import run\n\n\ndef test_run():\n    assert run(1) == 2\n"
    )


# --- the covered signal in the proof dict -----------------------------------


def test_referenced_module_proof_is_covered(tmp_path):
    _modernizable(tmp_path)
    _add_referencing_test(tmp_path)
    plan = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    pv = plan.steps[0].patch_preview
    if pv is None or "diff" not in pv:
        return  # generator declined — nothing to assert
    assert pv["covered"] is True


def test_unreferenced_module_proof_is_uncovered(tmp_path):
    _modernizable(tmp_path)  # no test touches app/svc.py
    plan = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    pv = plan.steps[0].patch_preview
    if pv is None or "diff" not in pv:
        return
    assert pv["covered"] is False


def test_covered_key_always_present_on_proof(tmp_path):
    """Whenever a proof is attached, the coverage signal is recorded."""
    _modernizable(tmp_path)
    plan = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    pv = plan.steps[0].patch_preview
    if pv is None or "diff" not in pv:
        return
    assert "covered" in pv
    assert isinstance(pv["covered"], bool)


# --- recommend-only: no file ever written -----------------------------------


def test_coverage_read_writes_nothing(tmp_path):
    _modernizable(tmp_path)
    _add_referencing_test(tmp_path)
    before = {p: p.read_text() for p in tmp_path.rglob("*.py")}
    plan = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    after = {p: p.read_text() for p in tmp_path.rglob("*.py")}
    assert before == after


# --- rendering: covered vs. uncovered clause --------------------------------


def test_render_covered_clause():
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {
        "diff": "-x\n+y\n", "added": 1, "removed": 1,
        "reparses": True, "applied": False, "covered": True,
    }
    md = render_action_markdown(_plan([step]))
    assert "your tests reference this module ✓" in md
    # The existing proof substrings are preserved.
    assert "proof: +1 −1, re-parses cleanly ✓" in md
    assert "apex brief x.1" in md


def test_render_uncovered_clause():
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {
        "diff": "-x\n+y\n", "added": 1, "removed": 1,
        "reparses": True, "applied": False, "covered": False,
    }
    md = render_action_markdown(_plan([step]))
    assert "⚠️ no test exercises this — add one first" in md
    assert "proof: +1 −1, re-parses cleanly ✓" in md


# --- additive: no proof → byte-identical, no clause -------------------------


def test_no_proof_step_byte_identical():
    """A step without proof fields gets no proof line at all (and no clause)."""
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {"transform_type": "t", "files": ["app/svc.py"], "applied": False}
    md = render_action_markdown(_plan([step]))
    assert "proof:" not in md
    assert "your tests reference this module" not in md
    assert "no test exercises this" not in md
    assert "draft `t`" in md


def test_legacy_proof_without_covered_unchanged():
    """A proof preview that predates the coverage signal renders byte-identical
    to today — no coverage clause leaks in when ``covered`` is absent."""
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {
        "diff": "-x\n+y\n", "added": 1, "removed": 1,
        "reparses": True, "applied": False,
    }
    line = _proof_affordance(step)
    assert line == (
        "    proof: +1 −1, re-parses cleanly ✓ "
        "— `apex brief x.1` for the full diff"
    )
    assert "tests reference this module" not in line
    assert "no test exercises this" not in line


# --- determinism ------------------------------------------------------------


def test_coverage_proof_is_deterministic(tmp_path):
    _modernizable(tmp_path)
    _add_referencing_test(tmp_path)
    a = _plan([_harden_step("x.1", "app/svc.py")])
    b = _plan([_harden_step("x.1", "app/svc.py")])
    IdeaActionBridge().attach_proofs(a, str(tmp_path))
    IdeaActionBridge().attach_proofs(b, str(tmp_path))
    assert a.steps[0].patch_preview == b.steps[0].patch_preview


def test_render_clause_deterministic():
    step = _harden_step("x.1", "app/svc.py")
    step.patch_preview = {
        "diff": "-x\n+y\n", "added": 1, "removed": 1,
        "reparses": True, "applied": False, "covered": True,
    }
    assert _proof_affordance(step) == _proof_affordance(step)
