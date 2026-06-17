"""DEEP mutation-hardening for app/cli_autonomy.py.

This file kills the survivors the default 30-mutant cap masks in this large CLI.
The full single-token mutant universe (346 splice-valid mutants) was enumerated
with the project's own mutation engine; the survivors of the scoped covering
suite are killed here one behaviour at a time, or named EQUIVALENT below.

Everything heavy (engines, bridges, compilers, simulation, evolution,
subprocess) is monkeypatched at the source module so no real idea tree, grader,
or pytest subprocess runs. Collaborator inputs are CAPTURED so the exact
numeric/boolean config a command forwards is asserted (that is what kills the
config-constant and parser-default mutants). No time/random/order assertions.

EQUIVALENT mutants (behaviour-preserving, hence unkillable by any test) are
documented in ``test_equivalent_mutants_are_documented`` at the end.
"""

from __future__ import annotations

import argparse
import json

import pytest

import app.cli_autonomy as m
from app.cli_autonomy import (
    _develop_top,
    _print_grade_proof,
    _shield_stub_path,
    _target_score,
    _top_payload,
    _top_proof_lines,
    cmd_develop,
    register_parsers,
)
from app.models.idea import ActionPlan, ActionStep
from app.cli_autonomy import _maintain_scope_recipe as _m_scope


# --------------------------------------------------------------------------- #
# Shared helpers / fakes (mirroring the existing cli_autonomy test style).     #
# --------------------------------------------------------------------------- #
def _ns(**over) -> argparse.Namespace:
    return argparse.Namespace(**over)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    register_parsers(sub)
    return p


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
    """Captures the config dict it was constructed with so the numeric
    permutation-config constants (max_total_ideas / depth / breadth) are pinned."""

    last_config: dict | None = None

    def __init__(self, *a, config=None, **kw):
        type(self).last_config = config
        self.last_profile = None

    def run(self, objective=None):
        _FakeEngine.last_objective = objective
        return {"objective": objective}


class _FakeBridge:
    def __init__(self, plan=None, apply_summary=None, prove=None):
        self._plan = plan if plan is not None else _plan([])
        self._apply_summary = apply_summary or {"results": []}
        self._prove = prove
        self.applied: list = []

    def plan_roadmap(self, report, mode="report", project_root="", proof=False,
                     draft=False):
        _FakeBridge.last_roadmap_kwargs = dict(mode=mode, proof=proof, draft=draft)
        return self._plan

    def prove_step(self, step, project_root):
        return self._prove

    def apply_plan(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        self.applied.append(dict(mode=mode, verify=verify, max_apply=max_apply,
                                 commit=commit))
        return self._apply_summary


# =========================================================================== #
# _target_score / _LETTER_MIN — every letter floor is load-bearing.            #
# Kills number mutants at lines 1031–1032 (the letter cutoffs).                #
# =========================================================================== #
@pytest.mark.parametrize("letter,floor", [
    ("A+", 97), ("A", 93), ("A-", 90), ("B+", 87), ("B", 83), ("B-", 80),
    ("C+", 77), ("C", 73), ("C-", 70), ("D+", 67), ("D", 63), ("D-", 60),
])
def test_target_score_letter_floors_exact(letter, floor):
    assert _target_score(letter) == floor
    assert _target_score(letter.lower()) == floor


def test_target_score_integer_and_unknown():
    assert _target_score("88") == 88
    assert _target_score("") is None
    assert _target_score("ZZ") is None


# =========================================================================== #
# register_parsers — every numeric default is load-bearing (kills the          #
# parser-default number mutants 1115/1117/1153/1166/1168/1180/1182/1240/       #
# 1272/1273/1275/1294).                                                        #
# =========================================================================== #
def test_ascend_parser_numeric_defaults():
    ns = _parser().parse_args(["ascend"])
    assert ns.max_rounds == 4
    assert ns.max_steps == 25


def test_auto_parser_numeric_defaults():
    ns = _parser().parse_args(["auto"])
    assert ns.max_apply == 0


def test_simulate_parser_numeric_defaults():
    ns = _parser().parse_args(["simulate"])
    assert ns.max_cycles == 3
    assert ns.max_apply == 5


def test_evolve_parser_numeric_defaults():
    ns = _parser().parse_args(["evolve"])
    assert ns.max_cycles == 3
    assert ns.max_apply == 5


def test_develop_parser_numeric_defaults():
    ns = _parser().parse_args(["develop"])
    assert ns.max_steps == 25


def test_maintain_parser_numeric_defaults():
    ns = _parser().parse_args(["maintain"])
    assert ns.depth == 2
    assert ns.breadth == 4
    assert ns.top == 0
    assert ns.max_apply == 0


def test_maintain_parser_overrides_are_typed_ints():
    ns = _parser().parse_args(
        ["maintain", "--depth", "7", "--breadth", "9", "--top", "3",
         "--max-apply", "11"])
    assert ns.depth == 7 and ns.breadth == 9 and ns.top == 3
    assert ns.max_apply == 11


# =========================================================================== #
# _print_grade_proof — the numeric/relational boundaries are load-bearing.     #
# =========================================================================== #
def _capture_record_run(monkeypatch):
    seen = {}

    def _rec(target, objective, moves, before, after):
        seen.update(target=target, objective=objective, moves=moves,
                    before=before, after=after)
    monkeypatch.setattr("app.engine.dev_history.record_run", _rec)
    return seen


def test_grade_proof_before_zero_still_reports(capsys, monkeypatch):
    # before == 0 must NOT trip the `before < 0` guard (kills `<`->`<=` and
    # the `0`->`1` flip at line 897 — either would early-return with no output).
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 5)
    _capture_record_run(monkeypatch)
    _print_grade_proof("/x", before=0, applied=True, objective="tidy", moves=1)
    out = capsys.readouterr().out
    assert "0 → 5" in out
    assert "(+5 ↑)" in out


def test_grade_proof_after_zero_still_reports(capsys, monkeypatch):
    # after == 0 must NOT trip `after < 0` (kills `<`->`<=` and `0`->`1` at 900).
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 0)
    _capture_record_run(monkeypatch)
    _print_grade_proof("/x", before=5, applied=True, objective="tidy", moves=1)
    out = capsys.readouterr().out
    assert "5 → 0" in out
    assert "(-5 ↓)" in out


def test_grade_proof_delta_one_is_positive_sign(capsys, monkeypatch):
    # delta == 1 must render a "+" sign (kills `delta > 0`->`delta > 1` at 904).
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 6)
    _capture_record_run(monkeypatch)
    _print_grade_proof("/x", before=5, applied=True, objective="tidy", moves=1)
    out = capsys.readouterr().out
    assert "(+1 ↑)" in out


def test_grade_proof_equal_uses_right_arrow_no_sign(capsys, monkeypatch):
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 50)
    _capture_record_run(monkeypatch)
    _print_grade_proof("/x", before=50, applied=True, objective="tidy", moves=1)
    out = capsys.readouterr().out
    assert "50 → 50 (0 →)" in out


def test_grade_proof_blank_objective_records_develop(capsys, monkeypatch):
    # `objective or "develop"` (line 909): empty objective records "develop"
    # (kills the `or`->`and` flip, which would record "" instead).
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 60)
    seen = _capture_record_run(monkeypatch)
    _print_grade_proof("/x", before=55, applied=True, objective="", moves=2)
    assert seen["objective"] == "develop"
    assert seen["moves"] == 2
    assert seen["before"] == 55 and seen["after"] == 60


# =========================================================================== #
# Permutation-config constants (40 / 2 / 4) forwarded to the engine.           #
# Kills the number mutants on the config dicts at lines 312, 427, 847.         #
# =========================================================================== #
def _patch_top(monkeypatch, bridge, covered):
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)
    monkeypatch.setattr(
        "app.engine.verification_strength.module_referenced_by_suite",
        lambda root, target: covered)


def _top_ns(tmp_path, **over):
    base = dict(
        target=str(tmp_path), objective="dead-params", goal="",
        all_objectives=False, grade=False, history=False, from_dream=False,
        playbook=False, top=True, force=False, apply=False, max_steps=3,
        no_verify=True, fast=True, json=False, shield=False,
    )
    base.update(over)
    return _ns(**base)


