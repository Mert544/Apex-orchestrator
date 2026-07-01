"""`apex develop --chain` and `apex develop --goal X --atomic` — the CLI doors
that make the shipped ``chain_compiler.run_chain`` / ``project_goal_orchestrator.
orchestrate_goal`` engines user-invokable.

These pin the WIRING, not a reimplementation: the two handlers PARSE the flag,
call the EXISTING engine, and render its report — they add no gate logic (the
never-fake-green suite-gate + rollback live inside the engines). Tests assert:

  * ``--chain a,b`` parses the comma sequence into an ordered list and hands it
    VERBATIM to ``run_chain`` (spied), rendering the chain report;
  * a malformed ``--chain`` (empty, or an unknown objective) is refused HONESTLY
    (non-zero, an error to stderr) before ANY engine call — no partial campaign;
  * ``--goal X --atomic`` routes to ``orchestrate_goal`` (spied), NOT the default
    per-leaf ``compile_goal`` path; ``--goal X`` without ``--atomic`` is unchanged;
  * bare ``apex develop`` (no --chain/--goal) dispatches BYTE-IDENTICALLY to today
    (the default single-objective campaign) — the new flags default off;
  * ``--chain --apply`` threads apply=True; a HALTED chain / an unknown goal / a
    rolled-back goal exit non-zero, an honest chain/goal exits 0.

The engines themselves are spied to sentinel reports so this file asserts the
CLI's parse+dispatch+render+exit, running no real compiler/apply/subprocess.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import _parse_chain, cmd_develop
from app.engine.chain_compiler import ChainReport
from app.engine.project_goal_orchestrator import GoalLanding


# --------------------------------------------------------------------------- #
# namespace helper — mirrors the dispatch characterization test's `_dev_ns`,   #
# EXTENDED with the new (default-off) flags so a test can flip exactly one.     #
# --------------------------------------------------------------------------- #
def _ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), objective="dead-params", goal="",
                all_objectives=False, grade=False, history=False, from_dream=False,
                playbook=False, top=False, apply=False, max_steps=3, no_verify=True,
                fast=False, json=True, mode_word="", session=False,
                chain="", halt_on_unmet=False, atomic=False, value_led=False)
    base.update(over)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# _parse_chain — the honest parse + refusal (pure, no engine)                  #
# --------------------------------------------------------------------------- #
def test_parse_chain_splits_and_trims_source_order():
    objs, err = _parse_chain(" implement-stub , sort-imports ,")
    assert err is None
    assert objs == ["implement-stub", "sort-imports"]  # trimmed, empties dropped


def test_parse_chain_empty_refuses():
    objs, err = _parse_chain("")
    assert objs == [] and err is not None and "empty --chain" in err


def test_parse_chain_whitespace_only_refuses():
    objs, err = _parse_chain("  ,  ,")
    assert objs == [] and err is not None and "empty --chain" in err


def test_parse_chain_unknown_objective_refuses_and_names_it():
    objs, err = _parse_chain("implement-stub,not-a-real-objective")
    # It parsed the sequence but refuses because a step is not registered.
    assert objs == ["implement-stub", "not-a-real-objective"]
    assert err is not None and "not-a-real-objective" in err
    assert "unknown objective" in err


def test_parse_chain_all_known_ok():
    objs, err = _parse_chain("implement-stub,cover-gaps,strengthen-tests")
    assert err is None
    assert objs == ["implement-stub", "cover-gaps", "strengthen-tests"]


# --------------------------------------------------------------------------- #
# --chain routing → run_chain (spied)                                          #
# --------------------------------------------------------------------------- #
def _spy_run_chain(monkeypatch) -> dict:
    """Replace ``run_chain`` with a spy that records its args and returns a
    sentinel green report; keep the renderer real (it is pure)."""
    seen: dict = {}

    def _fake(project_root, objectives, **kw):
        seen["project_root"] = str(project_root)
        seen["objectives"] = list(objectives)
        seen["kwargs"] = kw
        return ChainReport(objectives=list(objectives))

    monkeypatch.setattr("app.engine.chain_compiler.run_chain", _fake)
    return seen


def test_chain_flag_invokes_run_chain_with_parsed_sequence(tmp_path, monkeypatch, capsys):
    seen = _spy_run_chain(monkeypatch)
    rc = cmd_develop(_ns(tmp_path, chain="implement-stub,cover-gaps", json=False))
    assert rc == 0
    # The parsed, ordered sequence was handed VERBATIM to the engine.
    assert seen["objectives"] == ["implement-stub", "cover-gaps"]
    assert seen["project_root"] == str(tmp_path)
    # The chain report was rendered (the engine's own renderer, kept real).
    out = capsys.readouterr().out
    assert "Develop chain" in out
    assert "implement-stub → cover-gaps" in out


def test_chain_flag_threads_apply_and_fast(tmp_path, monkeypatch):
    seen = _spy_run_chain(monkeypatch)
    cmd_develop(_ns(tmp_path, chain="implement-stub", apply=True, fast=True,
                    max_steps=7, no_verify=False))
    kw = seen["kwargs"]
    assert kw["apply"] is True
    assert kw["fast"] is True
    assert kw["verify"] is True  # not --no-verify
    assert kw["max_steps"] == 7
    assert kw["halt_on_unmet_precondition"] is False


def test_chain_halt_on_unmet_flag_threads_through(tmp_path, monkeypatch):
    seen = _spy_run_chain(monkeypatch)
    cmd_develop(_ns(tmp_path, chain="cover-gaps,strengthen-tests",
                    halt_on_unmet=True))
    assert seen["kwargs"]["halt_on_unmet_precondition"] is True


def test_chain_malformed_refuses_before_engine_call(tmp_path, monkeypatch, capsys):
    """A malformed --chain must exit non-zero WITHOUT ever calling the engine."""
    called: list[int] = []

    def _boom(*a, **k):
        called.append(1)
        raise AssertionError("run_chain must not run on a malformed chain")

    monkeypatch.setattr("app.engine.chain_compiler.run_chain", _boom)
    rc = cmd_develop(_ns(tmp_path, chain="implement-stub,bogus-objective", json=False))
    assert rc == 2
    assert called == []  # engine never invoked
    err = capsys.readouterr().err
    assert "bogus-objective" in err


def test_chain_empty_value_falls_through_to_default_objective(tmp_path, monkeypatch):
    """`--chain ""` (empty) is byte-identically a bare develop — it must NOT enter
    the chain path but fall through to the default single-objective campaign."""
    calls: list[str] = []

    def _chain_stub(*a, **k):
        calls.append("chain")
        return 0

    def _obj_stub(args, target, objective, grade_before, max_steps, verify, apply):
        calls.append(f"objective:{objective}")
        return 0

    monkeypatch.setattr(m, "_develop_chain", _chain_stub)
    monkeypatch.setattr(m, "_develop_objective", _obj_stub)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path, chain=""))
    assert rc == 0
    assert calls == ["objective:dead-params"]  # NOT the chain path


def test_chain_halted_report_exits_nonzero(tmp_path, monkeypatch):
    """A chain the engine reports as HALTED (a rolled-back red step) exits 1 —
    an honest, never-faked failure the caller/CI notices."""
    def _halted(project_root, objectives, **kw):
        r = ChainReport(objectives=list(objectives))
        r.halted = True
        r.halt_reason = "`x`: a move rolled back"
        return r

    monkeypatch.setattr("app.engine.chain_compiler.run_chain", _halted)
    rc = cmd_develop(_ns(tmp_path, chain="implement-stub,sort-imports", json=False))
    assert rc == 1


# --------------------------------------------------------------------------- #
# --goal X --atomic routing → orchestrate_goal (spied)                         #
# --------------------------------------------------------------------------- #
def _spy_orchestrate(monkeypatch, landing: GoalLanding) -> dict:
    seen: dict = {}

    def _fake(project_root, goal, **kw):
        seen["project_root"] = str(project_root)
        seen["goal"] = goal
        seen["kwargs"] = kw
        return landing

    monkeypatch.setattr("app.engine.project_goal_orchestrator.orchestrate_goal", _fake)
    return seen


def test_goal_atomic_routes_to_orchestrator_not_compile_goal(tmp_path, monkeypatch):
    """`--goal X --atomic` must reach the ORCHESTRATOR, never the per-leaf
    ``_develop_goal`` (compile_goal) path."""
    calls: list[str] = []

    def _goal_stub(*a, **k):
        calls.append("compile_goal")
        return 0

    monkeypatch.setattr(m, "_develop_goal", _goal_stub)
    landing = GoalLanding(goal="ship-value", objectives=["implement-stub",
                                                         "wire-exports"])
    seen = _spy_orchestrate(monkeypatch, landing)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path, goal="ship-value", atomic=True, json=False))
    assert rc == 0
    assert calls == []  # the per-leaf path was NOT taken
    assert seen["goal"] == "ship-value"
    assert seen["project_root"] == str(tmp_path)


def test_goal_without_atomic_uses_compile_goal_path(tmp_path, monkeypatch):
    """`--goal X` (no --atomic) is byte-identical: it routes to the existing
    per-leaf ``_develop_goal`` path, never the orchestrator."""
    calls: list[str] = []

    def _goal_stub(args, target, goal, max_steps, verify, apply):
        calls.append(f"compile_goal:{goal}")
        return 0

    def _atomic_boom(*a, **k):
        raise AssertionError("orchestrate path must not run without --atomic")

    monkeypatch.setattr(m, "_develop_goal", _goal_stub)
    monkeypatch.setattr(m, "_develop_goal_atomic", _atomic_boom)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path, goal="tidy", atomic=False))
    assert rc == 0 and calls == ["compile_goal:tidy"]


def test_goal_atomic_threads_apply_and_value_led(tmp_path, monkeypatch):
    landing = GoalLanding(goal="ship-value", objectives=["implement-stub",
                                                         "wire-exports"])
    seen = _spy_orchestrate(monkeypatch, landing)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    cmd_develop(_ns(tmp_path, goal="ship-value", atomic=True, apply=True,
                    no_verify=False, value_led=True))
    kw = seen["kwargs"]
    assert kw["apply"] is True
    assert kw["verify"] is True
    assert kw["value_led"] is True


def test_goal_atomic_renders_landing_report(tmp_path, monkeypatch, capsys):
    landing = GoalLanding(goal="ship-value",
                          objectives=["implement-stub", "wire-exports"])
    landing.applied = True
    landing.verified = True
    landing.files_changed = ["app/s.py", "app/__init__.py"]
    _spy_orchestrate(monkeypatch, landing)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    cmd_develop(_ns(tmp_path, goal="ship-value", atomic=True, json=False))
    out = capsys.readouterr().out
    assert "Project-goal orchestration" in out
    assert "ONE atomic goal" in out


def test_goal_atomic_unknown_goal_exits_nonzero(tmp_path, monkeypatch):
    landing = GoalLanding(goal="no-such-goal")
    landing.refused = True
    landing.reason = "unknown goal 'no-such-goal' — decomposes to nothing"
    _spy_orchestrate(monkeypatch, landing)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path, goal="no-such-goal", atomic=True, json=False))
    assert rc == 1


def test_goal_atomic_rolled_back_exits_nonzero(tmp_path, monkeypatch):
    landing = GoalLanding(goal="ship-value",
                          objectives=["implement-stub", "wire-exports"])
    landing.rolled_back = True
    landing.reason = "the composed plan regressed the suite"
    _spy_orchestrate(monkeypatch, landing)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path, goal="ship-value", atomic=True, json=False))
    assert rc == 1


def test_goal_atomic_honest_refusal_nothing_to_compose_exits_zero(tmp_path, monkeypatch):
    """A goal that resolved but had <2 landable leaves is an HONEST refusal that
    lands nothing — not a usage error, so it exits 0."""
    landing = GoalLanding(goal="tidy", objectives=["modernize"])
    landing.refused = True
    landing.reason = "fewer than two leaves produced a landable plan"
    _spy_orchestrate(monkeypatch, landing)
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path, goal="tidy", atomic=True, json=False))
    assert rc == 0


# --------------------------------------------------------------------------- #
# bare develop dispatch is BYTE-IDENTICAL (new flags default off)              #
# --------------------------------------------------------------------------- #
def test_bare_develop_dispatch_unchanged(tmp_path, monkeypatch):
    """With every new flag off, cmd_develop reaches EXACTLY the default
    single-objective helper and neither new engine handler — byte-identical."""
    calls: list[str] = []

    def _obj(args, target, objective, grade_before, max_steps, verify, apply):
        calls.append(f"objective:{objective}")
        return 0

    def _boom(name):
        def _f(*a, **k):
            raise AssertionError(f"{name} must not run for a bare develop")
        return _f

    monkeypatch.setattr(m, "_develop_objective", _obj)
    monkeypatch.setattr(m, "_develop_chain", _boom("_develop_chain"))
    monkeypatch.setattr(m, "_develop_goal_atomic", _boom("_develop_goal_atomic"))
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    rc = cmd_develop(_ns(tmp_path))
    assert rc == 0 and calls == ["objective:dead-params"]
