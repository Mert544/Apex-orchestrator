"""`apex develop --auto` — autonomously land everything-applicable, NO objective-naming.

The gap this pins: the concrete synthesis objectives are reachable today only by
NAMING them (``apex develop --objective X``). ``apex develop --all`` sweeps just
the six hardcoded ``ALL_OBJECTIVES``; the 40+ self-registering objectives
(modernize idioms, infer-type-hints, dataclassify, cover-gaps, the expensive
implement-stub / wire-exports / strengthen-tests, …) are NOT in any autonomous
``develop`` sweep. ``--auto`` closes that: it selects the objectives that carry
qualifying targets — by each objective's OWN fitness, the SAME fitness-ranked
board ``apex plan`` / ``apex ascend`` use (``rank_objectives``) — and runs each
through the EXISTING ``compile_objective`` loop (suite-gated, auto-rollback). It
REUSES the selection + landing + rendering machinery, reimplementing none of it.

Covers:
  * the autonomous path SELECTS (by fitness, not by name) and LANDS an applicable
    opt-in objective on a foreign fixture — verified, the suite green after, with
    a real diff (``== None`` -> ``is None``);
  * a project with NOTHING applicable is a clean no-op (no writes, rc 0);
  * the EXPENSIVE concrete objectives are OFF by default and only swept with
    ``--concrete`` (honest about cost — the buyer opts into pytest-running work);
  * ``--auto`` reuses ``compile_objective`` (does NOT reimplement landing);
  * the chosen objective set is SURFACED (per-objective breakdown) — never silent;
  * determinism: same start state -> byte-identical report;
  * existing ``cmd_develop`` flag behaviour is UNCHANGED (the new flag defaults off
    and routes nowhere when absent; the established flags still dispatch as before).

Mirrors the develop-session eyml fixtures and the cli_autonomy dispatch
characterization style (sub-mode helpers monkeypatched to sentinels to pin the
parent's routing without running a real engine).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import cmd_develop


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _modernizable_project(root: Path) -> Path:
    """A foreign package with an APPLICABLE cheap opt-in objective: a ``== None``
    idiom (``modernize``) covered by a PASSING test, so the autonomous sweep can
    select it by fitness and land it suite-verified. Exports already wired and the
    one module type-tame, so the landed work is the modernize move (deterministic)."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text(
        'from .util import is_missing\n\n__all__ = [\n    "is_missing",\n]\n',
        encoding="utf-8")
    (root / "pkg" / "util.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_util.py").write_text(
        "from pkg.util import is_missing\n"
        "def test_missing():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    return root


def _stub_project(root: Path) -> Path:
    """A foreign package whose only debt is an EXPENSIVE concrete objective: a
    ``NotImplementedError`` stub (implement-stub, flagged expensive) covered by a
    passing-once-implemented test. The autonomous sweep must SKIP it by default and
    only reach it with ``--concrete``."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text(
        'from .mathlib import add\n\n__all__ = [\n    "add",\n]\n', encoding="utf-8")
    (root / "pkg" / "mathlib.py").write_text(
        'def add(a, b):\n    """Return the sum of a and b."""\n'
        "    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_mathlib.py").write_text(
        "from pkg.mathlib import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    return root


def _auto_ns(target: Path, **over) -> argparse.Namespace:
    """A develop Namespace with --auto on by default (the full flag surface the
    parser produces, so cmd_develop's ``getattr`` reads all resolve)."""
    base = dict(
        target=str(target), objective="dead-params", goal="", auto=True,
        concrete=False, all_objectives=False, grade=False, history=False,
        from_dream=False, playbook=False, top=False, session=False, mode_word="",
        apply=False, max_steps=5, no_verify=False, fast=False, json=False)
    base.update(over)
    return argparse.Namespace(**base)


def _run(ns: argparse.Namespace) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_develop(ns)
    return rc, out.getvalue()


# --------------------------------------------------------------------------- #
# the autonomous path selects + lands an applicable objective, no naming       #
# --------------------------------------------------------------------------- #
def test_auto_lands_applicable_objective_without_naming_it(tmp_path: Path):
    _modernizable_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path, apply=True))

    assert rc == 0
    # NO objective named: the sweep selected `modernize` by its own fitness and
    # landed the real, verified change (== None -> is None).
    util = (tmp_path / "pkg" / "util.py").read_text()
    assert "value is None" in util and "== None" not in util
    # The combined report surfaces the landed, test-covered modernize move.
    assert "modernize" in out
    assert "tests pass (covered)" in out
    assert "Applied to your working tree" in out