def test_develop_top_forwards_exact_permutation_config(tmp_path, monkeypatch):
    bridge = _FakeBridge(plan=_plan([]))
    _patch_top(monkeypatch, bridge, covered=True)
    _FakeEngine.last_config = None
    _develop_top(_top_ns(tmp_path), tmp_path)
    assert _FakeEngine.last_config == {
        "max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4}


def test_cmd_auto_forwards_exact_permutation_config(tmp_path, monkeypatch):
    # Line 312 config dict. Patch every cmd_auto collaborator; capture config.
    bridge = _FakeBridge(plan=_plan([]))
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)

    class _Road:
        def build(self, report):
            class _R:
                quick_wins = []
            return _R()
    monkeypatch.setattr("app.engine.idea_roadmap.RoadmapSynthesizer",
                        lambda *a, **k: _Road())

    class _Shape:
        total_ideas = 0
        distinct_subjects = 0
        observations = []
        heaviest_module = ""
        heaviest_loc = 0
    monkeypatch.setattr("app.engine.idea_tree_shape.analyze_tree_shape",
                        lambda report: _Shape())
    monkeypatch.setattr("app.cli_autonomy._auto_security_counts",
                        lambda target: (0, 0))
    monkeypatch.setattr("app.cli_autonomy._working_tree_clean",
                        lambda target: False)

    class _Decision:
        act = False
        mode = "report"
        reason = "nothing to do"

        def to_dict(self):
            return {"act": False}

    class _Policy:
        def decide(self, **kw):
            return _Decision()
    monkeypatch.setattr("app.policies.autonomy_policy.AutonomyPolicy",
                        lambda *a, **k: _Policy())

    class _Plugins:
        def load_all(self):
            pass

        def idea_operators(self):
            return []
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: _Plugins())

    # plan_roadmap is called once as a scout in cmd_auto; give it a stats stub.
    class _Scout:
        stats = {"executable_steps": 0}
    bridge._plan = _Scout()

    _FakeEngine.last_config = None
    rc = m.cmd_auto(_ns(target=str(tmp_path), goal="", apply=False,
                        recommend=True, mode=None, commit=False, no_verify=True,
                        max_apply=0, json=True, out=""))
    assert rc == 0
    assert _FakeEngine.last_config == {
        "max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4}


def test_cmd_evolve_dry_run_forwards_exact_config(tmp_path, capsys, monkeypatch):
    # Line 427 config dict, in the --dry-run branch of cmd_evolve.
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)

    class _Bridge:
        def plan_roadmap(self, report, mode="report", project_root=""):
            return "PLAN"

        def dry_run_plan(self, plan, root):
            return {"applicable": 2, "total_executable": 5}
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: _Bridge())

    _FakeEngine.last_config = None
    args = _ns(target=str(tmp_path), objective="", history=False, dry_run=True,
               json=False, mode=None, commit=False, max_cycles=3, max_apply=5,
               no_verify=True, out="")
    rc = m.cmd_evolve(args)
    assert rc == 0
    assert _FakeEngine.last_config == {
        "max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4}
    out = capsys.readouterr().out
    assert "2 of 5 fixes would apply" in out


# =========================================================================== #
# JSON indent=2 is load-bearing on every emitter. A 2-space indent prints a    #
# top-level key as "\n  \"key\""; indent=3 would print "\n   \"key\"". The     #
# helper below pins the 2-space shape, killing the `indent: 2 -> 3` mutants.   #
# =========================================================================== #
def _assert_two_space_indent(text: str) -> None:
    # The emitted block must be byte-for-byte json.dumps(obj, indent=2); an
    # indent=3 mutant would shift every nesting level and break this equality.
    parsed = json.loads(text)
    assert text.rstrip("\n") == json.dumps(parsed, indent=2), \
        "JSON must be emitted with exactly 2-space indent"


def test_develop_top_no_runnable_json_indent(tmp_path, capsys, monkeypatch):
    # Line 671.
    bridge = _FakeBridge(plan=_plan([]))
    _patch_top(monkeypatch, bridge, covered=True)
    _develop_top(_top_ns(tmp_path, json=True), tmp_path)
    out = capsys.readouterr().out
    assert json.loads(out) == {"top": None, "applied": False,
                               "reason": "no-runnable-step"}
    _assert_two_space_indent(out)


def test_develop_top_dry_run_json_indent(tmp_path, capsys, monkeypatch):
    # Line 735 (_top_emit_dry_run json).
    proof = {"reparses": True, "added": 1, "removed": 0, "impact": "",
             "covered": True}
    bridge = _FakeBridge(plan=_plan([_step(patch_preview={"diff": "x", **proof})]))
    _patch_top(monkeypatch, bridge, covered=True)
    _develop_top(_top_ns(tmp_path, json=True), tmp_path)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["applied"] is False
    _assert_two_space_indent(out)


def test_develop_top_false_green_json_indent(tmp_path, capsys, monkeypatch):
    # Line 724 (_top_emit_false_green json) + rc 2.
    bridge = _FakeBridge(plan=_plan([_step()]))
    _patch_top(monkeypatch, bridge, covered=False)
    rc = _develop_top(_top_ns(tmp_path, apply=True, json=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 2
    assert json.loads(out)["reason"] == "false-green-guard"
    _assert_two_space_indent(out)


def test_develop_top_shield_json_indent(tmp_path, capsys, monkeypatch):
    # Line 704 (_top_emit_shield json).
    bridge = _FakeBridge(plan=_plan([_step()]))
    _patch_top(monkeypatch, bridge, covered=False)
    monkeypatch.setattr("app.cli_autonomy._write_shield_stub",
                        lambda root, step: ("tests/test_m_characterization.py", True))
    rc = _develop_top(_top_ns(tmp_path, shield=True, json=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["reason"] == "shield-stub-written"
    _assert_two_space_indent(out)


def test_develop_top_apply_json_indent(tmp_path, capsys, monkeypatch):
    # Line 790 (_top_emit_apply json).
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    rc = _develop_top(_top_ns(tmp_path, apply=True, json=True), tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["applied"] is True
    _assert_two_space_indent(out)


# =========================================================================== #
# _top_emit_apply — the one-step ActionPlan it builds and the verify flag it   #
# forwards are load-bearing (kills line 774 stats and line 776 verify flip).   #
# =========================================================================== #
class _CapturingBridge(_FakeBridge):
    def apply_plan(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        _CapturingBridge.last_plan = plan
        _CapturingBridge.last_verify = verify
        _CapturingBridge.last_max_apply = max_apply
        return self._apply_summary


def test_top_apply_builds_single_step_plan_stats(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _CapturingBridge(plan=_plan([_step(), _step(branch_path="b2")]),
                              apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    plan = _CapturingBridge.last_plan
    # stats are pinned to {total:1, executable:1} regardless of source plan size.
    assert plan.stats == {"total_steps": 1, "executable_steps": 1}
    assert len(plan.steps) == 1
    assert _CapturingBridge.last_max_apply == 1


def test_top_apply_verify_follows_no_verify_flag(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _CapturingBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    # no_verify=False -> verify=True (kills the False->True flip at line 776,
    # which would make verify a constant regardless of the flag).
    _develop_top(_top_ns(tmp_path, apply=True, no_verify=False), tmp_path)
    assert _CapturingBridge.last_verify is True
    _develop_top(_top_ns(tmp_path, apply=True, no_verify=True), tmp_path)
    assert _CapturingBridge.last_verify is False


def test_top_apply_markdown_footer_only_when_applied_not_rolled_back(
        tmp_path, capsys, monkeypatch):
    # Line 794: `if applied and not rolled_back` gates the working-tree note.
    summary = {"results": [{"applied": True, "rolled_back": True,
                            "verified": True}]}
    bridge = _FakeBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    _develop_top(_top_ns(tmp_path, apply=True), tmp_path)
    out = capsys.readouterr().out
    # rolled_back -> no "Applied to your working tree" footer (kills and->or).
    assert "Applied to your working tree" not in out


# =========================================================================== #
# _top_proof_lines — the `.get('added', 0)` / `.get('removed', 0)` defaults    #
# are load-bearing (kills the `0 -> 1` flips at line 630).                      #
# =========================================================================== #
def test_top_proof_lines_missing_counts_default_to_zero():
    step = _step()
    proof = {"reparses": True, "covered": True}  # no added/removed keys
    lines = _top_proof_lines(step, proof)
    body = "\n".join(lines)
    assert "+0 −0" in body  # defaults are 0, not 1
    assert "re-parses cleanly" in body


def test_top_proof_lines_uses_present_counts():
    proof = {"reparses": False, "added": 4, "removed": 2, "impact": "big",
             "covered": False}
    body = "\n".join(_top_proof_lines(_step(), proof))
    assert "+4 −2" in body
    assert "re-parse check failed" in body
    assert "big" in body
    assert "no test exercises this" in body


# =========================================================================== #
# _top_prove_step — `"diff" in step.patch_preview` selects the carried proof.  #
# Kills the membership flip `in -> not in` at line 804.                         #
# =========================================================================== #
def test_top_prove_step_uses_carried_proof_when_diff_present():
    from app.cli_autonomy import _top_prove_step
    carried = {"diff": "patch", "added": 9}
    step = _step(patch_preview=carried)

    class _Bridge:
        def prove_step(self, step, root):
            raise AssertionError("should not redraft when proof carries a diff")

    assert _top_prove_step(_Bridge(), step, "/x") == carried


def test_top_prove_step_falls_back_when_no_diff_key():
    from app.cli_autonomy import _top_prove_step
    step = _step(patch_preview={"added": 1})  # no "diff" -> fall back

    class _Bridge:
        def prove_step(self, step, root):
            return {"fresh": True}

    assert _top_prove_step(_Bridge(), step, "/x") == {"fresh": True}


# =========================================================================== #
# cmd_develop non-top boolean `and` guards (511 / 537 / 554 / 556). The        #
# existing footer tests all use apply=True; these use apply=False with steps    #
# present so an `and`->`or` flip would WRONGLY claim a change.                  #
# =========================================================================== #
def _dev_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), objective="dead-params", goal="",
                all_objectives=False, grade=False, history=False,
                from_dream=False, playbook=False, top=False, apply=False,
                max_steps=3, no_verify=True, fast=False, json=False)
    base.update(over)
    return _ns(**base)


def test_develop_all_no_apply_with_steps_omits_footer_and_no_gain(
        tmp_path, capsys, monkeypatch):
    class _R:
        steps = [1, 2]

        def to_dict(self):
            return {"steps": self.steps}

    monkeypatch.setattr("app.engine.objective_compiler.compile_all",
                        lambda *a, **k: [_R()])
    monkeypatch.setattr("app.engine.objective_compiler.render_all_markdown",
                        lambda results: "# All")
    captured = {}
    monkeypatch.setattr(
        "app.cli_autonomy._print_grade_proof",
        lambda target, before, applied, objective="", moves=0:
        captured.update(applied=applied))
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True))
    out = capsys.readouterr().out
    assert rc == 0
    # apply=False -> `changed` is False even though steps exist (kills and->or).
    assert "Applied to your working tree" not in out
    assert captured["applied"] is False


def test_develop_from_dream_no_apply_with_steps_omits_footer(
        tmp_path, capsys, monkeypatch):
    class _R:
        steps = [1]

        def to_dict(self):
            return {"steps": self.steps}

    monkeypatch.setattr("app.engine.objective_compiler.dream_confluence_modules",
                        lambda target: ["app/m.py"])
    monkeypatch.setattr("app.engine.objective_compiler.compile_from_dream",
                        lambda *a, **k: [_R()])
    monkeypatch.setattr("app.engine.objective_compiler.render_from_dream_markdown",
                        lambda results, modules: "# Dream")
    rc = cmd_develop(_dev_ns(tmp_path, from_dream=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Applied to your working tree" not in out


def test_develop_objective_applied_false_with_steps_no_footer(
        tmp_path, capsys, monkeypatch):
    # Line 554 `result.applied and result.steps` + line 556 same predicate to
    # _print_grade_proof: applied=False but steps present -> no footer/no gain.
    class _R:
        steps = [1, 2, 3]
        applied = False
        blocked: list = []

        def to_dict(self):
            return {"steps": self.steps, "applied": self.applied}

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        lambda *a, **k: _R())
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# Compiled")
    captured = {}
    monkeypatch.setattr(
        "app.cli_autonomy._print_grade_proof",
        lambda target, before, applied, objective="", moves=0:
        captured.update(applied=applied, moves=moves))
    rc = cmd_develop(_dev_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Applied to your working tree" not in out
    assert captured["applied"] is False
    assert captured["moves"] == 3


def test_develop_objective_scope_verify_follows_fast_flag(
        tmp_path, monkeypatch):
    # Line 548 `scope_verify=getattr(args, "fast", False)`: fast must flow
    # through (kills the False->True flip, which would force scope_verify on).
    seen = {}

    class _R:
        steps = []
        applied = False
        blocked: list = []

        def to_dict(self):
            return {}

    def _compile(target, objective="", max_steps=25, verify=True, apply=False,
                 scope_verify=False):
        seen["scope_verify"] = scope_verify
        return _R()
    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        _compile)
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# C")
    cmd_develop(_dev_ns(tmp_path, fast=False))
    assert seen["scope_verify"] is False
    cmd_develop(_dev_ns(tmp_path, fast=True))
    assert seen["scope_verify"] is True


# =========================================================================== #
# _develop_goal return code (line 503): empty objectives -> rc 1, not 2.        #
# =========================================================================== #
def test_develop_goal_empty_objectives_returns_one(tmp_path, capsys, monkeypatch):
    class _GR:
        objectives: list = []
        total_moves = 0

        def to_dict(self):
            return {"objectives": []}

    monkeypatch.setattr("app.engine.fractal_develop.compile_goal",
                        lambda *a, **k: _GR())
    monkeypatch.setattr("app.engine.fractal_develop.render_goal_markdown",
                        lambda gr: "# Goal")
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt", apply=False))
    assert rc == 1


def test_develop_goal_nonempty_objectives_returns_zero(tmp_path, capsys, monkeypatch):
    class _GR:
        objectives = ["x"]
        total_moves = 0

        def to_dict(self):
            return {"objectives": ["x"]}

    monkeypatch.setattr("app.engine.fractal_develop.compile_goal",
                        lambda *a, **k: _GR())
    monkeypatch.setattr("app.engine.fractal_develop.render_goal_markdown",
                        lambda gr: "# Goal")
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt", apply=False))
    assert rc == 0


# =========================================================================== #
# cmd_develop getattr(...) default flips reached via a SPARSE namespace (the    #
# attribute is omitted, forcing the default). Kills False->True at 576/577/    #
# 586/594/548 and the max_steps default 25 at line 575.                         #
# =========================================================================== #
def test_develop_sparse_namespace_uses_safe_defaults(tmp_path, monkeypatch):
    seen = {}

    class _R:
        steps = []
        applied = False
        blocked: list = []

        def to_dict(self):
            return {}

    def _compile(target, objective="", max_steps=25, verify=True, apply=False,
                 scope_verify=False):
        seen.update(max_steps=max_steps, verify=verify, apply=apply,
                    scope_verify=scope_verify)
        return _R()
    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        _compile)
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# C")
    # Only the attributes cmd_develop *requires* before the objective path; all
    # the getattr-guarded flags are omitted so their defaults are exercised.
    rc = cmd_develop(_ns(target=str(tmp_path), objective="dead-params",
                         json=False))
    assert rc == 0
    # max_steps default 25 (line 575), apply default False (577),
    # verify=not no_verify default -> True (576), scope_verify default False (548).
    assert seen == {"max_steps": 25, "verify": True, "apply": False,
                    "scope_verify": False}


def test_develop_sparse_namespace_from_dream_default_false(tmp_path, monkeypatch):
    # from_dream (594) and all_objectives default False -> falls through to the
    # objective path, not the dream/all paths.
    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        lambda *a, **k: type("R", (), {
                            "steps": [], "applied": False, "blocked": [],
                            "to_dict": lambda self: {}})())
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# OBJECTIVE-PATH")

    def _boom(*a, **k):
        raise AssertionError("dream path must not run by default")
    monkeypatch.setattr("app.engine.objective_compiler.compile_from_dream", _boom)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_develop(_ns(target=str(tmp_path), objective="dead-params",
                             json=False))
    assert rc == 0
    assert "# OBJECTIVE-PATH" in buf.getvalue()


# =========================================================================== #
# cmd_simulate — forwards max_cycles/max_apply/objective; JSON indent at 392.   #
# Kills 387 (max_cycles default 3), 388 (max_apply default 5 + `or 5`), 392.    #
# =========================================================================== #
def _patch_simulate(monkeypatch, seen):
    class _Res:
        def to_dict(self):
            return {"before": 1, "after": 2}

    def _sim(target, max_cycles=3, max_apply_per_cycle=5, objective=None):
        seen.update(max_cycles=max_cycles,
                    max_apply_per_cycle=max_apply_per_cycle, objective=objective)
        return _Res()
    monkeypatch.setattr("app.engine.simulation.simulate_evolution", _sim)
    monkeypatch.setattr("app.engine.simulation.render_simulation_markdown",
                        lambda result, root: "# SIM")


def test_cmd_simulate_default_forwards(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_simulate(monkeypatch, seen)
    rc = m.cmd_simulate(_ns(target=str(tmp_path), json=False))
    assert rc == 0
    assert seen == {"max_cycles": 3, "max_apply_per_cycle": 5, "objective": None}


def test_cmd_simulate_zero_max_apply_falls_back_to_five(tmp_path, monkeypatch):
    # Line 388 `getattr(args, "max_apply", 5) or 5`: an explicit 0 must become 5.
    seen = {}
    _patch_simulate(monkeypatch, seen)
    m.cmd_simulate(_ns(target=str(tmp_path), json=False, max_apply=0,
                       max_cycles=3, objective=""))
    assert seen["max_apply_per_cycle"] == 5


def test_cmd_simulate_json_indent(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_simulate(monkeypatch, seen)
    m.cmd_simulate(_ns(target=str(tmp_path), json=True, max_apply=5,
                       max_cycles=3, objective=""))
    out = capsys.readouterr().out
    assert json.loads(out) == {"before": 1, "after": 2}
    _assert_two_space_indent(out)


# =========================================================================== #
# cmd_evolve — history (414/417), mode default (437), loop args (441/442/443/   #
# 444/445), result json (450/451).                                             #
# =========================================================================== #
class _FakeLoop:
    last_kwargs: dict = {}

    def __init__(self, project_root="", mode="supervised", max_cycles=3,
                 max_apply_per_cycle=5, verify=True, commit=False,
                 objective=None):
        _FakeLoop.last_kwargs = dict(
            mode=mode, max_cycles=max_cycles,
            max_apply_per_cycle=max_apply_per_cycle, verify=verify,
            commit=commit, objective=objective)

    def run(self):
        class _Res:
            def to_dict(self):
                return {"ok": True}
        return _Res()


def _patch_evolve_run(monkeypatch):
    monkeypatch.setattr("app.engine.evolution.EvolutionLoop", _FakeLoop)
    monkeypatch.setattr("app.engine.evolution.record_run", lambda *a, **k: None)
    monkeypatch.setattr("app.engine.evolution.render_evolution_markdown",
                        lambda result, root: "# EVO")
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: _FakeBridge())


def _evolve_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), objective="", history=False,
                dry_run=False, json=False, mode=None, commit=False,
                max_cycles=3, max_apply=5, no_verify=True, out="")
    base.update(over)
    return _ns(**base)


def test_cmd_evolve_default_loop_args(tmp_path, capsys, monkeypatch):
    _patch_evolve_run(monkeypatch)
    rc = m.cmd_evolve(_evolve_ns(tmp_path, no_verify=False))
    assert rc == 0
    kw = _FakeLoop.last_kwargs
    # mode default 437: not commit -> "supervised".
    assert kw["mode"] == "supervised"
    assert kw["max_cycles"] == 3
    assert kw["max_apply_per_cycle"] == 5
    assert kw["verify"] is True  # not no_verify (kills 443 False->True)
    assert kw["commit"] is False


def test_cmd_evolve_commit_defaults_mode_autonomous(tmp_path, capsys, monkeypatch):
    # Line 437: mode default is "autonomous" when --commit, else "supervised".
    _patch_evolve_run(monkeypatch)
    m.cmd_evolve(_evolve_ns(tmp_path, commit=True))
    assert _FakeLoop.last_kwargs["mode"] == "autonomous"
    assert _FakeLoop.last_kwargs["commit"] is True


def test_cmd_evolve_zero_max_apply_falls_back(tmp_path, monkeypatch):
    # Line 442 `getattr(...) or 5`: explicit 0 -> 5.
    _patch_evolve_run(monkeypatch)
    m.cmd_evolve(_evolve_ns(tmp_path, max_apply=0))
    assert _FakeLoop.last_kwargs["max_apply_per_cycle"] == 5


def test_cmd_evolve_history_json_indent(tmp_path, capsys, monkeypatch):
    # Lines 414/417: --history prints the trajectory and runs nothing.
    monkeypatch.setattr("app.engine.evolution.load_history",
                        lambda root: {"runs": [1, 2]})

    def _boom(*a, **k):
        raise AssertionError("history path must not build a loop")
    monkeypatch.setattr("app.engine.evolution.EvolutionLoop", _boom)
    rc = m.cmd_evolve(_evolve_ns(tmp_path, history=True, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"runs": [1, 2]}
    _assert_two_space_indent(out)


def test_cmd_evolve_result_json_indent(tmp_path, capsys, monkeypatch):
    # Lines 450/451: the result is emitted as 2-space JSON.
    _patch_evolve_run(monkeypatch)
    m.cmd_evolve(_evolve_ns(tmp_path, json=True))
    out = capsys.readouterr().out
    assert json.loads(out) == {"ok": True}
    _assert_two_space_indent(out)


# =========================================================================== #
# cmd_ascend — forwards every arg (1074/1075/1076/1077/1078/1079/1080), the     #
# dry-run note (1085), and the result JSON (1082).                              #
# =========================================================================== #
def _patch_ascend(monkeypatch, seen):
    class _Rep:
        def to_dict(self):
            return {"rounds": 1}

    def _ascend(target, max_rounds=4, target_score=None, apply=True,
                verify=True, goal="", max_steps=25, scope_verify=False):
        seen.update(max_rounds=max_rounds, target_score=target_score,
                    apply=apply, verify=verify, goal=goal, max_steps=max_steps,
                    scope_verify=scope_verify)
        return _Rep()
    monkeypatch.setattr("app.engine.ascend.ascend", _ascend)
    monkeypatch.setattr("app.engine.ascend.render_ascend_markdown",
                        lambda report: "# ASCEND")


def _ascend_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), max_rounds=4, until="", apply=False,
                no_verify=True, goal="", max_steps=25, fast=False, json=False)
    base.update(over)
    return _ns(**base)


def test_cmd_ascend_default_forwarding_and_dry_run_note(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_ascend(monkeypatch, seen)
    rc = m.cmd_ascend(_ascend_ns(tmp_path, no_verify=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert seen["max_rounds"] == 4
    assert seen["max_steps"] == 25
    assert seen["apply"] is False          # 1076 False->True
    assert seen["verify"] is True          # 1077 not no_verify
    assert seen["scope_verify"] is False   # 1080 False->True
    assert seen["target_score"] is None    # 1075 `or ""` -> _target_score("")
    assert "[ascend] Dry run" in out       # 1085 `if not apply`


def test_cmd_ascend_apply_omits_dry_run_note(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_ascend(monkeypatch, seen)
    m.cmd_ascend(_ascend_ns(tmp_path, apply=True))
    out = capsys.readouterr().out
    assert seen["apply"] is True
    assert "[ascend] Dry run" not in out


def test_cmd_ascend_until_letter_parsed_to_floor(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_ascend(monkeypatch, seen)
    m.cmd_ascend(_ascend_ns(tmp_path, until="A-"))
    assert seen["target_score"] == 90


def test_cmd_ascend_json_indent(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_ascend(monkeypatch, seen)
    m.cmd_ascend(_ascend_ns(tmp_path, json=True))
    out = capsys.readouterr().out
    assert json.loads(out) == {"rounds": 1}
    _assert_two_space_indent(out)


# =========================================================================== #
# cmd_plan — goal `or ""` (1054) + result JSON indent (1061).                   #
# =========================================================================== #
def test_cmd_plan_json_indent_no_goal(tmp_path, capsys, monkeypatch):
    class _Rank:
        def to_dict(self):
            return {"objective": "x"}
    monkeypatch.setattr("app.engine.ascend.rank_objectives",
                        lambda root, restrict: [_Rank()])
    monkeypatch.setattr("app.engine.ascend.render_plan_markdown",
                        lambda rankings: "# PLAN")
    rc = m.cmd_plan(_ns(target=str(tmp_path), goal="", json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == [{"objective": "x"}]
    _assert_two_space_indent(out)


def test_cmd_plan_goal_resolves_restrict(tmp_path, capsys, monkeypatch):
    # Line 1054/1056: a non-empty goal triggers resolve_goal -> restrict.
    seen = {}
    monkeypatch.setattr("app.engine.fractal_develop.resolve_goal",
                        lambda goal: ["dead-params"])

    def _rank(root, restrict):
        seen["restrict"] = restrict
        return []
    monkeypatch.setattr("app.engine.ascend.rank_objectives", _rank)
    monkeypatch.setattr("app.engine.ascend.render_plan_markdown",
                        lambda rankings: "# PLAN")
    m.cmd_plan(_ns(target=str(tmp_path), goal="reduce-debt", json=False))
    assert seen["restrict"] == ["dead-params"]


def test_cmd_plan_no_goal_restrict_is_none(tmp_path, capsys, monkeypatch):
    seen = {}

    def _rank(root, restrict):
        seen["restrict"] = restrict
        return []
    monkeypatch.setattr("app.engine.ascend.rank_objectives", _rank)
    monkeypatch.setattr("app.engine.ascend.render_plan_markdown",
                        lambda rankings: "# PLAN")
    m.cmd_plan(_ns(target=str(tmp_path), goal="", json=False))
    assert seen["restrict"] is None


# =========================================================================== #
# _working_tree_clean — subprocess kwargs (text=True at 372, timeout=10 at      #
# 366/372) and the `or` guard at 368 are load-bearing.                          #
# =========================================================================== #
class _Proc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_working_tree_clean_passes_text_and_timeout(monkeypatch):
    calls = []

    def _run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        calls.append(dict(cmd=cmd, text=text, timeout=timeout))
        if cmd[1] == "rev-parse":
            return _Proc(0, "true\n")
        return _Proc(0, "")  # clean status
    monkeypatch.setattr("subprocess.run", _run)
    from app.cli_autonomy import _working_tree_clean
    from pathlib import Path
    assert _working_tree_clean(Path("/x")) is True
    # text=True is required (kills 372 True->False) and timeout is 10 (366/372).
    for c in calls:
        assert c["text"] is True
        assert c["timeout"] == 10


def test_working_tree_clean_not_inside_repo_is_dirty(monkeypatch):
    # Line 368 `returncode != 0 or stdout != "true"`: a non-"true" stdout (even
    # with rc 0) must count as not-a-repo (kills the `or`->`and` flip, which
    # would require BOTH to be wrong before bailing).
    def _run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        return _Proc(0, "false\n")
    monkeypatch.setattr("subprocess.run", _run)
    from app.cli_autonomy import _working_tree_clean
    from pathlib import Path
    assert _working_tree_clean(Path("/x")) is False


def test_working_tree_clean_dirty_status_is_not_clean(monkeypatch):
    def _run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        if cmd[1] == "rev-parse":
            return _Proc(0, "true\n")
        return _Proc(0, " M file.py\n")
    monkeypatch.setattr("subprocess.run", _run)
    from app.cli_autonomy import _working_tree_clean
    from pathlib import Path
    assert _working_tree_clean(Path("/x")) is False


# =========================================================================== #
# _verify_one_test — subprocess kwargs: timeout=120 (924) is forwarded.         #
# =========================================================================== #
def test_verify_one_test_forwards_default_timeout(monkeypatch):
    seen = {}

    def _run(cmd, cwd=None, capture_output=False, timeout=None):
        seen["timeout"] = timeout
        seen["capture_output"] = capture_output
        seen["cmd"] = cmd
        return _Proc(0)
    monkeypatch.setattr("subprocess.run", _run)
    from app.cli_autonomy import _verify_one_test
    assert _verify_one_test("/x", "tests/test_a.py") is True
    assert seen["timeout"] == 120
    # capture_output=True keeps the generated-test output off the console
    # (kills the True->False flip at line 929).
    assert seen["capture_output"] is True
    assert "tests/test_a.py" in seen["cmd"]


def test_verify_one_test_failure_returncode(monkeypatch):
    def _run(cmd, cwd=None, capture_output=False, timeout=None):
        return _Proc(1)
    monkeypatch.setattr("subprocess.run", _run)
    from app.cli_autonomy import _verify_one_test
    assert _verify_one_test("/x", "tests/test_a.py") is False


# =========================================================================== #
# cmd_shield / _shield_all                                                      #
# =========================================================================== #
class _ShieldObj:
    def __init__(self, module="app/m.py"):
        self.module = module
        self.test_path = "tests/test_m_characterization.py"
        self.functions = ["pub"]
        self.content = "def test_x():\n    pass\n"


def test_cmd_shield_json_indent_and_apply_flag(tmp_path, capsys, monkeypatch):
    # Line 1013 (json indent) + 1014 getattr apply default. apply omitted ->
    # write_shield_test must NOT be called (kills False->True at 1014).
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: _ShieldObj())

    def _boom(root, shield):
        raise AssertionError("must not write without --apply")
    monkeypatch.setattr("app.execution.test_shield.write_shield_test", _boom)
    rc = m.cmd_shield(_ns(target=str(tmp_path), module="app/m.py",
                          all_modules=False, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["module"] == "app/m.py"
    _assert_two_space_indent(out)


def test_cmd_shield_markdown_apply_default_false_is_preview(tmp_path, capsys, monkeypatch):
    # Line 1023 getattr apply default: omitted -> preview footer, no write.
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: _ShieldObj())

    def _boom(root, shield):
        raise AssertionError("must not write without --apply")
    monkeypatch.setattr("app.execution.test_shield.write_shield_test", _boom)
    rc = m.cmd_shield(_ns(target=str(tmp_path), module="app/m.py",
                          all_modules=False, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Preview only" in out


def test_cmd_shield_no_functions_renders_smoke_label(tmp_path, capsys, monkeypatch):
    # Line 1019 `', '.join(functions) or '(import smoke only)'`: empty list ->
    # the smoke label (kills the `or`->`and` flip).
    sh = _ShieldObj()
    sh.functions = []
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: sh)
    rc = m.cmd_shield(_ns(target=str(tmp_path), module="app/m.py",
                          all_modules=False, json=False, apply=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "(import smoke only)" in out


def test_shield_all_json_indent_and_apply_passthrough(tmp_path, capsys, monkeypatch):
    # Line 1001 getattr apply default forwarded into _shield_all; 968 json indent.
    monkeypatch.setattr("app.cli_autonomy._untested_own_modules",
                        lambda target: ["app/a.py"])
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: _ShieldObj())
    rc = m.cmd_shield(_ns(target=str(tmp_path), module="", all_modules=True,
                          json=True, apply=False))
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["candidates"] == ["app/a.py"]
    assert payload["applied"] is False  # apply omitted -> False (kills 1001)
    _assert_two_space_indent(out)


def test_shield_all_preview_lists_candidates(tmp_path, capsys, monkeypatch):
    from app.cli_autonomy import _shield_all
    monkeypatch.setattr("app.cli_autonomy._untested_own_modules",
                        lambda target: ["app/a.py", "app/b.py"])
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: _ShieldObj(module=mod))
    rc = _shield_all(str(tmp_path), apply=False, as_json=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "would build 2 test(s)" in out
    assert "- app/a.py" in out and "- app/b.py" in out


# =========================================================================== #
# _auto_resolve_mode — `not explicit_mode and goal` (146) + `return explicit_   #
# mode` (153).                                                                  #
# =========================================================================== #
def test_auto_resolve_mode_explicit_wins(monkeypatch):
    from app.cli_autonomy import _auto_resolve_mode

    def _boom(*a, **k):
        raise AssertionError("explicit mode must short-circuit the parser")
    monkeypatch.setattr("app.intent.parser.IntentParser", _boom)
    args = _ns(mode="autonomous")
    assert _auto_resolve_mode(args, "do stuff") == "autonomous"


def test_auto_resolve_mode_infers_from_goal(monkeypatch):
    from app.cli_autonomy import _auto_resolve_mode

    class _Parsed:
        mode = "supervised"

    class _Parser:
        def parse(self, goal):
            return _Parsed()
    monkeypatch.setattr("app.intent.parser.IntentParser", lambda: _Parser())
    # no explicit mode + a goal -> inferred (line 153 returns explicit_mode,
    # which is now the inferred value, not None).
    assert _auto_resolve_mode(_ns(mode=None), "tidy up") == "supervised"


def test_auto_resolve_mode_no_goal_returns_none():
    from app.cli_autonomy import _auto_resolve_mode
    # `not explicit_mode and goal`: goal is empty -> parser never runs, None.
    assert _auto_resolve_mode(_ns(mode=None), "") is None


def test_auto_resolve_mode_parser_failure_is_none(monkeypatch):
    from app.cli_autonomy import _auto_resolve_mode

    class _Parser:
        def parse(self, goal):
            raise RuntimeError("boom")
    monkeypatch.setattr("app.intent.parser.IntentParser", lambda: _Parser())
    assert _auto_resolve_mode(_ns(mode=None), "tidy") is None


# =========================================================================== #
# _auto_security_counts — the project/fixture split (line 170 `sec_n += 1`).    #
# =========================================================================== #
def test_auto_security_counts_splits_project_and_fixture(monkeypatch):
    from app.cli_autonomy import _auto_security_counts
    findings = [{"file": "app/real.py"}, {"file": "tests/fixtures/x.py"},
                {"file": "app/other.py"}]

    class _Agent:
        def run(self, project_root=""):
            return {"findings": findings}
    monkeypatch.setattr("app.agents.skills.SecurityAgent", lambda: _Agent())
    monkeypatch.setattr("app.engine.health_score._is_fixture_path",
                        lambda p: "fixtures" in p)
    sec_n, fixture_n = _auto_security_counts("/x")
    # `sec_n += 1` (kills +=>-=): two project findings -> 2, one fixture -> 1.
    assert sec_n == 2
    assert fixture_n == 1


def test_auto_security_counts_scanner_failure_is_zero(monkeypatch):
    from app.cli_autonomy import _auto_security_counts

    class _Agent:
        def run(self, project_root=""):
            raise RuntimeError("scanner down")
    monkeypatch.setattr("app.agents.skills.SecurityAgent", lambda: _Agent())
    assert _auto_security_counts("/x") == (0, 0)


# =========================================================================== #
# _auto_memory_line — the `100` percentage scale (line 216).                    #
# =========================================================================== #
def test_auto_memory_line_renders_percentage(monkeypatch):
    from app.cli_autonomy import _auto_memory_line

    class _Mem:
        @staticmethod
        def load(root):
            class _L:
                def summary(self):
                    return {"most_reliable": [
                        {"key": "trim", "success_rate": 1.0, "samples": 4}]}
            return _L()
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory", _Mem)
    lines = _auto_memory_line("/x")
    # 1.0 * 100 -> 100% exactly; the 100->101 flip would print "101%"
    # (int(1.0 * 101) == 101 distinguishes it, unlike a fractional rate).
    assert any("100% of the time" in ln for ln in lines)
    assert not any("101%" in ln for ln in lines)
    assert any("(4 samples)" in ln for ln in lines)


def test_auto_memory_line_empty_on_failure(monkeypatch):
    from app.cli_autonomy import _auto_memory_line

    class _Mem:
        @staticmethod
        def load(root):
            raise RuntimeError("no ledger")
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory", _Mem)
    assert _auto_memory_line("/x") == []


# =========================================================================== #
# _auto_recommend — JSON emit (line 234) + applied:False / decision payload.    #
# =========================================================================== #
class _Decision:
    def __init__(self, act=False, mode="report", reason="r"):
        self.act = act
        self.mode = mode
        self.reason = reason

    def to_dict(self):
        return {"act": self.act, "reason": self.reason}


class _Shape:
    total_ideas = 3
    distinct_subjects = 2
    observations = ["o1"]
    heaviest_module = "app/h.py"
    heaviest_loc = 99


class _Roadmap:
    quick_wins = []


def test_auto_recommend_json_indent(tmp_path, capsys):
    from app.cli_autonomy import _auto_recommend
    rc = _auto_recommend(_ns(), tmp_path, "goal", _Shape(), _Roadmap(),
                         sec_n=1, executable=4, decision=_Decision(),
                         emit_json=True)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["applicable"] == 4
    _assert_two_space_indent(out)


# =========================================================================== #
# _auto_act — line 256 `getattr(args, "max_apply", 0) or 8` and verify/draft.   #
# =========================================================================== #
class _ActBridge:
    last: dict = {}

    def plan_roadmap(self, report, mode="report", project_root="", draft=False):
        _ActBridge.last["draft"] = draft
        return _plan([])

    def apply_plan(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        _ActBridge.last.update(max_apply=max_apply, verify=verify, mode=mode,
                               commit=commit)
        return {"results": []}


def _patch_auto_act(monkeypatch):
    monkeypatch.setattr("app.engine.idea_action_bridge.render_maintenance_markdown",
                        lambda summary, root, objective="": "# MD")
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory",
                        type("M", (), {"learn_from": staticmethod(
                            lambda summary, root: None)}))
    monkeypatch.setattr("app.engine.signal_trends.SignalTrends",
                        lambda root: type("S", (), {
                            "record": lambda self, p: None})())


def test_auto_act_zero_max_apply_falls_back_to_eight(tmp_path, capsys, monkeypatch):
    _patch_auto_act(monkeypatch)
    bridge = _ActBridge()
    engine = _FakeEngine()
    _ActBridge.last = {}
    rc = m._auto_act(_ns(no_verify=False, max_apply=0, out=""), tmp_path, "goal",
                     bridge, engine, {"report": True}, mode="supervised",
                     commit=False, decision=_Decision(act=True), emit_json=False)
    assert rc == 0
    # max_apply 0 -> 8 (kills both the 0->1 and 8->9 flips at line 256).
    assert _ActBridge.last["max_apply"] == 8
    assert _ActBridge.last["verify"] is True   # not no_verify (255 False->True)
    assert _ActBridge.last["draft"] is True     # 252 plan_roadmap draft=True


def test_auto_act_json_indent(tmp_path, capsys, monkeypatch):
    _patch_auto_act(monkeypatch)
    bridge = _ActBridge()
    rc = m._auto_act(_ns(no_verify=True, max_apply=2, out=""), tmp_path, "goal",
                     bridge, _FakeEngine(), {}, mode="supervised", commit=False,
                     decision=_Decision(act=True), emit_json=True)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["decision"]["act"] is True
    _assert_two_space_indent(out)


# =========================================================================== #
# cmd_auto orchestration — the flags it reads (305 apply / 306 recommend /      #
# 326 commit), the scout's executable count (330), the goal `or None` (316),    #
# emit_json (321), and the `act and mode == "report"` upgrade (344).            #
# =========================================================================== #
def _patch_cmd_auto(monkeypatch, decision, decide_seen, executable=0):
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)

    class _Scout:
        stats = {"executable_steps": executable}

    class _Bridge:
        def plan_roadmap(self, report, mode="report", project_root="",
                         draft=False, proof=False):
            return _Scout()

        def apply_plan(self, *a, **k):
            return {"results": []}
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: _Bridge())
    monkeypatch.setattr("app.engine.idea_roadmap.RoadmapSynthesizer",
                        lambda *a, **k: type("R", (), {
                            "build": lambda self, report: _Roadmap()})())
    monkeypatch.setattr("app.engine.idea_tree_shape.analyze_tree_shape",
                        lambda report: _Shape())
    monkeypatch.setattr("app.cli_autonomy._auto_security_counts",
                        lambda target: (0, 0))
    monkeypatch.setattr("app.cli_autonomy._working_tree_clean",
                        lambda target: True)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: type("P", (), {
                            "load_all": lambda self: None,
                            "idea_operators": lambda self: []})())

    class _Policy:
        def decide(self, **kw):
            decide_seen.update(kw)
            return decision
    monkeypatch.setattr("app.policies.autonomy_policy.AutonomyPolicy",
                        lambda *a, **k: _Policy())
    monkeypatch.setattr("app.cli_autonomy._auto_recommend",
                        lambda *a, **k: 0)
    monkeypatch.setattr("app.cli_autonomy._auto_act",
                        lambda *a, **k: 0)


def _auto_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), goal="", apply=False, recommend=False,
                mode=None, commit=False, no_verify=True, max_apply=0,
                json=False, out="")
    base.update(over)
    return _ns(**base)


def test_cmd_auto_forwards_flags_to_policy(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=7)
    rc = m.cmd_auto(_auto_ns(tmp_path, apply=True, recommend=False,
                             commit=True))
    assert rc == 0
    # explicit_apply (305), explicit_recommend (306), commit (326), and the
    # scout's executable_steps (330) all flow into the policy unchanged.
    assert seen["explicit_apply"] is True
    assert seen["explicit_recommend"] is False
    assert seen["commit"] is True
    assert seen["executable_steps"] == 7
    assert seen["working_tree_clean"] is True


def test_cmd_auto_default_flags_are_false(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=0)
    m.cmd_auto(_auto_ns(tmp_path))
    # all flags default False (kills the False->True flips at 305/306/326) and
    # executable defaults 0 when the scout stat is absent (kills 330 0->1).
    assert seen["explicit_apply"] is False
    assert seen["explicit_recommend"] is False
    assert seen["commit"] is False
    assert seen["executable_steps"] == 0


def test_cmd_auto_act_report_mode_upgraded_to_supervised(tmp_path, capsys, monkeypatch):
    # Line 344: when the decision is to act but mode resolves to "report", it is
    # upgraded to "supervised" (a patch-capable mode). Capture the mode passed
    # to _auto_act.
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=True, mode="report"), seen)
    captured = {}
    monkeypatch.setattr(
        "app.cli_autonomy._auto_act",
        lambda args, target, goal, bridge, engine, report, mode, commit,
        decision, emit_json: captured.update(mode=mode) or 0)
    rc = m.cmd_auto(_auto_ns(tmp_path, apply=True))
    assert rc == 0
    assert captured["mode"] == "supervised"


# =========================================================================== #
# mkdir(parents=True, exist_ok=True) — BOTH flags are load-bearing and each is  #
# a distinct mutant per line (cols differ):                                     #
#   * exist_ok=True->False: writing into an ALREADY-EXISTING parent dir raises  #
#     FileExistsError. Killed by the *_into_existing_dir tests below.           #
#   * parents=True->False: writing into a path whose INTERMEDIATE dirs are      #
#     ABSENT raises FileNotFoundError. Killed by the *_nested_missing_dirs      #
#     tests below.                                                              #
# Together these kill all four True->False pairs at lines 84, 283, 456, 662.    #
# =========================================================================== #
def test_maintain_write_out_into_existing_dir(tmp_path):
    from app.cli_autonomy import _maintain_write_out
    sub = tmp_path / "reports"
    sub.mkdir()  # parent already exists -> exist_ok=True must tolerate it
    out = sub / "r.md"
    _maintain_write_out(_ns(out=str(out)), "# body")
    assert out.read_text() == "# body"


def test_maintain_write_out_creates_nested_missing_dirs(tmp_path):
    from app.cli_autonomy import _maintain_write_out
    # Intermediate dirs a/ and a/b/ do NOT exist -> parents=True is required.
    out = tmp_path / "a" / "b" / "r.md"
    _maintain_write_out(_ns(out=str(out)), "# body")
    assert out.read_text() == "# body"


def test_maintain_write_out_noop_without_out():
    from app.cli_autonomy import _maintain_write_out
    _maintain_write_out(_ns(out=""), "# body")  # must not raise


def test_auto_act_out_writes_into_existing_dir(tmp_path, capsys, monkeypatch):
    _patch_auto_act(monkeypatch)
    sub = tmp_path / "out"
    sub.mkdir()
    out = sub / "auto.md"
    rc = m._auto_act(_ns(no_verify=True, max_apply=1, out=str(out)), tmp_path,
                     "g", _ActBridge(), _FakeEngine(), {}, mode="supervised",
                     commit=False, decision=_Decision(act=True), emit_json=False)
    assert rc == 0
    assert out.exists()


def test_auto_act_out_creates_nested_missing_dirs(tmp_path, capsys, monkeypatch):
    _patch_auto_act(monkeypatch)
    out = tmp_path / "x" / "y" / "auto.md"  # intermediates absent -> parents=True
    rc = m._auto_act(_ns(no_verify=True, max_apply=1, out=str(out)), tmp_path,
                     "g", _ActBridge(), _FakeEngine(), {}, mode="supervised",
                     commit=False, decision=_Decision(act=True), emit_json=False)
    assert rc == 0
    assert out.exists()


def test_evolve_out_writes_into_existing_dir(tmp_path, capsys, monkeypatch):
    _patch_evolve_run(monkeypatch)
    sub = tmp_path / "evoout"
    sub.mkdir()
    out = sub / "e.md"
    rc = m.cmd_evolve(_evolve_ns(tmp_path, out=str(out)))
    assert rc == 0
    assert out.read_text() == "# EVO"


def test_evolve_out_creates_nested_missing_dirs(tmp_path, capsys, monkeypatch):
    _patch_evolve_run(monkeypatch)
    out = tmp_path / "p" / "q" / "e.md"  # intermediates absent -> parents=True
    rc = m.cmd_evolve(_evolve_ns(tmp_path, out=str(out)))
    assert rc == 0
    assert out.read_text() == "# EVO"


def test_write_shield_stub_into_existing_tests_dir(tmp_path, monkeypatch):
    from app.cli_autonomy import _write_shield_stub
    (tmp_path / "tests").mkdir()  # parent dir already there
    monkeypatch.setattr("app.engine.idea_action_bridge._test_stub_body",
                        lambda step, target: "def test_stub():\n    pass\n")
    rel, written = _write_shield_stub(str(tmp_path), _step(target="app/m.py"))
    assert written is True
    assert rel == "tests/test_m_characterization.py"
    assert (tmp_path / rel).exists()


def test_write_shield_stub_creates_tests_dir_when_absent(tmp_path, monkeypatch):
    from app.cli_autonomy import _write_shield_stub
    # No tests/ dir at all -> exist_ok=True path is still exercised when it is
    # created. (The stub's parent is always `<root>/tests`, exactly one level
    # under the always-existing root, so the `parents` flag at line 662 is
    # behaviour-preserving here — see test_equivalent_mutants_are_documented.)
    monkeypatch.setattr("app.engine.idea_action_bridge._test_stub_body",
                        lambda step, target: "def test_stub():\n    pass\n")
    rel, written = _write_shield_stub(
        str(tmp_path), _step(target="deep/nested/pkg/m.py"))
    assert written is True
    assert (tmp_path / rel).exists()


def test_write_shield_stub_never_clobbers(tmp_path, monkeypatch):
    from app.cli_autonomy import _write_shield_stub
    dest = tmp_path / "tests" / "test_m_characterization.py"
    dest.parent.mkdir(parents=True)
    dest.write_text("ORIGINAL")
    monkeypatch.setattr("app.engine.idea_action_bridge._test_stub_body",
                        lambda step, target: "REPLACED")
    rel, written = _write_shield_stub(str(tmp_path), _step(target="app/m.py"))
    assert written is False
    assert dest.read_text() == "ORIGINAL"


# =========================================================================== #
# _maintain_build_plan — `engine.run(objective=args.objective or None)` (34).   #
# =========================================================================== #
def _patch_maintain_build(monkeypatch, seen):
    class _Engine:
        last_profile = None

        def __init__(self, *a, **k):
            pass

        def run(self, objective=None):
            seen["run_objective"] = objective
            return {"r": True}

    class _Bridge:
        def plan_tree(self, report, mode="report", top=None, project_root=""):
            seen["mode"] = mode
            seen["top"] = top
            return "PLAN"
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _Engine)
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: _Bridge())
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: type("P", (), {
                            "load_all": lambda self: None,
                            "idea_operators": lambda self: []})())


def test_maintain_build_plan_empty_objective_runs_none(tmp_path, monkeypatch):
    from app.cli_autonomy import _maintain_build_plan
    seen = {}
    _patch_maintain_build(monkeypatch, seen)
    args = _ns(max_ideas=40, depth=2, breadth=4, objective="", mode="report",
               top=0)
    _maintain_build_plan(args, tmp_path)
    # `"" or None` -> None (kills the `or`->`and` flip, which yields "").
    assert seen["run_objective"] is None
    # `args.top or None` -> None when top is 0.
    assert seen["top"] is None


def test_maintain_build_plan_passes_objective_through(tmp_path, monkeypatch):
    from app.cli_autonomy import _maintain_build_plan
    seen = {}
    _patch_maintain_build(monkeypatch, seen)
    args = _ns(max_ideas=40, depth=2, breadth=4, objective="security",
               mode="supervised", top=3)
    _maintain_build_plan(args, tmp_path)
    assert seen["run_objective"] == "security"
    assert seen["top"] == 3


# =========================================================================== #
# _maintain_write_proof — `objective=args.objective or ""` (95) + the           #
# no-results early return.                                                      #
# =========================================================================== #
def test_maintain_write_proof_passes_objective_through(tmp_path, capsys, monkeypatch):
    from app.cli_autonomy import _maintain_write_proof
    seen = {}
    monkeypatch.setattr("app.engine.proof_of_fix.build_proof",
                        lambda summary, root, objective="":
                        seen.update(objective=objective) or {"p": 1})
    monkeypatch.setattr("app.engine.proof_of_fix.write_proof",
                        lambda proof, root, out=None: ".apex/proof.json")
    # A non-empty objective: `"sec" or ""` -> "sec" but `"sec" and ""` -> ""
    # (this is what kills the `or`->`and` flip at line 95).
    _maintain_write_proof(_ns(objective="sec", json=True, proof=""),
                          {"results": [1]}, tmp_path)
    assert seen["objective"] == "sec"


def test_maintain_write_proof_skips_when_no_results(tmp_path):
    from app.cli_autonomy import _maintain_write_proof
    # no results -> early return, never imports proof_of_fix.
    _maintain_write_proof(_ns(objective="x", json=True, proof=""), {}, tmp_path)


# =========================================================================== #
# cmd_maintain — dry_run getattr default (133) reached via sparse namespace.    #
# =========================================================================== #
def test_cmd_maintain_sparse_namespace_not_dry_run(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("app.cli_autonomy._maintain_build_plan",
                        lambda args, target: ("E", "B", "PLAN"))
    monkeypatch.setattr("app.cli_autonomy._maintain_scope_recipe",
                        lambda args, plan: True)
    monkeypatch.setattr("app.cli_autonomy._maintain_dry_run",
                        lambda args, bridge, plan, target:
                        seen.update(dry=True))
    monkeypatch.setattr("app.cli_autonomy._maintain_apply",
                        lambda args, e, b, plan, target:
                        seen.update(applied=True) or 0)
    # dry_run attribute omitted -> getattr default False -> apply path runs.
    rc = m.cmd_maintain(_ns(target=str(tmp_path)))
    assert rc == 0
    assert seen.get("dry") is None
    assert seen.get("applied") is True


# =========================================================================== #
# _develop_top — plan_roadmap proof=True (852) and engine objective (850).      #
# =========================================================================== #
def test_develop_top_requests_proof_and_forwards_objective(tmp_path, monkeypatch):
    bridge = _FakeBridge(plan=_plan([]))
    _patch_top(monkeypatch, bridge, covered=True)
    _FakeEngine.last_objective = "sentinel"
    _develop_top(_top_ns(tmp_path, objective="reduce"), tmp_path)
    # proof=True is requested on the roadmap (kills 852 True->False).
    assert _FakeBridge.last_roadmap_kwargs["proof"] is True
    # objective forwarded; `"reduce" or None` -> "reduce" (kills 850 or->and).
    assert _FakeEngine.last_objective == "reduce"


def test_develop_top_empty_objective_runs_none(tmp_path, monkeypatch):
    bridge = _FakeBridge(plan=_plan([]))
    _patch_top(monkeypatch, bridge, covered=True)
    _FakeEngine.last_objective = "sentinel"
    _develop_top(_top_ns(tmp_path, objective=""), tmp_path)
    assert _FakeEngine.last_objective is None


# =========================================================================== #
# _develop_playbook / _develop_history / _develop_goal JSON indent (474/486/    #
# 498).                                                                         #
# =========================================================================== #
def test_develop_playbook_json_indent(tmp_path, capsys, monkeypatch):
    class _Arch:
        def to_dict(self):
            return {"recipes": {"a": 1}}

    class _CA:
        @staticmethod
        def load(root):
            return _Arch()
    monkeypatch.setattr("app.engine.composition_archive.CompositionArchive", _CA)
    monkeypatch.setattr("app.engine.composition_archive.render_playbook_markdown",
                        lambda archive: "# PB")
    rc = cmd_develop(_dev_ns(tmp_path, playbook=True, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"recipes": {"a": 1}}
    _assert_two_space_indent(out)


def test_develop_history_json_indent(tmp_path, capsys, monkeypatch):
    class _Hist:
        def to_dict(self):
            return {"runs": [{"x": 1}]}

    class _DH:
        @staticmethod
        def load(root):
            return _Hist()
    monkeypatch.setattr("app.engine.dev_history.DevHistory", _DH)
    monkeypatch.setattr("app.engine.dev_history.render_history_markdown",
                        lambda history: "# HI")
    rc = cmd_develop(_dev_ns(tmp_path, history=True, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"runs": [{"x": 1}]}
    _assert_two_space_indent(out)


def test_develop_goal_json_indent(tmp_path, capsys, monkeypatch):
    class _GR:
        objectives = ["x"]
        total_moves = 0

        def to_dict(self):
            return {"objectives": ["x"]}
    monkeypatch.setattr("app.engine.fractal_develop.compile_goal",
                        lambda *a, **k: _GR())
    monkeypatch.setattr("app.engine.fractal_develop.render_goal_markdown",
                        lambda gr: "# G")
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt", json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"objectives": ["x"]}
    _assert_two_space_indent(out)


def test_develop_all_json_indent(tmp_path, capsys, monkeypatch):
    class _R:
        steps = []

        def to_dict(self):
            return {"steps": []}
    monkeypatch.setattr("app.engine.objective_compiler.compile_all",
                        lambda *a, **k: [_R()])
    monkeypatch.setattr("app.engine.objective_compiler.render_all_markdown",
                        lambda results: "# A")
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == [{"steps": []}]
    _assert_two_space_indent(out)


def test_develop_from_dream_json_indent(tmp_path, capsys, monkeypatch):
    class _R:
        steps = []

        def to_dict(self):
            return {"steps": []}
    monkeypatch.setattr("app.engine.objective_compiler.dream_confluence_modules",
                        lambda target: ["app/m.py"])
    monkeypatch.setattr("app.engine.objective_compiler.compile_from_dream",
                        lambda *a, **k: [_R()])
    monkeypatch.setattr("app.engine.objective_compiler.render_from_dream_markdown",
                        lambda results, modules: "# D")
    rc = cmd_develop(_dev_ns(tmp_path, from_dream=True, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"modules": ["app/m.py"], "campaigns": [{"steps": []}]}
    _assert_two_space_indent(out)


def test_develop_objective_json_indent(tmp_path, capsys, monkeypatch):
    class _R:
        steps = []
        applied = False
        blocked: list = []

        def to_dict(self):
            return {"applied": False}
    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        lambda *a, **k: _R())
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# C")
    rc = cmd_develop(_dev_ns(tmp_path, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"applied": False}
    _assert_two_space_indent(out)


# =========================================================================== #
# cmd_auto forwards `goal or None` to the engine (line 316).                    #
# =========================================================================== #
def test_cmd_auto_empty_goal_runs_engine_with_none(tmp_path, monkeypatch):
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=0)
    _FakeEngine.last_objective = "sentinel"
    m.cmd_auto(_auto_ns(tmp_path, goal=""))
    assert _FakeEngine.last_objective is None


def test_cmd_auto_goal_runs_engine_with_goal(tmp_path, monkeypatch):
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=0)
    _FakeEngine.last_objective = None
    m.cmd_auto(_auto_ns(tmp_path, goal="harden security"))
    assert _FakeEngine.last_objective == "harden security"


# =========================================================================== #
# _top_payload — the base payload shape (covered flag + applied:False).         #
# =========================================================================== #
def test_top_payload_shape():
    step = _step()
    payload = _top_payload(step, covered=True, proof={"diff": "x"})
    assert payload["covered"] is True
    assert payload["applied"] is False
    assert payload["verified"] is None
    assert payload["top"]["target"] == "app/m.py"
    assert payload["proof"] == {"diff": "x"}


# =========================================================================== #
# _shield_stub_path — deterministic naming (the `::`/`/` split mutants at       #
# lines 641/642 are EQUIVALENT because [0]/[-1] are invariant to maxsplit; see  #
# test_equivalent_mutants_are_documented — but the slug logic itself is pinned).#
# =========================================================================== #
def test_shield_stub_path_from_target_and_subject():
    assert _shield_stub_path(_step(target="app/sub/foo.py")) == \
        "tests/test_foo_characterization.py"
    # target empty -> falls back to subject's pre-`::` part.
    assert _shield_stub_path(_step(target="", subject="app/bar.py::func")) == \
        "tests/test_bar_characterization.py"
    # multi-`::` target still keeps the file part (maxsplit invariance).
    assert _shield_stub_path(_step(target="app/baz.py::x::y")) == \
        "tests/test_baz_characterization.py"


# =========================================================================== #
# EQUIVALENT MUTANTS (behaviour-preserving — unkillable by any test).          #
#                                                                              #
# These survive every possible test because they do not change the program's   #
# observable behaviour. They are named here so the survivor count is honest:    #
# the true suite strength is the kill rate over the NON-equivalent universe.    #
# =========================================================================== #
_EQUIVALENT_MUTANTS = {
    # _shield_stub_path (lines 641, 642): the `maxsplit` argument of
    #   `str.split("::", 1)` / `str.rsplit("/", 1)` is incremented (1 -> 2), but
    #   only element [0] (for split) or [-1] (for rsplit) is taken. Taking the
    #   first/last piece is invariant to how many *additional* splits are
    #   permitted, so `maxsplit=1` and `maxsplit=2` yield identical results for
    #   every input. Behaviour-preserving -> no test can distinguish them.
    (641, "number:1>2", "(step.target or step.subject.split(\"::\", 1)[0])"
                        ".split(\"::\", 1)[0]  (outer split maxsplit)"),
    (641, "number:1>2", "step.subject.split(\"::\", 1)[0]  (inner split maxsplit)"),
    (642, "number:1>2", "file_part.rsplit(\"/\", 1)[-1]  (rsplit maxsplit)"),
    # _write_shield_stub (line 662) `dest.parent.mkdir(parents=True, ...)`: the
    #   `parents=True -> False` flip. The stub's destination is always
    #   `<root>/tests/test_<stem>.py`, so `dest.parent` is ALWAYS `<root>/tests`
    #   — exactly ONE level below the project root, which already exists at the
    #   only call sites. `parents=False` therefore creates `<root>/tests`
    #   identically (only one level is ever needed), so the flag is
    #   behaviour-preserving. (The sibling `exist_ok=True` flip on the SAME line
    #   is NOT equivalent and is killed by test_write_shield_stub_never_clobbers
    #   / the existing-dir test.)
    (662, "constant:True>False", "dest.parent.mkdir(parents=True, ...)  "
                                 "(parents flag; parent is always <root>/tests)"),
}


def test_equivalent_mutants_are_documented():
    # A guard so the equivalence claims stay visible and reviewable. The proof
    # that each is equivalent is the invariance demonstrated below.
    # split: taking [0] is independent of maxsplit.
    assert "a::b::c".split("::", 1)[0] == "a::b::c".split("::", 2)[0] == "a"
    # rsplit: taking [-1] is independent of maxsplit.
    assert "a/b/c".rsplit("/", 1)[-1] == "a/b/c".rsplit("/", 2)[-1] == "c"
    # mkdir parents flag: creating a single missing level needs no `parents`.
    assert len(_EQUIVALENT_MUTANTS) == 4


# =========================================================================== #
# getattr(args, NAME, DEFAULT) default-value flips. A default is only OBSERVED  #
# when NAME is absent from the namespace; the tests above pass full namespaces  #
# so the default is dead. These tests pass SPARSE namespaces (only `target`     #
# set) so each getattr falls back to its literal default — flipping that        #
# default now changes behaviour. Kills the constant/number default flips in     #
# cmd_auto, cmd_evolve, cmd_ascend, cmd_shield, _develop_top and _auto_act.     #
# =========================================================================== #
def test_cmd_evolve_sparse_namespace_defaults(tmp_path, monkeypatch):
    # 414 history / 423 dry_run / 437 mode / 441 max_cycles / 442 max_apply /
    # 443 no_verify / 444 commit / 445 objective / 450 json all default here.
    _patch_evolve_run(monkeypatch)

    def _boom_hist(root):
        raise AssertionError("history default must be False")
    monkeypatch.setattr("app.engine.evolution.load_history", _boom_hist)
    rc = m.cmd_evolve(_ns(target=str(tmp_path)))
    assert rc == 0
    kw = _FakeLoop.last_kwargs
    assert kw["max_cycles"] == 3        # 441 default
    assert kw["max_apply_per_cycle"] == 5  # 442 default (and `or 5`)
    assert kw["verify"] is True         # 443: not (no_verify default False)
    assert kw["commit"] is False        # 444 default False
    assert kw["objective"] is None      # 445 default "" -> or None
    assert kw["mode"] == "supervised"   # 437: not commit -> supervised


def test_cmd_ascend_sparse_namespace_defaults(tmp_path, capsys, monkeypatch):
    # 1074 max_rounds / 1076 apply / 1077 no_verify / 1078 goal / 1079 max_steps
    # / 1080 fast / 1085 apply all default here.
    seen = {}
    _patch_ascend(monkeypatch, seen)
    rc = m.cmd_ascend(_ns(target=str(tmp_path), json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert seen["max_rounds"] == 4       # 1074 default
    assert seen["max_steps"] == 25       # 1079 default
    assert seen["apply"] is False        # 1076 default False
    assert seen["verify"] is True        # 1077: not (no_verify default False)
    assert seen["scope_verify"] is False  # 1080 default False
    assert seen["goal"] == ""            # 1078 default "" (`or ""`)
    assert "[ascend] Dry run" in out     # 1085: not (apply default False)


def test_cmd_shield_sparse_namespace_apply_default_false(tmp_path, capsys, monkeypatch):
    # Line 1001: the apply forwarded into _shield_all defaults False.
    monkeypatch.setattr("app.cli_autonomy._untested_own_modules",
                        lambda target: [])
    rc = m.cmd_shield(_ns(target=str(tmp_path), module="", all_modules=True,
                          json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["applied"] is False


def test_cmd_auto_sparse_namespace_defaults(tmp_path, monkeypatch):
    # 305 apply / 306 recommend / 321 json / 326 commit / 330 executable default.
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=0)
    # Scout with NO executable_steps key -> stats.get default 0 (kills 330).
    rc = m.cmd_auto(_ns(target=str(tmp_path)))
    assert rc == 0
    assert seen["explicit_apply"] is False     # 305
    assert seen["explicit_recommend"] is False  # 306
    assert seen["commit"] is False             # 326
    assert seen["executable_steps"] == 0       # 330


def test_cmd_auto_scout_missing_stat_defaults_zero(tmp_path, monkeypatch):
    # Line 330 specifically: scout.stats lacks "executable_steps".
    seen = {}
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)

    class _Scout:
        stats: dict = {}  # no executable_steps key

    class _Bridge:
        def plan_roadmap(self, report, mode="report", project_root="",
                         draft=False, proof=False):
            return _Scout()
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: _Bridge())
    monkeypatch.setattr("app.engine.idea_roadmap.RoadmapSynthesizer",
                        lambda *a, **k: type("R", (), {
                            "build": lambda self, report: _Roadmap()})())
    monkeypatch.setattr("app.engine.idea_tree_shape.analyze_tree_shape",
                        lambda report: _Shape())
    monkeypatch.setattr("app.cli_autonomy._auto_security_counts",
                        lambda target: (0, 0))
    monkeypatch.setattr("app.cli_autonomy._working_tree_clean",
                        lambda target: True)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: type("P", (), {
                            "load_all": lambda self: None,
                            "idea_operators": lambda self: []})())

    class _Policy:
        def decide(self, **kw):
            seen.update(kw)
            return _Decision(act=False)
    monkeypatch.setattr("app.policies.autonomy_policy.AutonomyPolicy",
                        lambda *a, **k: _Policy())
    monkeypatch.setattr("app.cli_autonomy._auto_recommend", lambda *a, **k: 0)
    m.cmd_auto(_ns(target=str(tmp_path)))
    assert seen["executable_steps"] == 0


def test_develop_top_sparse_namespace_defaults(tmp_path, capsys, monkeypatch):
    # 841 apply / 842 force / 844 json default False in _develop_top; with a
    # covered step and apply omitted -> the dry-run path runs (not apply/shield).
    proof = {"reparses": True, "added": 0, "removed": 0, "impact": "",
             "covered": True}
    bridge = _CapturingBridge(plan=_plan([_step(patch_preview={"diff": "d",
                                                               **proof})]))
    _patch_top(monkeypatch, bridge, covered=True)
    _CapturingBridge.last_plan = None
    rc = _develop_top(_ns(target=str(tmp_path), objective="dead-params"),
                      tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    # apply defaulted False -> dry-run preview, apply_plan never called.
    assert _CapturingBridge.last_plan is None
    assert "re-run with --apply" in out


def test_auto_act_sparse_namespace_verify_and_max_apply(tmp_path, capsys, monkeypatch):
    # 255 no_verify default / 256 max_apply default in _auto_act.
    _patch_auto_act(monkeypatch)
    _ActBridge.last = {}
    rc = m._auto_act(_ns(out=""), tmp_path, "goal", _ActBridge(), _FakeEngine(),
                     {}, mode="supervised", commit=False,
                     decision=_Decision(act=True), emit_json=False)
    assert rc == 0
    assert _ActBridge.last["verify"] is True   # 255: not (no_verify default F)
    assert _ActBridge.last["max_apply"] == 8   # 256: (max_apply default 0) or 8


def test_top_emit_apply_sparse_namespace_verify_default(tmp_path, capsys, monkeypatch):
    # Line 776: _top_emit_apply verify=not getattr(args,"no_verify",False).
    summary = {"results": [{"applied": True, "rolled_back": False,
                            "verified": True}]}
    bridge = _CapturingBridge(plan=_plan([_step()]), apply_summary=summary)
    _patch_top(monkeypatch, bridge, covered=True)
    _develop_top(_ns(target=str(tmp_path), objective="dead-params", apply=True),
                 tmp_path)
    assert _CapturingBridge.last_verify is True


def test_cmd_develop_sparse_namespace_grade_default_false(tmp_path, capsys, monkeypatch):
    # Line 586 `want_grade = getattr(args, "grade", False)`: omitted -> False,
    # so _grade_score is never read.
    def _boom(target):
        raise AssertionError("grade default must be False")
    monkeypatch.setattr("app.cli_autonomy._grade_score", _boom)
    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        lambda *a, **k: type("R", (), {
                            "steps": [], "applied": False, "blocked": [],
                            "to_dict": lambda self: {}})())
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# C")
    rc = cmd_develop(_ns(target=str(tmp_path), objective="dead-params",
                         json=False))
    assert rc == 0


# =========================================================================== #
# cmd_auto line 344 `if decision.act and mode == "report"`: the `and` must NOT  #
# upgrade a non-report mode. act=True with an inferred autonomous mode -> the    #
# mode passes through unchanged (an `and`->`or` flip would force "supervised").  #
# =========================================================================== #
def test_cmd_auto_act_non_report_mode_passes_through(tmp_path, monkeypatch):
    seen = {}
    # decision.mode is "autonomous"; explicit_mode None so mode = decision.mode.
    _patch_cmd_auto(monkeypatch, _Decision(act=True, mode="autonomous"), seen)
    captured = {}
    monkeypatch.setattr(
        "app.cli_autonomy._auto_act",
        lambda args, target, goal, bridge, engine, report, mode, commit,
        decision, emit_json: captured.update(mode=mode) or 0)
    rc = m.cmd_auto(_auto_ns(tmp_path, apply=True))
    assert rc == 0
    # `act(True) and mode=="report"(False)` -> False -> mode stays "autonomous";
    # an `or` flip would be True and force it to "supervised".
    assert captured["mode"] == "autonomous"


# =========================================================================== #
# _working_tree_clean line 368 `returncode != 0 or stdout != "true"`: a FAILED  #
# rev-parse (rc 128) must short-circuit to not-a-repo even if stdout says        #
# "true". An `or`->`and` flip would fall through to the status check.            #
# =========================================================================== #
def test_working_tree_clean_revparse_failure_is_dirty(monkeypatch):
    calls = []

    def _run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        calls.append(cmd[1])
        if cmd[1] == "rev-parse":
            return _Proc(128, "true\n")  # nonzero rc but stdout "true"
        return _Proc(0, "")  # a clean status, were it ever reached
    monkeypatch.setattr("subprocess.run", _run)
    from app.cli_autonomy import _working_tree_clean
    from pathlib import Path
    assert _working_tree_clean(Path("/x")) is False
    # The `or` short-circuits on the nonzero rc; the status command is never run
    # (an `and` flip would continue to it and wrongly report clean).
    assert "status" not in calls


# =========================================================================== #
# _untested_own_modules line 921 — the two `and`s in the filter are load-        #
# bearing: a non-.py module (str) and a fixture .py must both be excluded.       #
# =========================================================================== #
def test_untested_own_modules_excludes_non_py_and_fixtures(monkeypatch):
    from app.cli_autonomy import _untested_own_modules

    class _Profile:
        untested_modules = ["app/keep.py", "app/skip.txt",
                            "tests/fixtures/f.py", 123]

    class _Profiler:
        def __init__(self, target):
            pass

        def profile(self):
            return _Profile()
    monkeypatch.setattr("app.tools.project_profile.ProjectProfiler", _Profiler)
    monkeypatch.setattr("app.engine.health_score._is_fixture_path",
                        lambda p: "fixtures" in p)
    result = _untested_own_modules("/x")
    # `.py` filter (kills the m.endswith(".py) `and`) and the fixture filter
    # (kills the `not _is_fixture_path` `and`) both apply; the int 123 is
    # excluded by the isinstance(m, str) guard.
    assert result == ["app/keep.py"]


# =========================================================================== #
# _shield_all preview slice caps (lines 976 `[:40]`). With >40 candidates only  #
# the first 40 are listed.                                                       #
# =========================================================================== #
def test_shield_all_preview_caps_candidate_list_at_40(tmp_path, capsys, monkeypatch):
    from app.cli_autonomy import _shield_all
    mods = [f"app/m{i:03d}.py" for i in range(45)]
    monkeypatch.setattr("app.cli_autonomy._untested_own_modules",
                        lambda target: mods)
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: _ShieldObj(module=mod))
    rc = _shield_all(str(tmp_path), apply=False, as_json=False)
    out = capsys.readouterr().out
    assert rc == 0
    # The header counts ALL 45 candidates, but only 40 are listed (line 976).
    assert "would build 45 test(s)" in out
    listed = [ln for ln in out.splitlines() if ln.startswith("- app/m")]
    assert len(listed) == 40
    assert "- app/m039.py" in out
    assert "- app/m040.py" not in out


# =========================================================================== #
# _shield_all applied summary slice caps (981 `built[:40]`, 983 `failed[:10]`).  #
# =========================================================================== #
def test_shield_all_apply_caps_built_at_40_and_failed_at_10(tmp_path, capsys, monkeypatch):
    from app.cli_autonomy import _shield_all
    mods = [f"app/b{i:03d}.py" for i in range(45)] + \
           [f"app/f{i:03d}.py" for i in range(15)]
    monkeypatch.setattr("app.cli_autonomy._untested_own_modules",
                        lambda target: mods)
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda root, mod: _ShieldObj(module=mod))
    monkeypatch.setattr(
        "app.execution.test_shield.write_shield_test",
        lambda root, shield: f"tests/test_{shield.module.split('/')[-1]}")
    # modules starting app/b* pass; app/f* fail their generated test.
    monkeypatch.setattr(
        "app.cli_autonomy._verify_one_test",
        lambda target, path, timeout=120: "/test_b" in path)
    monkeypatch.setattr("os.remove", lambda p: None)
    rc = _shield_all(str(tmp_path), apply=True, as_json=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Built 45 verified test(s); 15 skipped" in out
    built_lines = [ln for ln in out.splitlines() if ln.startswith("- ✅")]
    failed_lines = [ln for ln in out.splitlines() if ln.startswith("- ↩️")]
    assert len(built_lines) == 40   # line 981 cap
    assert len(failed_lines) == 10  # line 983 cap


# =========================================================================== #
# _print_grade_proof `moves: int = 0` default param (line 893): called without  #
# moves -> record_run receives 0 (kills the 0->1 default flip).                  #
# =========================================================================== #
def test_print_grade_proof_default_moves_is_zero(capsys, monkeypatch):
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 70)
    seen = _capture_record_run(monkeypatch)
    # Call WITHOUT moves= so the default parameter is exercised.
    _print_grade_proof("/x", before=65, applied=True, objective="tidy")
    assert seen["moves"] == 0


# =========================================================================== #
# _maintain_scope_recipe — the error path returns exactly False (line 54), the  #
# bool contract a direct caller can observe (kills `return False`->`return       #
# None`). Also pins the True returns.                                            #
# =========================================================================== #
def test_maintain_scope_recipe_error_returns_false(capsys, monkeypatch):
    def _filter(plan, recipe):
        raise ValueError("unknown recipe `xyz`")
    monkeypatch.setattr("app.execution.recipes.filter_plan", _filter)
    result = _m_scope(_ns(recipe="xyz"), plan="PLAN")
    assert result is False
    out = capsys.readouterr().out
    assert "unknown recipe" in out


def test_maintain_scope_recipe_no_recipe_returns_true():
    assert _m_scope(_ns(recipe=""), plan="PLAN") is True


def test_maintain_scope_recipe_success_returns_true(capsys, monkeypatch):
    monkeypatch.setattr("app.execution.recipes.filter_plan",
                        lambda plan, recipe: 3)
    result = _m_scope(_ns(recipe="tidy"), plan="PLAN")
    assert result is True
    assert "scoped to recipe" in capsys.readouterr().out


# =========================================================================== #
# Final survivor closers: getattr-default observability + the ascend goal       #
# `or ""` flip.                                                                 #
# =========================================================================== #
def test_cmd_auto_json_default_false_prints_narrative(tmp_path, capsys, monkeypatch):
    # Line 321: emit_json defaults False -> the Markdown narrative IS printed
    # (line 322 `if not emit_json`). A False->True flip would suppress it.
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=0)
    m.cmd_auto(_ns(target=str(tmp_path)))  # json omitted
    out = capsys.readouterr().out
    assert "# Apex — autonomous review" in out


def test_cmd_auto_json_true_suppresses_narrative(tmp_path, capsys, monkeypatch):
    seen = {}
    _patch_cmd_auto(monkeypatch, _Decision(act=False), seen, executable=0)
    m.cmd_auto(_ns(target=str(tmp_path), json=True))
    out = capsys.readouterr().out
    assert "# Apex — autonomous review" not in out


def test_cmd_evolve_json_default_false_prints_markdown(tmp_path, capsys, monkeypatch):
    # Line 450: json defaults False -> the Markdown report is printed, not JSON.
    _patch_evolve_run(monkeypatch)
    m.cmd_evolve(_ns(target=str(tmp_path)))  # json omitted
    out = capsys.readouterr().out
    assert "# EVO" in out
    # markdown path means the result dict was NOT json-dumped.
    assert '"ok"' not in out


def test_develop_top_force_default_false_blocks_false_green(tmp_path, capsys, monkeypatch):
    # Line 842: force defaults False -> an apply on an uncovered module hits the
    # false-green guard (rc 2). A False->True flip would apply instead (rc 0/1).
    bridge = _CapturingBridge(plan=_plan([_step()]))
    _patch_top(monkeypatch, bridge, covered=False)
    _CapturingBridge.last_plan = None
    rc = _develop_top(_ns(target=str(tmp_path), objective="dead-params",
                          apply=True), tmp_path)  # force omitted
    assert rc == 2
    assert _CapturingBridge.last_plan is None  # never applied
    assert "FALSE green" in capsys.readouterr().out


def test_cmd_ascend_goal_or_empty_forwards_nonempty_goal(tmp_path, capsys, monkeypatch):
    # Line 1078 `getattr(args, "goal", "") or ""`: a non-empty goal flows
    # through unchanged. `"reduce" or ""` -> "reduce"; an `or`->`and` flip would
    # yield "" (`"reduce" and ""` == "").
    seen = {}
    _patch_ascend(monkeypatch, seen)
    m.cmd_ascend(_ascend_ns(tmp_path, goal="reduce"))
    assert seen["goal"] == "reduce"
