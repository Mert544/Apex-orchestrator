"""Characterization tests pinning the dispatch routing of cmd_develop and
cmd_auto in app/cli_autonomy.py.

These were added alongside a behavior-preserving extraction of those two
high-complexity commands into cohesive private helpers. They lock the routing
contract: for a representative set of flag combinations each command must reach
exactly one sub-mode helper / branch and return that helper's code unchanged.

The sub-mode helpers themselves are monkeypatched to sentinel return codes so
this file asserts the parent's *dispatch* (which branch, which return code, no
double-dispatch) without running any real engine, planner, apply or subprocess.
No time/random/order assertions.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import cmd_auto, cmd_develop
from app.policies.autonomy_policy import AutonomyDecision


# --------------------------------------------------------------------------- #
# cmd_develop dispatch                                                         #
# --------------------------------------------------------------------------- #
def _dev_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), objective="dead-params", goal="",
                all_objectives=False, grade=False, history=False, from_dream=False,
                playbook=False, top=False, apply=False, max_steps=3, no_verify=True,
                fast=False, json=True)
    base.update(over)
    return argparse.Namespace(**base)


def _route_develop(monkeypatch):
    """Replace every cmd_develop sub-mode with a sentinel; return the call log."""
    calls: list[str] = []

    def _stub(name, rc):
        def _f(*a, **k):
            calls.append(name)
            return rc
        return _f

    monkeypatch.setattr(m, "_develop_playbook", _stub("playbook", 0))
    monkeypatch.setattr(m, "_develop_history", _stub("history", 0))
    monkeypatch.setattr(m, "_develop_top", _stub("top", 7))
    monkeypatch.setattr(m, "_develop_goal", _stub("goal", 0))
    monkeypatch.setattr(m, "_develop_all", _stub("all", 0))
    monkeypatch.setattr(m, "_develop_from_dream", _stub("from_dream", 0))
    monkeypatch.setattr(m, "_develop_objective", _stub("objective", 0))
    # grade-before is read before the goal/all/objective branches; keep it cheap.
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    return calls


def test_develop_routes_to_playbook(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, playbook=True))
    assert rc == 0 and calls == ["playbook"]


def test_develop_routes_to_history(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, history=True))
    assert rc == 0 and calls == ["history"]


def test_develop_routes_to_top_and_returns_its_code(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, top=True))
    assert rc == 7 and calls == ["top"]


def test_develop_routes_to_goal(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt"))
    assert rc == 0 and calls == ["goal"]


def test_develop_routes_to_all(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True))
    assert rc == 0 and calls == ["all"]


def test_develop_routes_to_from_dream(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, from_dream=True))
    assert rc == 0 and calls == ["from_dream"]


def test_develop_default_routes_to_objective(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path))
    assert rc == 0 and calls == ["objective"]


def test_develop_playbook_precedes_every_other_flag(tmp_path, monkeypatch):
    # The dispatch order is load-bearing: --playbook wins even with --top/--goal.
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, playbook=True, top=True, goal="x",
                             all_objectives=True, from_dream=True))
    assert rc == 0 and calls == ["playbook"]


def test_develop_grade_read_only_when_grade_flag_set(tmp_path, monkeypatch):
    # grade_before is read for the goal/all/objective branches; the early
    # playbook/history/top branches must short-circuit before it.
    reads: list[str] = []
    _route_develop(monkeypatch)
    monkeypatch.setattr(m, "_grade_score",
                        lambda target: reads.append("read") or 50)
    cmd_develop(_dev_ns(tmp_path, playbook=True, grade=True))
    assert reads == []  # playbook short-circuits before any grade read
    cmd_develop(_dev_ns(tmp_path, grade=True))  # default objective branch
    assert reads == ["read"]


# --------------------------------------------------------------------------- #
# Positional `mode_word` -> objective DWIM (the field-test footgun fix)        #
#                                                                              #
# `apex develop seal-hashable-eq` used to fall through to the --objective      #
# DEFAULT (dead-params) with no warning. These pin the corrected routing: a    #
# positional that names a registered objective IS that objective; a typo       #
# errors non-zero (not a silent dead-params run); the `session` mode and the   #
# explicit --objective flag are unaffected.                                    #
# --------------------------------------------------------------------------- #
def _capture_objective(monkeypatch) -> dict:
    """Stub the single-objective + session helpers, recording which objective
    `_develop_objective` was handed (or that `_develop_session` ran)."""
    seen: dict = {}

    def _obj(args, target, objective, grade_before, max_steps, verify, apply):
        seen["objective"] = objective
        return 0

    def _session(*a, **k):
        seen["session"] = True
        return 0

    monkeypatch.setattr(m, "_develop_objective", _obj)
    monkeypatch.setattr(m, "_develop_session", _session)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    return seen


def test_develop_positional_objective_name_selects_that_objective(tmp_path, monkeypatch):
    # The footgun: a bare objective name must select THAT objective, not the
    # --objective default (dead-params).
    seen = _capture_objective(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, mode_word="seal-hashable-eq"))
    assert rc == 0
    assert seen.get("objective") == "seal-hashable-eq"
    assert seen["objective"] != "dead-params"


def test_develop_positional_session_word_still_runs_session_mode(tmp_path, monkeypatch):
    # `session` is a recognized MODE word, not an objective — it must keep
    # routing to the combined session run.
    seen = _capture_objective(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, mode_word="session"))
    assert rc == 0 and seen.get("session") is True
    assert "objective" not in seen


def test_develop_unknown_positional_errors_nonzero_not_silent_default(tmp_path, monkeypatch, capsys):
    # A typo must error helpfully to stderr and exit non-zero — NOT silently run
    # dead-params (the old misleading "Fitness 0 -> 0").
    seen = _capture_objective(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, mode_word="seal-hashable-eqq"))
    assert rc != 0
    assert seen == {}  # neither the objective nor the session helper ran
    err = capsys.readouterr().err
    assert "unknown develop mode/objective 'seal-hashable-eqq'" in err
    assert "--objective" in err  # points the user at the right flag


def test_develop_explicit_objective_flag_wins_over_positional(tmp_path, monkeypatch):
    # When both a positional name and an explicit --objective (not the default)
    # are given, the explicit flag wins — a deliberate flag is never overridden.
    seen = _capture_objective(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, mode_word="seal-hashable-eq",
                             objective="modernize"))
    assert rc == 0 and seen.get("objective") == "modernize"


def test_develop_bare_invocation_unchanged_defaults_to_dead_params(tmp_path, monkeypatch):
    # No positional, no --objective: the default campaign (dead-params) is
    # byte-identical to before the DWIM fix.
    seen = _capture_objective(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path))
    assert rc == 0 and seen.get("objective") == "dead-params"


# --------------------------------------------------------------------------- #
# cmd_auto dispatch (recommend vs act)                                         #
# --------------------------------------------------------------------------- #
def _auto_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(goal="", target=str(tmp_path), apply=False, recommend=False,
                mode=None, commit=False, no_verify=True, max_apply=0, json=False,
                out="")
    base.update(over)
    return argparse.Namespace(**base)


class _Shape:
    observations: list = []
    heaviest_module = ""
    heaviest_loc = 0
    total_ideas = 0
    distinct_subjects = 0


class _Roadmap:
    quick_wins: list = []


class _Scout:
    stats = {"executable_steps": 3}


class _Bridge:
    def plan_roadmap(self, *a, **k):
        return _Scout()


def _route_auto(monkeypatch, *, decision):
    """Stub everything cmd_auto pulls in up to the dispatch fork, and replace the
    two terminal branches with sentinels. Returns the recommend/act call log."""
    calls: list[str] = []

    class _Engine:
        last_profile = None

        def __init__(self, **kw):
            pass

        def run(self, objective=None):
            return {}

    class _Plugins:
        def load_all(self):
            pass

        def idea_operators(self):
            return []

    class _Synth:
        def build(self, report):
            return _Roadmap()

    class _Policy:
        def decide(self, **kw):
            return decision

    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine", _Engine)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry", lambda *a, **k: _Plugins())
    monkeypatch.setattr("app.engine.idea_roadmap.RoadmapSynthesizer",
                        lambda *a, **k: _Synth())
    monkeypatch.setattr("app.engine.idea_tree_shape.analyze_tree_shape",
                        lambda report: _Shape())
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: _Bridge())
    monkeypatch.setattr("app.policies.autonomy_policy.AutonomyPolicy",
                        lambda *a, **k: _Policy())
    monkeypatch.setattr(m, "_auto_resolve_mode", lambda args, goal: None)
    monkeypatch.setattr(m, "_auto_security_counts", lambda target: (0, 0))
    monkeypatch.setattr(m, "_auto_narrative",
                        lambda *a, **k: ["# Apex"])
    monkeypatch.setattr(m, "_working_tree_clean", lambda target: True)

    def _rec(*a, **k):
        calls.append("recommend")
        return 0

    def _act(*a, **k):
        calls.append("act")
        return 0

    monkeypatch.setattr(m, "_auto_recommend", _rec)
    monkeypatch.setattr(m, "_auto_act", _act)
    return calls


def test_auto_routes_to_recommend_when_policy_declines(tmp_path, capsys, monkeypatch):
    decision = AutonomyDecision(False, "report", "no safe fixes")
    calls = _route_auto(monkeypatch, decision=decision)
    rc = cmd_auto(_auto_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0 and calls == ["recommend"]
    assert "# Apex" in out  # the narrative still prints in non-JSON mode


def test_auto_routes_to_act_when_policy_acts(tmp_path, monkeypatch):
    decision = AutonomyDecision(True, "supervised", "safe to apply")
    calls = _route_auto(monkeypatch, decision=decision)
    rc = cmd_auto(_auto_ns(tmp_path, apply=True))
    assert rc == 0 and calls == ["act"]


def test_auto_report_mode_promoted_to_supervised_when_acting(tmp_path, monkeypatch):
    # decision.act with mode "report" must be promoted to a patch-capable mode
    # before _auto_act runs (acting requires a patch-capable mode).
    seen: dict = {}
    decision = AutonomyDecision(True, "report", "act")
    _route_auto(monkeypatch, decision=decision)

    def _act(args, target, goal, bridge, engine, report, mode,
             commit, dec, emit_json):
        seen["mode"] = mode
        return 0

    monkeypatch.setattr(m, "_auto_act", _act)
    rc = cmd_auto(_auto_ns(tmp_path, apply=True))
    assert rc == 0 and seen["mode"] == "supervised"


def test_auto_json_mode_suppresses_narrative_print(tmp_path, capsys, monkeypatch):
    decision = AutonomyDecision(False, "report", "no safe fixes")
    _route_auto(monkeypatch, decision=decision)
    cmd_auto(_auto_ns(tmp_path, json=True))
    # The narrative is only printed in non-JSON mode; the recommend sentinel
    # prints nothing, so JSON-mode output stays empty here.
    assert capsys.readouterr().out == ""