def test_auto_suite_is_green_after_the_landed_move(tmp_path: Path):
    # Never-fake-green / suite-green-after: the per-move gate ran the covering test
    # and it passes after the modernize move. We confirm the suite is green at the
    # post-auto tree by running it directly (the move was suite-verified to land).
    _modernizable_project(tmp_path)
    _run(_auto_ns(tmp_path, apply=True))

    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(tmp_path), env={"PYTHONPATH": str(tmp_path), "PATH": ""},
        capture_output=True, text=True)
    assert proc.returncode == 0  # the suite is GREEN after the autonomous landing


def test_auto_json_emits_compile_results_with_landed_step(tmp_path: Path):
    _modernizable_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path, apply=True, json=True))
    assert rc == 0
    data = json.loads(out.strip())
    assert isinstance(data, list)
    modernize = next(r for r in data if r["objective"] == "modernize")
    assert modernize["moves_applied"] >= 1
    assert modernize["applied"] is True


def test_auto_dry_run_writes_nothing(tmp_path: Path):
    _modernizable_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path, apply=False))
    assert rc == 0
    # Dry run: the idiom is still present, nothing was written.
    assert "== None" in (tmp_path / "pkg" / "util.py").read_text()
    assert "Applied to your working tree" not in out


# --------------------------------------------------------------------------- #
# a project with nothing applicable is a clean no-op                           #
# --------------------------------------------------------------------------- #
def test_auto_clean_no_op_when_nothing_applicable(tmp_path: Path, monkeypatch):
    # When the fitness board reports NO objective with qualifying targets, the
    # autonomous sweep lands nothing, writes nothing, and exits 0 (the clean no-op).
    # We pin this on the selection contract: an empty selection -> empty sweep.
    _modernizable_project(tmp_path)
    before = (tmp_path / "pkg" / "util.py").read_text()
    monkeypatch.setattr(m, "_auto_selected_objectives", lambda target, concrete: [])

    rc, out = _run(_auto_ns(tmp_path, apply=True))
    assert rc == 0
    # Nothing selected -> nothing landed -> nothing written; the report says so.
    assert (tmp_path / "pkg" / "util.py").read_text() == before
    assert "Nothing to do" in out
    assert "Applied to your working tree" not in out


def test_auto_clean_no_op_compile_never_called_on_empty_selection(tmp_path: Path,
                                                                  monkeypatch):
    # The no-op must not even spin up the landing loop: with an empty selection,
    # compile_objective is never invoked.
    _modernizable_project(tmp_path)
    monkeypatch.setattr(m, "_auto_selected_objectives", lambda target, concrete: [])
    calls: list[str] = []
    monkeypatch.setattr(
        "app.engine.objective_compiler.compile_objective",
        lambda *a, **k: calls.append("compile") or None)

    rc, _out = _run(_auto_ns(tmp_path, apply=True))
    assert rc == 0 and calls == []


# --------------------------------------------------------------------------- #
# honesty about cost: expensive concrete objectives are opt-in via --concrete  #
# --------------------------------------------------------------------------- #
def test_expensive_objectives_excluded_by_default(tmp_path: Path):
    # implement-stub is flagged expensive: the DEFAULT autonomous selection must
    # NOT include it (no silent pytest-running work the user didn't ask for).
    _stub_project(tmp_path)
    default_sel = m._auto_selected_objectives(tmp_path, concrete=False)
    assert "implement-stub" not in default_sel


