"""Deterministic coverage for the remaining app/cli_autonomy.py surface:

  * register_parsers wiring (each subcommand's defaults + func binding),
  * the develop[non-top] "_Applied …_" footer branches (goal / --all /
    --from-dream / objective) under --apply,
  * the small pure-ish helpers _working_tree_clean (error path), _grade_score,
    _print_grade_proof and _verify_one_test (subprocess stubbed),
  * cmd_simulate's objective pass-through and cmd_shield's json+apply branch.

Compile/grade collaborators are patched at their source modules so no real
engine, grader, or pytest subprocess runs. No time/random/order assertions.
"""

from __future__ import annotations

import argparse
import json

from app.cli_autonomy import (
    _grade_score,
    _print_grade_proof,
    _shield_all,
    _verify_one_test,
    _working_tree_clean,
    cmd_develop,
    cmd_shield,
    cmd_simulate,
    register_parsers,
)


# --------------------------------------------------------------------------- #
# register_parsers — every subcommand binds its func + defaults.              #
# --------------------------------------------------------------------------- #
def _parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    register_parsers(sub)
    return p


def test_register_parsers_binds_all_funcs():
    from app import cli_autonomy as m
    p = _parser()
    cases = {
        "plan": m.cmd_plan, "ascend": m.cmd_ascend, "auto": m.cmd_auto,
        "simulate": m.cmd_simulate, "evolve": m.cmd_evolve,
        "develop": m.cmd_develop, "shield": m.cmd_shield,
        "maintain": m.cmd_maintain,
    }
    for name, func in cases.items():
        ns = p.parse_args([name])
        assert ns.func is func


def test_register_parsers_maintain_defaults():
    ns = _parser().parse_args(["maintain"])
    assert ns.mode == "supervised"
    assert ns.max_ideas == 40
    assert ns.dry_run is False
    assert ns.recipe == ""


def test_register_parsers_auto_goal_positional_and_flags():
    ns = _parser().parse_args(["auto", "tidy up", "--apply", "--max-apply", "3"])
    assert ns.goal == "tidy up"
    assert ns.apply is True
    assert ns.max_apply == 3


def test_register_parsers_develop_flags():
    ns = _parser().parse_args(["develop", "--top", "--shield", "--force", "--apply"])
    assert ns.top is True and ns.shield is True and ns.force is True
    assert ns.apply is True
    assert ns.objective == "dead-params"


def test_register_parsers_shield_all_and_module():
    ns = _parser().parse_args(["shield", "app/foo.py", "--all", "--apply"])
    assert ns.module == "app/foo.py"
    assert ns.all_modules is True
    assert ns.apply is True


def test_register_parsers_evolve_and_simulate_caps():
    evo = _parser().parse_args(["evolve", "--max-cycles", "2", "--max-apply", "7"])
    assert evo.max_cycles == 2 and evo.max_apply == 7
    sim = _parser().parse_args(["simulate", "--max-cycles", "1"])
    assert sim.max_cycles == 1


def test_register_parsers_ascend_until_and_fast():
    ns = _parser().parse_args(["ascend", "--until", "A-", "--fast", "--apply"])
    assert ns.until == "A-" and ns.fast is True and ns.apply is True


# --------------------------------------------------------------------------- #
# _working_tree_clean — error path returns False.                            #
# --------------------------------------------------------------------------- #
def test_working_tree_clean_non_repo_is_false(tmp_path):
    # A bare directory is not a git work tree -> "not clean".
    assert _working_tree_clean(tmp_path) is False


def test_working_tree_clean_subprocess_error_is_false(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("git missing")
    monkeypatch.setattr("subprocess.run", _boom)
    assert _working_tree_clean(tmp_path) is False


# --------------------------------------------------------------------------- #
# _grade_score / _print_grade_proof                                          #
# --------------------------------------------------------------------------- #
def test_grade_score_failure_returns_minus_one(monkeypatch):
    def _boom(target):
        raise RuntimeError("no grader")
    monkeypatch.setattr("app.engine.health_score.grade", _boom)
    assert _grade_score("/nope") == -1


def test_print_grade_proof_skips_when_not_applied(capsys):
    _print_grade_proof("/x", before=80, applied=False)
    assert capsys.readouterr().out == ""


def test_print_grade_proof_skips_when_before_none(capsys):
    _print_grade_proof("/x", before=None, applied=True)
    assert capsys.readouterr().out == ""


def test_print_grade_proof_reports_gain(capsys, monkeypatch):
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 90)
    monkeypatch.setattr("app.engine.dev_history.record_run",
                        lambda target, objective, moves, before, after: None)
    _print_grade_proof("/x", before=80, applied=True, objective="tidy", moves=3)
    out = capsys.readouterr().out
    assert "Health grade: 80 → 90 (+10 ↑)" in out


