"""`apex develop --top`: close the loop on the SINGLE highest-value proven,
runnable recommendation, COVERAGE-AWARE so a green suite can never claim a
false "verified" on a module no test exercises.

Two flavors of coverage here:
  - Real-engine integration on tiny tmp_path projects (deterministic: the same
    project yields the same #1 runnable step every run). These exercise the full
    wiring — engine → proof-carrying roadmap plan → top-step selection → proof
    render → blind-spot guard → dry run.
  - Monkeypatched-plan unit tests that hand a single, fixed step to
    ``_develop_top`` and stub ``apply_plan``/``module_referenced_by_suite`` so the
    guarded loop is fast, never spawns a subprocess, and the false-green guard /
    weak-verification verdict logic is asserted exactly.

No time/random/order asserts; nothing here runs the real pytest suite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import _develop_top, _top_runnable_step, cmd_develop
from app.models.idea import ActionPlan, ActionStep


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _ns(**over) -> argparse.Namespace:
    base = dict(
        target="", objective="", goal="", all_objectives=False, grade=False,
        history=False, from_dream=False, playbook=False, apply=False, top=True,
        force=False, max_steps=5, no_verify=True, fast=True, json=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _covered_project(tmp_path: Path) -> Path:
    """A project whose `app/m.py` IS referenced by a test (importable + named)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    return tmp_path