def test_concrete_flag_opts_in_the_expensive_objectives(tmp_path: Path):
    from app.engine.develop_registry import expensive_names

    _stub_project(tmp_path)
    concrete_sel = set(m._auto_selected_objectives(tmp_path, concrete=True))
    default_sel = set(m._auto_selected_objectives(tmp_path, concrete=False))
    # --concrete reaches implement-stub; the expensive set is exactly what default
    # excludes among the newly-available objectives.
    assert "implement-stub" in concrete_sel
    assert "implement-stub" not in default_sel
    assert (concrete_sel - default_sel) <= expensive_names()


def test_auto_concrete_lands_the_expensive_stub_objective(tmp_path: Path):
    # End-to-end: with --concrete the autonomous sweep lands the EXPENSIVE
    # implement-stub objective — real, working code, suite-verified.
    _stub_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path, apply=True, concrete=True))
    assert rc == 0
    math_src = (tmp_path / "pkg" / "mathlib.py").read_text()
    assert "raise NotImplementedError" not in math_src
    assert "return a + b" in math_src
    assert "implement-stub" in out


# --------------------------------------------------------------------------- #
# RANK 2: a resolved scope_module auto-unlocks the EXPENSIVE objectives — but   #
# ONLY on that one named module; the whole-project default stays byte-identical #
# --------------------------------------------------------------------------- #
def test_scope_module_unlocks_expensive_objectives(tmp_path: Path):
    # A narrowly-named, resolved scope is an explicit + bounded invitation: the
    # selector unlocks the expensive concrete objectives (implement-stub, …) on it
    # WITHOUT --concrete. This is what lets `apex assist "implement auth.py"` reach
    # implement-stub instead of honestly no-op'ing.
    _stub_project(tmp_path)
    scoped = m._auto_selected_objectives(tmp_path, concrete=False,
                                         scope_module="pkg/mathlib.py")
    assert "implement-stub" in scoped


def test_no_scope_module_keeps_expensive_excluded_byte_identical(tmp_path: Path):
    # The DEFAULT (whole-project, no named scope) is byte-identical: expensive
    # objectives stay excluded, and the selection equals the pre-fix 2-arg call.
    _stub_project(tmp_path)
    default_none = m._auto_selected_objectives(tmp_path, concrete=False,
                                               scope_module=None)
    default_2arg = m._auto_selected_objectives(tmp_path, concrete=False)
    assert "implement-stub" not in default_none
    assert default_none == default_2arg  # scope_module=None changes nothing


def test_select_for_sweep_threads_scope_module_only_when_named(tmp_path: Path):
    # _select_for_sweep unlocks expensive when a scope_module is threaded, and is
    # byte-identical to the 2-arg default when it is None (the fitness board order
    # and membership are unchanged for the broad sweep).
    _stub_project(tmp_path)
    scoped = m._select_for_sweep(tmp_path, False, False, "pkg/mathlib.py")
    default = m._select_for_sweep(tmp_path, False, False)
    assert "implement-stub" in scoped
    assert "implement-stub" not in default
    assert default == m._auto_selected_objectives(tmp_path, False)


def test_auto_scope_module_none_without_scope_attr(tmp_path: Path):
    # A develop namespace WITHOUT a scope attribute (every existing --auto call)
    # resolves to None — the sweep stays whole-project + byte-identical.
    ns = _auto_ns(tmp_path)  # no ``scope`` key
    assert m._auto_scope_module(ns, tmp_path) is None
    # An explicit empty scope is also None (no accidental whole-project narrowing).
    ns_empty = _auto_ns(tmp_path, scope="")
    assert m._auto_scope_module(ns_empty, tmp_path) is None


def test_auto_scope_module_resolves_named_target(tmp_path: Path):
    # A named-but-bare hint resolves to the real module path (unique-stem match),
    # exactly as `apex assist` resolves it.
    _stub_project(tmp_path)
    ns = _auto_ns(tmp_path, scope="mathlib")
    assert m._auto_scope_module(ns, tmp_path) == "pkg/mathlib.py"