def test_print_grade_proof_after_unreadable_is_silent(capsys, monkeypatch):
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: -1)
    _print_grade_proof("/x", before=80, applied=True)
    assert capsys.readouterr().out == ""


def test_print_grade_proof_history_failure_is_swallowed(capsys, monkeypatch):
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 70)

    def _boom(*a, **k):
        raise RuntimeError("history broke")
    monkeypatch.setattr("app.engine.dev_history.record_run", _boom)
    # No exception must escape; the grade line is still printed.
    _print_grade_proof("/x", before=70, applied=True)
    assert "Health grade: 70 → 70 (0 →)" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# _verify_one_test — subprocess fully stubbed.                               #
# --------------------------------------------------------------------------- #
def test_verify_one_test_passes(monkeypatch):
    class _R:
        returncode = 0
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
    assert _verify_one_test("/x", "tests/test_x.py") is True


def test_verify_one_test_failure_returncode(monkeypatch):
    class _R:
        returncode = 1
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
    assert _verify_one_test("/x", "tests/test_x.py") is False


def test_verify_one_test_timeout_is_false(monkeypatch):
    import subprocess

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)
    monkeypatch.setattr("subprocess.run", _boom)
    assert _verify_one_test("/x", "tests/test_x.py") is False


# --------------------------------------------------------------------------- #
# _shield_all — direct branch coverage (generation/verify/remove paths).      #
# --------------------------------------------------------------------------- #
class _Shield:
    def __init__(self, module):
        self.module = module
        self.test_path = f"tests/test_{module.split('/')[-1][:-3]}_char.py"
        self.functions = ["f"]
        self.content = "def test_f():\n    pass\n"


def _patch_shield_all(monkeypatch, *, modules, gen, verify):
    monkeypatch.setattr("app.cli_autonomy._untested_own_modules",
                        lambda target: modules)
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test", gen)
    monkeypatch.setattr("app.execution.test_shield.write_shield_test",
                        lambda target, shield: shield.test_path)
    monkeypatch.setattr("app.cli_autonomy._verify_one_test",
                        lambda target, path, timeout=120: verify)


