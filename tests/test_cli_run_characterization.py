"""Characterization harness proving the cmd_run decomposition is byte-identical.

Loads the original (pre-refactor) cmd_run from a snapshot committed at HEAD and
the refactored cmd_run from app.cli, then drives both across a matrix of
arg/goal/mode combinations under identical mocks. stdout, stderr, exit code, and
the env mutations must match byte-for-byte.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_original_cmd_run():
    """Reconstruct the pre-refactor cmd_run from git HEAD as an isolated module."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/cli.py"], cwd=str(REPO)
    ).decode("utf-8")
    mod = types.ModuleType("_cli_original_snapshot")
    mod.__dict__["__name__"] = "_cli_original_snapshot"
    # Stub the heavy import-surface so exec'ing the snapshot does not pull in
    # the whole CLI family; cmd_run only needs argparse/json/os/sys/Path +
    # _get_project_root, which we inject after exec via monkeypatch in the test.
    exec(compile(src, "app/cli.py(HEAD)", "exec"), mod.__dict__)
    return mod


# ---------------------------------------------------------------------------
# Shared fakes (deterministic, no network, no real engine work)
# ---------------------------------------------------------------------------


class _FakeIntent:
    def __init__(self, goal: str):
        self.goal = goal


class _FakeParser:
    def parse(self, goal, explicit_mode=None):
        return _FakeIntent(goal)


class _FakePlan:
    def __init__(self, mode: str):
        self.plan_name = "plan_x"
        self.steps = [1, 2, 3]
        self.agents = ["a", "b"] if mode != "report" else []
        self.mode = mode
        self.can_patch = mode == "autonomous"
        self.fallback_plan = "fb"
        self.rationale = "because reasons"


class _FakePlanner:
    def __init__(self, mode_from_args):
        self._mode = mode_from_args

    def build_plan(self, intent):
        return _FakePlan(self._mode)


class _FakeAgent:
    def run(self, project_root, max_depth):
        return {"root": project_root, "depth": max_depth}


class _FakeComposer:
    def __init__(self, results):
        self._n = len(results)

    def to_markdown(self):
        # Long enough to exercise the >1500 truncation branch.
        return "FRACTAL-SUMMARY " * 200


def _install_fakes(monkeypatch, plan_mode: str, target: Path):
    """Patch every collaborator both cli modules import, in both namespaces."""
    intent_mod = types.ModuleType("app.intent.parser")
    intent_mod.IntentParser = _FakeParser
    planner_mod = types.ModuleType("app.automation.planner")
    planner_mod.AutonomousPlanner = lambda: _FakePlanner(plan_mode)
    main_mod = types.ModuleType("app.main")
    calls = []
    main_mod.main = lambda: calls.append("main")
    fractal_mod = types.ModuleType("app.agents.fractal_agents")
    fractal_mod.FractalSecurityAgent = _FakeAgent
    composer_mod = types.ModuleType("app.reporting.composer")
    composer_mod.ReportComposer = _FakeComposer

    monkeypatch.setitem(sys.modules, "app.intent.parser", intent_mod)
    monkeypatch.setitem(sys.modules, "app.automation.planner", planner_mod)
    monkeypatch.setitem(sys.modules, "app.main", main_mod)
    monkeypatch.setitem(sys.modules, "app.agents.fractal_agents", fractal_mod)
    monkeypatch.setitem(sys.modules, "app.reporting.composer", composer_mod)
    return calls


_GOALS = [
    "fix docstrings",
    "security audit",
    "improve RISK posture",
    "find a vuln",
    "make it nicer",
    "AUDIT everything",
    "",
]
_MODES = ["report", "supervised", "autonomous"]
_BOOL_TRI = [None, True, False]


def _arg_matrix():
    """A representative but exhaustive-enough cross product of run flags."""
    combos = []
    for goal in _GOALS:
        for mode in _MODES:
            combos.append(dict(
                goal=goal, mode=mode, fractal=False,
                auto_patch=None, auto_commit=None, max_fractal_budget=None,
                safety_policy=None, dry_run=False,
            ))
    # Flag-toggle sweep (single goal/mode to keep it focused but cover each knob)
    for fractal in (True, False):
        for ap in _BOOL_TRI:
            for ac in _BOOL_TRI:
                for budget in (None, 0, 7):
                    for policy in (None, "minimal", "standard", "strict"):
                        for dry in (True, False):
                            combos.append(dict(
                                goal="security audit", mode="autonomous",
                                fractal=fractal, auto_patch=ap, auto_commit=ac,
                                max_fractal_budget=budget, safety_policy=policy,
                                dry_run=dry,
                            ))
    return combos


def _run_one(func, monkeypatch, target, combo):
    """Invoke `func` with a clean env, returning (rc, stdout, stderr, env_delta).

    `_get_project_root` is bound into the callable's own globals and restored
    afterwards so neither the live `app.cli` module nor the snapshot leaks.
    """
    args = argparse.Namespace(target=str(target), **combo)
    calls = _install_fakes(monkeypatch, combo["mode"], target)
    g = func.__globals__
    had_root = "_get_project_root" in g
    saved_root = g.get("_get_project_root")
    g["_get_project_root"] = lambda: target

    tracked = [
        "EPISTEMIC_TARGET_ROOT", "EPISTEMIC_AUTOMATION_PLAN", "EPISTEMIC_OBJECTIVE",
        "APEX_USE_FRACTAL", "APEX_AUTO_PATCH", "APEX_AUTO_COMMIT",
        "APEX_MAX_FRACTAL_BUDGET", "APEX_SAFETY_POLICY", "APEX_DRY_RUN", "APEX_MODE",
    ]
    for k in tracked:
        os.environ.pop(k, None)

    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = func(args)
    finally:
        if had_root:
            g["_get_project_root"] = saved_root
        else:
            g.pop("_get_project_root", None)
    env_delta = {k: os.environ.get(k) for k in tracked}
    return rc, out.getvalue(), err.getvalue(), env_delta, len(calls)


@pytest.fixture(scope="module")
def original_module():
    return _load_original_cmd_run()


@pytest.mark.parametrize("combo", _arg_matrix())
def test_cmd_run_byte_identical(combo, original_module, tmp_path, monkeypatch):
    from app import cli as refactored

    orig_rc, orig_out, orig_err, orig_env, orig_calls = _run_one(
        original_module.cmd_run, monkeypatch, tmp_path, combo
    )
    new_rc, new_out, new_err, new_env, new_calls = _run_one(
        refactored.cmd_run, monkeypatch, tmp_path, combo
    )

    assert new_rc == orig_rc, combo
    assert new_out == orig_out, combo
    assert new_err == orig_err, combo
    assert new_env == orig_env, combo
    assert new_calls == orig_calls == 1, combo


def test_reexport_surface_preserved():
    """The decomposition must not disturb cli.py's re-export import surface."""
    from app import cli
    for name in (
        "cmd_auto", "cmd_develop", "cmd_evolve", "cmd_maintain", "cmd_shield",
        "cmd_simulate", "_working_tree_clean", "_get_project_root",
        "cmd_brief", "cmd_changelog", "cmd_dream", "cmd_scan", "cmd_metrics",
        "cmd_review", "_apply_review_fixes", "_render_review_fixes_markdown",
        "cmd_rename", "cmd_move", "cmd_signature", "cmd_ideate", "cmd_plugin_list",
        "cmd_dashboard", "cmd_canvas", "cmd_bench", "cmd_run", "main",
    ):
        assert hasattr(cli, name), name