def _uncovered_project(tmp_path: Path) -> Path:
    """A project whose `app/lonely.py` is referenced by NO test."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "lonely.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_other.py").write_text(
        "def test_trivial():\n    assert True\n"
    )
    return tmp_path


def _step(target: str = "app/m.py", **over) -> ActionStep:
    base = dict(
        branch_path="x.a.b", title="Test → Document: app/m.py", operator="doc",
        subject="app/m.py", action_type="add_docstring", target=target,
        description="Add docstrings to app/m.py", executable=True, value=0.67,
        patch_preview={"diff": "--- a/app/m.py\n+++ b/app/m.py\n",
                       "added": 1, "removed": 0, "reparses": True,
                       "impact": "", "covered": True, "applied": False},
    )
    base.update(over)
    return ActionStep(**base)


# --------------------------------------------------------------------------- #
# _top_runnable_step — selection by plan order                                #
# --------------------------------------------------------------------------- #
def test_top_runnable_step_picks_first_executable_py():
    advisory = ActionStep(branch_path="x.a", title="advise", operator="o",
                          subject="s", action_type="observe", target="",
                          executable=False, value=0.99)
    non_py = ActionStep(branch_path="x.b", title="cfg", operator="o",
                        subject="s", action_type="edit", target="setup.cfg",
                        executable=True, value=0.9)
    runnable = _step(value=0.5)
    plan = ActionPlan(steps=[advisory, non_py, runnable])
    chosen = _top_runnable_step(plan)
    assert chosen is runnable  # first executable .py in plan order, not by value


def test_top_runnable_step_none_when_all_advisory():
    advisory = ActionStep(branch_path="x.a", title="advise", operator="o",
                          subject="s", action_type="observe", target="",
                          executable=False, value=0.99)
    assert _top_runnable_step(ActionPlan(steps=[advisory])) is None


# --------------------------------------------------------------------------- #
# real-engine integration: covered module, dry run                            #
# --------------------------------------------------------------------------- #
def test_top_dry_run_shows_proof_covered(tmp_path, capsys):
    _covered_project(tmp_path)
    rc = cmd_develop(_ns(target=str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Top recommendation" in out
    assert "proof:" in out
    assert "your tests reference this module" in out  # coverage verdict ✓
    assert "re-run with --apply to land it." in out
    # dry run changed nothing
    assert (tmp_path / "app" / "m.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_top_dry_run_json_mirrors_outcome(tmp_path, capsys):
    _covered_project(tmp_path)
    rc = cmd_develop(_ns(target=str(tmp_path), json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is False
    assert payload["covered"] is True
    assert payload["top"]["target"].endswith(".py")
    assert payload["proof"]["reparses"] is True


def test_top_dry_run_is_deterministic(tmp_path, capsys):
    _covered_project(tmp_path)
    cmd_develop(_ns(target=str(tmp_path), json=True))
    first = capsys.readouterr().out
    cmd_develop(_ns(target=str(tmp_path), json=True))
    second = capsys.readouterr().out
    assert first == second  # same input → same output (no time/random)


# --------------------------------------------------------------------------- #
# real-engine integration: no runnable step → advisory message, rc 0          #
# --------------------------------------------------------------------------- #
def test_top_no_runnable_step_advisory(tmp_path, capsys):
    # An empty project yields only advisory ideas (nothing executable).
    rc = cmd_develop(_ns(target=str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "No runnable recommendation right now" in out


def test_top_no_runnable_step_json(tmp_path, capsys):
    rc = cmd_develop(_ns(target=str(tmp_path), json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["top"] is None
    assert payload["applied"] is False
    assert payload["reason"] == "no-runnable-step"


# --------------------------------------------------------------------------- #
# the blind-spot fix (false green): uncovered target + --apply               #
# --------------------------------------------------------------------------- #
def _stub_apply(monkeypatch):
    """Stub apply_plan so the guarded loop never spawns pytest; record the call
    and report a clean single-step apply."""
    calls: list = []

    def fake_apply(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        calls.append({"steps": len(plan.steps), "max_apply": max_apply,
                      "verify": verify})
        return {"results": [{"applied": True, "rolled_back": False,
                             "verified": None}],
                "applied": 1, "rolled_back": 0}

    from app.engine.idea_action_bridge import IdeaActionBridge
    monkeypatch.setattr(IdeaActionBridge, "apply_plan", fake_apply)
    return calls


def _force_plan(monkeypatch, step: ActionStep):
    """Make plan_roadmap return a fixed one-step plan (deterministic selection)."""
    from app.engine.idea_action_bridge import IdeaActionBridge

    def fake_plan(self, report, *a, **k):
        return ActionPlan(objective="dead-params", project_root="", steps=[step])

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", fake_plan)
    # the permutation engine still runs but cheaply on a tiny project


def test_false_green_guard_blocks_without_force(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    calls = _stub_apply(monkeypatch)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: False)

    before = (tmp_path / "app" / "lonely.py").read_text()
    rc = cmd_develop(_ns(target=str(tmp_path), apply=True, force=False))
    out = capsys.readouterr().out

    assert rc == 2  # non-zero so CI/automation notices
    assert "FALSE green" in out
    assert "app/lonely.py" in out
    assert "--force" in out
    assert calls == []  # apply_plan was NOT called — nothing landed
    assert (tmp_path / "app" / "lonely.py").read_text() == before  # untouched


def test_false_green_guard_json_non_zero(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: False)

    rc = cmd_develop(_ns(target=str(tmp_path), apply=True, force=False, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["reason"] == "false-green-guard"
    assert payload["covered"] is False
    assert payload["applied"] is False
    assert "warning" in payload


def test_force_applies_and_labels_weak_verification(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    calls = _stub_apply(monkeypatch)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: False)

    rc = cmd_develop(_ns(target=str(tmp_path), apply=True, force=True))
    out = capsys.readouterr().out

    assert rc == 0  # it landed
    assert len(calls) == 1
    assert calls[0]["max_apply"] == 1  # single-step guarded apply
    assert calls[0]["steps"] == 1
    assert "weak verification" in out  # NOT a plain "verified"
    assert "applied" in out.lower()


def test_force_json_weak_verification_verdict(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: False)

    rc = cmd_develop(_ns(target=str(tmp_path), apply=True, force=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True
    assert payload["covered"] is False
    assert "weak verification" in payload["verdict"]


# --------------------------------------------------------------------------- #
# covered module + --apply: real guarded apply (max_apply=1), honest verdict   #
# --------------------------------------------------------------------------- #
def test_top_apply_covered_lands_and_verifies(tmp_path, monkeypatch, capsys):
    _covered_project(tmp_path)
    step = _step(target="app/m.py")
    _force_plan(monkeypatch, step)
    calls = _stub_apply(monkeypatch)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: True)
    # apply_plan stub reports verified=None; make it verified=True for this case
    from app.engine.idea_action_bridge import IdeaActionBridge

    def verified_apply(self, plan, root, **k):
        calls.append({"max_apply": k.get("max_apply")})
        return {"results": [{"applied": True, "rolled_back": False,
                             "verified": True}], "applied": 1}

    monkeypatch.setattr(IdeaActionBridge, "apply_plan", verified_apply)

    rc = cmd_develop(_ns(target=str(tmp_path), apply=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "applied and verified" in out
    assert calls[-1]["max_apply"] == 1  # only the one chosen step


def test_top_apply_rolled_back_returns_non_zero(tmp_path, monkeypatch, capsys):
    _covered_project(tmp_path)
    step = _step(target="app/m.py")
    _force_plan(monkeypatch, step)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: True)
    from app.engine.idea_action_bridge import IdeaActionBridge

    def rollback_apply(self, plan, root, **k):
        return {"results": [{"applied": False, "rolled_back": True,
                             "verified": False}], "applied": 0, "rolled_back": 1}

    monkeypatch.setattr(IdeaActionBridge, "apply_plan", rollback_apply)

    rc = cmd_develop(_ns(target=str(tmp_path), apply=True))
    out = capsys.readouterr().out
    assert rc == 1  # the step we set out to land did not land
    assert "rolled back" in out


# --------------------------------------------------------------------------- #
# _develop_top directly (bypassing cmd_develop dispatch) for the proof block   #
# --------------------------------------------------------------------------- #
def test_develop_top_direct_proof_block(tmp_path, monkeypatch, capsys):
    _covered_project(tmp_path)
    step = _step(target="app/m.py")
    _force_plan(monkeypatch, step)
    monkeypatch.setattr("app.engine.verification_strength.module_referenced_by_suite", lambda r, p: True)
    rc = _develop_top(_ns(target=str(tmp_path)), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "add_docstring" in out
    assert "app/m.py" in out