def test_shield_all_skips_unshieldable_module(tmp_path, capsys, monkeypatch):
    """A module whose generator returns None is skipped (never a candidate)."""
    _patch_shield_all(monkeypatch, modules=["app/a.py", "app/b.py"],
                      gen=lambda target, mod: None if mod == "app/a.py"
                      else _Shield(mod), verify=True)
    rc = _shield_all(str(tmp_path), apply=False, as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["candidates"] == ["app/b.py"]


def test_shield_all_apply_built_listing(tmp_path, capsys, monkeypatch):
    _patch_shield_all(monkeypatch, modules=["app/a.py"],
                      gen=lambda target, mod: _Shield(mod), verify=True)
    rc = _shield_all(str(tmp_path), apply=True, as_json=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Built 1 verified test(s)" in out
    assert "✅ tests/test_a_char.py" in out


def test_shield_all_apply_remove_oserror_swallowed(tmp_path, capsys, monkeypatch):
    """A failing generated test is removed; an OSError on remove is swallowed and
    the module is still reported as failed."""
    _patch_shield_all(monkeypatch, modules=["app/a.py"],
                      gen=lambda target, mod: _Shield(mod), verify=False)

    def _boom(path):
        raise OSError("cannot remove")
    monkeypatch.setattr("os.remove", _boom)
    rc = _shield_all(str(tmp_path), apply=True, as_json=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 skipped" in out
    assert "app/a.py (generated test didn't pass — removed)" in out


# --------------------------------------------------------------------------- #
# cmd_simulate — objective is forwarded to simulate_evolution.               #
# --------------------------------------------------------------------------- #
def test_simulate_forwards_objective(tmp_path, capsys, monkeypatch):
    captured = {}

    class _Result:
        def to_dict(self):
            return {"cycles": 0}

    def _sim(target, max_cycles=3, max_apply_per_cycle=5, objective=None):
        captured.update(target=target, max_cycles=max_cycles,
                        max_apply_per_cycle=max_apply_per_cycle, objective=objective)
        return _Result()

    monkeypatch.setattr("app.engine.simulation.simulate_evolution", _sim)
    monkeypatch.setattr("app.engine.simulation.render_simulation_markdown",
                        lambda result, target: "# Sim")
    ns = argparse.Namespace(target=str(tmp_path), json=False, objective="security",
                            max_cycles=2, max_apply=4)
    rc = cmd_simulate(ns)
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Sim" in out
    assert captured["objective"] == "security"
    assert captured["max_cycles"] == 2
    assert captured["max_apply_per_cycle"] == 4


# --------------------------------------------------------------------------- #
# cmd_shield — JSON path also writes when --apply.                           #
# --------------------------------------------------------------------------- #
def test_shield_json_apply_writes(tmp_path, capsys, monkeypatch):
    class _Shield:
        module = "app/pub.py"
        test_path = "tests/test_pub_characterization.py"
        functions = ["pub"]
        content = "def test_pub():\n    pass\n"

    wrote = {}
    monkeypatch.setattr(
        "app.execution.test_shield.generate_characterization_test",
        lambda target, module: _Shield())

    def _write(target, shield):
        wrote["path"] = shield.test_path
        return shield.test_path
    monkeypatch.setattr("app.execution.test_shield.write_shield_test", _write)

    ns = argparse.Namespace(target=str(tmp_path), module="app/pub.py",
                            all_modules=False, apply=True, json=True)
    rc = cmd_shield(ns)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["module"] == "app/pub.py"
    assert payload["functions"] == ["pub"]
    # --apply still wrote the file in the JSON branch
    assert wrote["path"] == "tests/test_pub_characterization.py"


# --------------------------------------------------------------------------- #
# develop[non-top] — the "_Applied …_" footers under --apply.                 #
# --------------------------------------------------------------------------- #
def _dev_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), objective="dead-params", goal="",
                all_objectives=False, grade=False, history=False,
                from_dream=False, deep=False, playbook=False, top=False, apply=True,
                max_steps=3, no_verify=True, fast=False, json=False)
    base.update(over)
    return argparse.Namespace(**base)


def test_develop_goal_apply_footer(tmp_path, capsys, monkeypatch):
    class _GR:
        objectives = ["dead-params"]
        total_moves = 2

        def to_dict(self):
            return {"objectives": self.objectives}

    monkeypatch.setattr("app.engine.fractal_develop.compile_goal",
                        lambda *a, **k: _GR())
    monkeypatch.setattr("app.engine.fractal_develop.render_goal_markdown",
                        lambda gr: "# Goal")
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Goal" in out
    assert "Applied to your working tree" in out


def test_develop_goal_apply_no_moves_omits_footer(tmp_path, capsys, monkeypatch):
    """apply=True but zero moves -> no '_Applied …_' footer (the 452 branch)."""
    class _GR:
        objectives = ["dead-params"]
        total_moves = 0

        def to_dict(self):
            return {"objectives": self.objectives}

    monkeypatch.setattr("app.engine.fractal_develop.compile_goal",
                        lambda *a, **k: _GR())
    monkeypatch.setattr("app.engine.fractal_develop.render_goal_markdown",
                        lambda gr: "# Goal")
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Goal" in out
    assert "Applied to your working tree" not in out


def test_develop_all_objectives_apply_footer_and_grade(tmp_path, capsys, monkeypatch):
    class _R:
        steps = [1, 2]

        def to_dict(self):
            return {"steps": self.steps}

    monkeypatch.setattr("app.engine.objective_compiler.compile_all",
                        lambda *a, **k: [_R()])
    monkeypatch.setattr("app.engine.objective_compiler.render_all_markdown",
                        lambda results: "# All")
    # grade=True -> _print_grade_proof runs; control both reads.
    monkeypatch.setattr("app.cli_autonomy._grade_score", lambda t: 88)
    monkeypatch.setattr("app.engine.dev_history.record_run",
                        lambda *a, **k: None)
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True, grade=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "# All" in out
    assert "Applied to your working tree" in out
    assert "Health grade:" in out


def test_develop_from_dream_apply_footer(tmp_path, capsys, monkeypatch):
    class _R:
        steps = [1]

        def to_dict(self):
            return {"steps": self.steps}

    monkeypatch.setattr("app.engine.dream_landing.dream_confluence_modules",
                        lambda target: ["app/m.py"])
    monkeypatch.setattr("app.engine.dream_landing.compile_from_dream",
                        lambda *a, **k: [_R()])
    monkeypatch.setattr("app.engine.objective_compiler.render_from_dream_markdown",
                        lambda results, modules, sweep=False: "# Dream")
    rc = cmd_develop(_dev_ns(tmp_path, from_dream=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Dream" in out
    assert "Applied to your working tree" in out


def test_develop_objective_apply_footer(tmp_path, capsys, monkeypatch):
    class _R:
        steps = [1, 2, 3]
        applied = True
        blocked: list = []

        def to_dict(self):
            return {"steps": self.steps, "applied": self.applied}

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        lambda *a, **k: _R())
    monkeypatch.setattr("app.engine.objective_compiler.render_compile_markdown",
                        lambda result: "# Compiled")
    rc = cmd_develop(_dev_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Compiled" in out
    assert "Applied to your working tree" in out
