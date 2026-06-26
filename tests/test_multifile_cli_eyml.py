"""CLI wiring of the SHIPPED multi-file atomic landing primitive onto `apex develop`.

The composition primitive already exists and is tested end-to-end
(``app.execution.compose_plans.compose_plans`` +
``app.execution.multifile_landing.{plan_implement_and_wire,multifile_moves}``);
only a USER entry point was missing. These tests pin the WIRING of the new
``apex develop --multifile`` flag:

  - the parser exposes ``--multifile`` and it is OFF by default (off-by-default
    invariant: the bare ``apex develop`` namespace is unchanged);
  - ``cmd_develop`` dispatches to ``_develop_multifile`` ONLY when the flag is set,
    and the DEFAULT path still reaches ``_develop_objective`` (byte-identical
    routing — the new branch never fires unless opted in);
  - ``_develop_multifile`` runs ``multifile_moves(target)`` through the EXISTING
    compile loop (``run_moves``): a DRY RUN writes NOTHING, and ``--apply`` lands
    the composed implement-AND-wire change on a real tmp package (both files);
  - the engine helper ``run_moves`` drives a ready move list through the same gated
    loop without an objective registration (covering the empty-list edge too).

Style follows tests/test_develop_value_led_cli_eyml.py: build an
``argparse.Namespace`` (or parse real argv), monkeypatch the underlying fn to a
sentinel when only routing matters, and drive the real engine on a tmp repo when
the landing itself matters. ``no_verify``/``verify=False`` keeps the routing tests
from spawning pytest; the end-to-end apply test verifies through the impact-scoped
suite gate, exactly as the primitive's own tests do. No time/random asserts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import (
    _develop_multifile,
    cmd_develop,
    register_parsers,
)
from app.engine.objective_compiler import Move, run_moves


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _parser() -> argparse.ArgumentParser:
    """The develop subparser as the real CLI builds it."""
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    register_parsers(sub)
    return p


def _dev_ns(tmp_path: Path, **over) -> argparse.Namespace:
    """A develop Namespace with the parser's default field-set, including the NEW
    ``multifile`` flag at its OFF default."""
    base = dict(
        target=str(tmp_path), objective="dead-params", goal="",
        all_objectives=False, multifile=False, auto=False, concrete=False,
        grade=False, history=False, from_dream=False, deep=False, playbook=False,
        top=False, force=False, shield=False, session=False, mode_word="",
        apply=False, max_steps=3, no_verify=True, fast=False, json=True,
        value_led=False, min_value=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _pkg_project(tmp_path: Path) -> Path:
    """A tmp project with a package (``app/pkg``) holding a test-pinned fillable
    stub module and an EMPTY ``__init__.py`` waiting to be wired — the exact shape
    ``multifile_moves`` pairs (mirrors tests/test_multifile_landing_eyml.py)."""
    (tmp_path / "app" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.pkg.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# the parser exposes --multifile, OFF by default                              #
# --------------------------------------------------------------------------- #
def test_parser_defines_multifile_off_by_default():
    ns = _parser().parse_args(["develop"])
    assert ns.multifile is False  # store_true, unset


def test_parser_multifile_flag_sets_true():
    ns = _parser().parse_args(["develop", "--multifile"])
    assert ns.multifile is True


# --------------------------------------------------------------------------- #
# cmd_develop dispatch: --multifile routes to _develop_multifile; default not  #
# --------------------------------------------------------------------------- #
def test_cmd_develop_routes_multifile_to_helper(tmp_path, monkeypatch):
    seen: dict = {}

    def _spy(args, target, max_steps, verify, apply):
        seen["called"] = True
        seen["apply"] = apply
        return 0

    monkeypatch.setattr(m, "_develop_multifile", _spy)
    rc = cmd_develop(_dev_ns(tmp_path, multifile=True, apply=True))
    assert rc == 0
    assert seen.get("called") is True
    assert seen.get("apply") is True


def test_cmd_develop_default_does_not_reach_multifile(tmp_path, monkeypatch):
    # OFF-BY-DEFAULT: the bare develop path must never touch the multifile branch
    # — it falls through to the existing single-objective campaign, unchanged.
    monkeypatch.setattr(m, "_develop_multifile",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("multifile must not run by default")))
    objective_calls: list = []
    monkeypatch.setattr(m, "_develop_objective",
                        lambda *a, **k: objective_calls.append(a) or 0)
    rc = cmd_develop(_dev_ns(tmp_path))  # multifile=False
    assert rc == 0
    assert objective_calls  # the DEFAULT campaign path ran, not multifile


# --------------------------------------------------------------------------- #
# _develop_multifile: dry run lists moves but writes NOTHING                   #
# --------------------------------------------------------------------------- #
def test_multifile_dry_run_writes_nothing(tmp_path, capsys):
    _pkg_project(tmp_path)
    calc_before = (tmp_path / "app" / "pkg" / "calc.py").read_text()
    init_before = (tmp_path / "app" / "pkg" / "__init__.py").read_text()

    rc = _develop_multifile(_dev_ns(tmp_path, json=False), tmp_path,
                            max_steps=3, verify=False, apply=False)
    assert rc == 0

    # Nothing on disk changed — a dry run is preview-only.
    assert (tmp_path / "app" / "pkg" / "calc.py").read_text() == calc_before
    assert (tmp_path / "app" / "pkg" / "__init__.py").read_text() == init_before
    # The composed implement-and-wire move was surfaced as WOULD-apply.
    out = capsys.readouterr().out
    assert "multifile-landing" in out
    assert "would apply" in out
    assert "implement a tested stub" in out


def test_multifile_dry_run_json_lists_the_composed_move(tmp_path, capsys):
    _pkg_project(tmp_path)
    rc = _develop_multifile(_dev_ns(tmp_path, json=True), tmp_path,
                            max_steps=3, verify=False, apply=False)
    assert rc == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["objective"] == "multifile-landing"
    assert payload["applied"] is False
    # One pair (app/pkg/calc.py + its package) -> one composed implement-and-wire step.
    ops = [s["operator"] for s in payload["steps"]]
    assert "implement_and_wire" in ops


# --------------------------------------------------------------------------- #
# _develop_multifile --apply: lands the composed change on BOTH files          #
# --------------------------------------------------------------------------- #
def test_multifile_apply_lands_stub_and_export(tmp_path, capsys):
    _pkg_project(tmp_path)
    rc = _develop_multifile(_dev_ns(tmp_path, json=False, apply=True), tmp_path,
                            max_steps=3, verify=True, apply=True)
    assert rc == 0

    # BOTH halves landed atomically: the stub is filled AND its export is wired.
    calc = (tmp_path / "app" / "pkg" / "calc.py").read_text()
    assert "raise NotImplementedError" not in calc and "return a + b" in calc
    init = (tmp_path / "app" / "pkg" / "__init__.py").read_text()
    assert "from .calc import add" in init and '"add"' in init

    out = capsys.readouterr().out
    assert "Applied" in out
    # The applied-tree disclosure note fired (a real landing, not a dry run).
    assert "working tree" in out


# --------------------------------------------------------------------------- #
# run_moves engine helper: drives a ready move list; empty-list edge           #
# --------------------------------------------------------------------------- #
def test_run_moves_empty_list_is_a_clean_noop(tmp_path):
    _pkg_project(tmp_path)
    res = run_moves(str(tmp_path), [], label="multifile-landing", apply=True,
                    verify=False, scope_verify=True)
    assert res.objective == "multifile-landing"
    assert res.steps == []
    assert res.fitness_start == 0.0 and res.fitness_end == 0.0
    assert res.applied is True


def test_run_moves_dry_run_lists_a_refusing_move_as_blocked(tmp_path):
    # A move whose composed plan REFUSES (empty/blocked) must not be listed as a
    # would-apply step — run_moves surfaces it exactly as the compile loop does.
    _pkg_project(tmp_path)
    from app.execution.compose_plans import compose_plans
    from app.execution.cross_file_rename import RenamePlan

    def _refusing_plan() -> RenamePlan:
        a = RenamePlan(old="app/pkg/calc.py", new="x")
        a.blockers.append("unsynthesizable stub")
        b = RenamePlan(old="app/pkg/__init__.py", new="x")
        return compose_plans(a, b)  # refuses -> blockers set, no new_contents

    moves = [Move(operator="implement_and_wire", target="app/pkg/calc.py:x",
                  description="composed", build_plan=_refusing_plan)]
    res = run_moves(str(tmp_path), moves, label="multifile-landing", apply=False)
    assert res.steps == []          # nothing would land
    assert res.blocked              # the refusal is disclosed