def test_auto_scope_module_unknown_hint_falls_back_to_whole_project(tmp_path: Path):
    # An unknown/ambiguous hint resolves to None (safe whole-project sweep, never a
    # wrong-module scope) — the expensive unlock only fires on a REAL named module.
    _stub_project(tmp_path)
    ns = _auto_ns(tmp_path, scope="does_not_exist")
    assert m._auto_scope_module(ns, tmp_path) is None


def test_scoped_auto_sweep_lands_expensive_stub_without_concrete(tmp_path: Path):
    # END-TO-END: `apex develop --auto` pointed at ONE module (scope=mathlib) lands
    # the EXPENSIVE implement-stub WITHOUT --concrete — the reach fix, real verified
    # code — while WITHOUT a scope the same project no-ops on that stub (below).
    _stub_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path, apply=True, scope="mathlib"))
    assert rc == 0
    math_src = (tmp_path / "pkg" / "mathlib.py").read_text()
    assert "raise NotImplementedError" not in math_src
    assert "return a + b" in math_src
    assert "implement-stub" in out


def test_unscoped_auto_sweep_does_not_land_expensive_stub(tmp_path: Path):
    # The NEGATIVE half (proves the test is non-tautological): the SAME project
    # WITHOUT a named scope and WITHOUT --concrete never touches the expensive stub
    # — the byte-identical default reach is preserved.
    _stub_project(tmp_path)
    rc, _out = _run(_auto_ns(tmp_path, apply=True))
    assert rc == 0
    math_src = (tmp_path / "pkg" / "mathlib.py").read_text()
    assert "raise NotImplementedError" in math_src  # untouched — still a stub


def test_selection_is_fitness_grounded_only_pending(tmp_path: Path):
    # The selection is GROUNDED in each objective's own fitness: only objectives
    # with qualifying targets (pending > 0) are chosen, so the sweep never runs an
    # objective with nothing to do.
    from app.engine.ascend import rank_objectives

    _modernizable_project(tmp_path)
    selected = m._auto_selected_objectives(tmp_path, concrete=False)
    ranked = {r.objective: r.pending for r in rank_objectives(str(tmp_path))}
    assert "modernize" in selected
    assert all(ranked.get(o, 0.0) > 0 for o in selected)


# --------------------------------------------------------------------------- #
# reuse, not reimplement: --auto drives compile_objective                      #
# --------------------------------------------------------------------------- #
def test_auto_reuses_compile_objective_for_landing(tmp_path: Path, monkeypatch):
    # --auto must REUSE the existing guarded loop (compile_objective), never a
    # bespoke apply path. We pin that it is the engine the sweep calls, once per
    # selected objective, forwarding apply/verify.
    from app.engine.objective_compiler import CompileResult

    _modernizable_project(tmp_path)
    monkeypatch.setattr(m, "_auto_selected_objectives",
                        lambda target, concrete: ["modernize", "infer-type-hints"])
    seen: list[tuple] = []

    def spy(root, *, objective, max_steps, verify, apply, scope_verify=False, **kw):
        seen.append((objective, apply, verify))
        return CompileResult(objective=objective, fitness_start=1.0,
                             fitness_end=0.0, applied=apply)

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective", spy)
    rc, _out = _run(_auto_ns(tmp_path, apply=True))
    assert rc == 0
    assert [s[0] for s in seen] == ["modernize", "infer-type-hints"]
    assert all(s[1] is True and s[2] is True for s in seen)  # apply + verify forwarded


def test_auto_fast_forwards_scope_verify(tmp_path: Path, monkeypatch):
    # --fast forwards scope_verify=True to the reused loop (impact-scoped gating),
    # exactly as the other develop paths do.
    from app.engine.objective_compiler import CompileResult

    _modernizable_project(tmp_path)
    monkeypatch.setattr(m, "_auto_selected_objectives",
                        lambda target, concrete: ["modernize"])
    seen: list[bool] = []

    def spy(root, *, objective, max_steps, verify, apply, scope_verify=False, **kw):
        seen.append(scope_verify)
        return CompileResult(objective=objective, fitness_start=0.0,
                             fitness_end=0.0, applied=apply)

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective", spy)
    _run(_auto_ns(tmp_path, apply=True, fast=True))
    assert seen == [True]


