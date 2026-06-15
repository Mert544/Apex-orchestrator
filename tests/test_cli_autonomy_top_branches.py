"""Deterministic coverage for the `apex develop --top` machinery.

Targets the new _develop_top / _top_runnable_step / _top_proof_lines paths and
the --top branch of cmd_develop in app/cli_autonomy.py.

Everything heavy is monkeypatched: the IdeaPermutationEngine.run, the bridge's
plan_roadmap / apply_plan / prove_step, and verification_strength's
module_referenced_by_suite. NO real pytest suite runs and NO file apply ever
touches the real repo — the proof/apply path stays recommend-only and fast.

No time/random/order assertions; all inputs are explicit Namespaces over a tmp
project tree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import (
    _develop_top,
    _top_proof_lines,
    _top_runnable_step,
    cmd_develop,
)
from app.models.idea import ActionPlan, ActionStep


def _ns(**over) -> argparse.Namespace:
    return argparse.Namespace(**over)


def _top_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(tmp_path), objective="dead-params", goal="",
        all_objectives=False, grade=False, history=False, from_dream=False,
        playbook=False, top=True, force=False, apply=False, max_steps=3,
        no_verify=True, fast=True, json=False,
    )
    base.update(over)
    return _ns(**base)


def _step(**over) -> ActionStep:
    base = dict(
        branch_path="root/secure/0", title="Trim dead parameter",
        operator="dead_params", subject="app/m.py", action_type="refactor",
        target="app/m.py", description="remove unused `b`", executable=True,
        value=42.0, patch_preview=None,
    )
    base.update(over)
    return ActionStep(**base)


def _plan(steps, **over) -> ActionPlan:
    base = dict(objective="dead-params", project_root="/x", mode="supervised",
                steps=steps, stats={"total_steps": len(steps),
                                     "executable_steps": len(steps)})
    base.update(over)
    return ActionPlan(**base)


class _FakeEngine:
    """Stands in for IdeaPermutationEngine — never builds a real idea tree."""

    def __init__(self, **kw):
        self.last_profile = None

    def run(self, objective=None):
        return {"objective": objective}


class _FakeBridge:
    """A bridge whose plan/apply/prove are fully controlled by the test."""

    def __init__(self, plan=None, apply_summary=None, prove=None):
        self._plan = plan if plan is not None else _plan([])
        self._apply_summary = apply_summary or {"results": []}
        self._prove = prove
        self.applied_plans: list = []

    def plan_roadmap(self, report, mode="report", project_root="", proof=False,
                     draft=False):
        return self._plan

    def prove_step(self, step, project_root):
        return self._prove

    def apply_plan(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        self.applied_plans.append(plan)
        return self._apply_summary


def _patch_top(monkeypatch, bridge, covered):
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)
    monkeypatch.setattr(
        "app.engine.verification_strength.module_referenced_by_suite",
        lambda root, target: covered)


# --------------------------------------------------------------------------- #
# _top_runnable_step                                                           #
# --------------------------------------------------------------------------- #
def test_top_runnable_step_picks_first_executable_py():
    advisory = _step(executable=False, branch_path="a")
    non_py = _step(target="README.md", branch_path="b")
    runnable = _step(branch_path="c", target="app/m.py")
    plan = _plan([advisory, non_py, runnable])
    assert _top_runnable_step(plan) is runnable


def test_top_runnable_step_none_when_all_advisory():
    plan = _plan([_step(executable=False), _step(executable=False)])
    assert _top_runnable_step(plan) is None


def test_top_runnable_step_skips_non_py_executable():
    plan = _plan([_step(target="docs/readme.txt"), _step(target="")])
    assert _top_runnable_step(plan) is None


# --------------------------------------------------------------------------- #
# _top_proof_lines                                                             #
# --------------------------------------------------------------------------- #
def test_top_proof_lines_no_proof_declined():
    lines = _top_proof_lines(_step(), None)
    assert any("declined to draft" in ln for ln in lines)
    # header + action + focus + declined = 4 lines
    assert lines[0].startswith("## Top recommendation:")


def test_top_proof_lines_clean_reparse_and_covered():
    proof = {"reparses": True, "added": 3, "removed": 1, "impact": "tidies",
             "covered": True}
    lines = _top_proof_lines(_step(), proof)
    body = "\n".join(lines)
    assert "+3 −1" in body
    assert "re-parses cleanly" in body
    assert "tidies" in body
    assert "your tests reference this module" in body


def test_top_proof_lines_failed_reparse_uncovered_no_impact():
    proof = {"reparses": False, "added": 0, "removed": 0, "covered": False}
    lines = _top_proof_lines(_step(), proof)
    body = "\n".join(lines)
    assert "re-parse check failed" in body
    assert "no test exercises this" in body


# --------------------------------------------------------------------------- #
# _develop_top — no runnable step                                             #
# --------------------------------------------------------------------------- #
def test_develop_top_no_runnable_step_markdown(tmp_path, capsys, monkeypatch):
    bridge = _FakeBridge(plan=_plan([_step(executable=False)]))
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No runnable recommendation" in out


def test_develop_top_no_runnable_step_json(tmp_path, capsys, monkeypatch):
    bridge = _FakeBridge(plan=_plan([]))
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, json=True), tmp_path)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == {"top": None, "applied": False, "reason": "no-runnable-step"}


# --------------------------------------------------------------------------- #
# _develop_top — dry run (default)                                            #
# --------------------------------------------------------------------------- #
def test_develop_top_dry_run_covered_markdown(tmp_path, capsys, monkeypatch):
    proof = {"diff": "x", "reparses": True, "added": 1, "removed": 0,
             "covered": True}
    bridge = _FakeBridge(plan=_plan([_step(patch_preview=proof)]))
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "re-run with --apply to land it." in out
    # covered -> no false-green heads-up
    assert "false green" not in out


def test_develop_top_dry_run_uncovered_warns(tmp_path, capsys, monkeypatch):
    bridge = _FakeBridge(plan=_plan([_step()]))
    _patch_top(monkeypatch, bridge, covered=False)
    rc = _develop_top(_top_ns(tmp_path), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no test exercises this module" in out
    assert "re-run with --apply to land it." in out


def test_develop_top_dry_run_json_proves_via_fallback(tmp_path, capsys, monkeypatch):
    """No proof on the step -> prove_step fallback is used, surfaced in payload."""
    fresh = {"reparses": True, "added": 2, "removed": 0, "covered": True}
    bridge = _FakeBridge(plan=_plan([_step(patch_preview=None)]), prove=fresh)
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, json=True), tmp_path)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is False
    assert payload["proof"] == fresh
    assert payload["covered"] is True


# --------------------------------------------------------------------------- #
# _develop_top — blind-spot (false-green) guard                              #
# --------------------------------------------------------------------------- #
def test_develop_top_apply_uncovered_blocked_markdown(tmp_path, capsys, monkeypatch):
    bridge = _FakeBridge(plan=_plan([_step()]))
    _patch_top(monkeypatch, bridge, covered=False)
    rc = _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 2
    assert "FALSE green" in out
    # the guard must never reach apply_plan
    assert bridge.applied_plans == []


def test_develop_top_apply_uncovered_blocked_json(tmp_path, capsys, monkeypatch):
    bridge = _FakeBridge(plan=_plan([_step()]))
    _patch_top(monkeypatch, bridge, covered=False)
    rc = _develop_top(_top_ns(tmp_path, apply=True, json=True), tmp_path)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["reason"] == "false-green-guard"
    assert "warning" in payload
    assert bridge.applied_plans == []


# --------------------------------------------------------------------------- #
# _develop_top — apply paths (single-step guarded loop, all stubbed)         #
# --------------------------------------------------------------------------- #
def test_develop_top_apply_covered_verified(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "applied and verified" in out
    assert "review with `git diff`" in out
    # exactly one step was routed through the guarded apply loop
    assert len(bridge.applied_plans) == 1
    assert len(bridge.applied_plans[0].steps) == 1


def test_develop_top_apply_rolled_back_rc1(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": False, "rolled_back": True,
                            "verified": False}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "rolled back" in out


def test_develop_top_apply_not_applied_rc1(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": False, "rolled_back": False,
                            "reason": "no applicable patch"}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out
    assert "no applicable patch" in out


def test_develop_top_apply_covered_no_test_command(tmp_path, capsys, monkeypatch):
    """Applied, covered, but verified is falsy -> 'no test command' verdict."""
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": None}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no test command detected" in out


def test_develop_top_force_apply_uncovered_weak(tmp_path, capsys, monkeypatch):
    """--force lets an uncovered apply through, labeled weak verification."""
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=False)
    rc = _develop_top(_top_ns(tmp_path, apply=True, force=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "weak verification" in out
    assert len(bridge.applied_plans) == 1


def test_develop_top_force_apply_uncovered_json(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=False)
    rc = _develop_top(_top_ns(tmp_path, apply=True, force=True, json=True),
                      tmp_path)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True
    assert payload["covered"] is False
    assert "weak verification" in payload["verdict"]
    assert "apply_summary" in payload


def test_develop_top_apply_empty_results_defaults(tmp_path, capsys, monkeypatch):
    """An empty results list falls back to {} -> not-applied verdict, rc 1."""
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary={"results": []})
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out


# --------------------------------------------------------------------------- #
# cmd_develop --top dispatch                                                  #
# --------------------------------------------------------------------------- #
def test_cmd_develop_top_dispatches(tmp_path, capsys, monkeypatch):
    """cmd_develop routes the --top flag into _develop_top (json no-step path)."""
    bridge = _FakeBridge(plan=_plan([]))
    _patch_top(monkeypatch, bridge, covered=True)
    rc = cmd_develop(_top_ns(tmp_path, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["reason"] == "no-runnable-step"