# --------------------------------------------------------------------------- #
# determinism                                                                  #
# --------------------------------------------------------------------------- #
def test_auto_report_is_deterministic_byte_for_byte(tmp_path: Path):
    a = _modernizable_project(tmp_path / "a")
    b = _modernizable_project(tmp_path / "b")
    _rc_a, out_a = _run(_auto_ns(a, apply=True))
    _rc_b, out_b = _run(_auto_ns(b, apply=True))
    # Same start state -> byte-identical report (the applied-tree note and per-
    # objective breakdown carry no clock/random; paths differ only in the header).
    assert out_a.replace(str(a), "ROOT") == out_b.replace(str(b), "ROOT")


# --------------------------------------------------------------------------- #
# existing cmd_develop flag behaviour is UNCHANGED                             #
# --------------------------------------------------------------------------- #
def _route_develop(monkeypatch) -> list[str]:
    """Replace every cmd_develop sub-mode with a sentinel; return the call log.
    Mirrors tests/test_cli_autonomy_dispatch_characterization.py."""
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
    monkeypatch.setattr(m, "_develop_auto", _stub("auto", 0))
    monkeypatch.setattr(m, "_develop_all", _stub("all", 0))
    monkeypatch.setattr(m, "_develop_from_dream", _stub("from_dream", 0))
    monkeypatch.setattr(m, "_develop_objective", _stub("objective", 0))
    monkeypatch.setattr(m, "_develop_session", _stub("session", 0))
    monkeypatch.setattr(m, "_grade_score", lambda target: 50)
    return calls


def _dev_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), objective="dead-params", goal="", auto=False,
                concrete=False, all_objectives=False, grade=False, history=False,
                from_dream=False, playbook=False, top=False, session=False,
                mode_word="", apply=False, max_steps=3, no_verify=True, fast=False,
                json=True)
    base.update(over)
    return argparse.Namespace(**base)


def test_default_still_routes_to_objective_when_auto_absent(tmp_path, monkeypatch):
    # The established default path is UNCHANGED: with --auto off, a bare develop
    # still routes to the single-objective campaign.
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path))
    assert rc == 0 and calls == ["objective"]


def test_all_still_routes_to_all_when_auto_absent(tmp_path, monkeypatch):
    # --all is unaffected by the new flag.
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True))
    assert rc == 0 and calls == ["all"]


def test_auto_routes_to_auto(tmp_path, monkeypatch):
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, auto=True))
    assert rc == 0 and calls == ["auto"]


def test_goal_precedes_auto(tmp_path, monkeypatch):
    # Dispatch order: a --goal still wins over --auto (goal is checked first), so a
    # user who names a goal is never silently diverted into the broad sweep.
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt", auto=True))
    assert rc == 0 and calls == ["goal"]


def test_auto_precedes_all_and_from_dream(tmp_path, monkeypatch):
    # When both --auto and --all/--from-dream are set, --auto wins (it is the
    # broader autonomous sweep); pinned so the order is load-bearing and stable.
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, auto=True, all_objectives=True,
                             from_dream=True))
    assert rc == 0 and calls == ["auto"]


def test_preview_modes_precede_auto(tmp_path, monkeypatch):
    # The read-only preview sub-modes (playbook/history/top) still short-circuit
    # before any campaign path, including --auto.
    calls = _route_develop(monkeypatch)
    assert cmd_develop(_dev_ns(tmp_path, playbook=True, auto=True)) == 0
    assert cmd_develop(_dev_ns(tmp_path, top=True, auto=True)) == 7
    assert calls == ["playbook", "top"]


def test_session_precedes_auto(tmp_path, monkeypatch):
    # `develop session` / --session is checked before the goal/auto fork, so it is
    # not diverted by --auto.
    calls = _route_develop(monkeypatch)
    rc = cmd_develop(_dev_ns(tmp_path, session=True, auto=True))
    assert rc == 0 and calls == ["session"]
