"""RU-1: CLI wiring of the DORMANT value-led + min-move-value capabilities onto
`apex develop`.

The ENGINE already supports both (``value_led`` in
``app.engine.fractal_develop.compile_goal`` and ``min_move_value`` in
``app.engine.objective_compiler.compile_objective``); only the CLI flags were
missing. These tests pin the WIRING:

  - ``--value-led`` routes ``value_led=True`` into ``compile_goal`` (and a real
    tmp-repo end-to-end where it reorders the higher-buyer-value concrete
    objective ahead of the lower one).
  - ``--min-value 0.5`` routes ``min_move_value=0.5`` into ``compile_objective``
    (and into the ``--auto`` sweep, which is ``compile_objective``-backed).
  - The DEFAULT (no flags) path is byte-identical to today: ``value_led`` stays
    ``False`` and ``min_move_value`` stays the engine default ``0.0`` (the CLI's
    ``None`` maps to ``0.0``), so omitting the flags reorders/refuses nothing.

Style follows tests/test_cli_autonomy_dispatch_characterization.py: build an
``argparse.Namespace``, monkeypatch the underlying compile fn to a sentinel that
captures the routed kwargs, invoke the helper, and assert. No real pytest
subprocess is spawned (``no_verify=True`` / ``verify=False``); no
time/random/order asserts beyond the deterministic, hashseed-invariant value-led
order the engine already proves.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import (
    _develop_auto,
    _develop_goal,
    _develop_objective,
    _min_move_value,
    register_parsers,
)
from app.engine.fractal_develop import compile_goal


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _parser() -> argparse.ArgumentParser:
    """The develop subparser as the real CLI builds it (see
    tests/test_cli_autonomy_misc_internals.py::_parser)."""
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    register_parsers(sub)
    return p
def _dev_ns(tmp_path: Path, **over) -> argparse.Namespace:
    """A develop Namespace with the same default field-set the parser produces,
    including the two NEW flags at their OFF defaults (value_led=False,
    min_value=None)."""
    base = dict(
        target=str(tmp_path), objective="dead-params", goal="",
        all_objectives=False, auto=False, concrete=False, grade=False,
        history=False, from_dream=False, playbook=False, top=False, session=False,
        mode_word="", apply=False, max_steps=3, no_verify=True, fast=False,
        json=True, value_led=False, min_value=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _capture_compile_goal(monkeypatch) -> dict:
    """Replace ``compile_goal`` (as imported inside ``_develop_goal``) with a
    sentinel that records the kwargs it was called with."""
    seen: dict = {}

    def _fake(project_root, goal, **kw):
        seen["project_root"] = project_root
        seen["goal"] = goal
        seen.update(kw)
        return _StubGoalResult()

    monkeypatch.setattr("app.engine.fractal_develop.compile_goal", _fake)
    return seen


def _capture_compile_objective(monkeypatch) -> list[dict]:
    """Replace ``compile_objective`` (as imported inside the develop helpers)
    with a sentinel recording each call's kwargs."""
    calls: list[dict] = []

    def _fake(project_root, **kw):
        calls.append(dict(kw, project_root=project_root))
        return _StubCompileResult()

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective", _fake)
    return calls


class _StubGoalResult:
    objectives: list[str] = []
    total_moves = 0

    def to_dict(self) -> dict:
        return {"objectives": []}


class _StubCompileResult:
    steps: list = []
    fitness_start = 0
    applied = False
    blocked: list[str] = []

    def to_dict(self) -> dict:
        return {"steps": []}


def _stub_and_dataclass_project(tmp_path: Path) -> Path:
    """A project with BOTH a test-pinned fillable stub (implement-stub, buyer
    value 1.00) and a boilerplate __init__ class (dataclassify, 0.50). Mirrors
    the fixture in tests/test_fractal_develop.py so the value-led reorder is
    exercised end-to-end."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    (tmp_path / "app" / "pt.py").write_text(
        "class Point:\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n", encoding="utf-8")
    (tmp_path / "tests" / "test_pt.py").write_text(
        "from app.pt import Point\ndef test_pt():\n"
        "    p = Point(1, 2)\n    assert p.x == 1 and p.y == 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n",
                                             encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# the parser exposes the two flags with the documented OFF defaults            #
# --------------------------------------------------------------------------- #
def test_parser_defines_value_led_and_min_value_off_by_default():
    ns = _parser().parse_args(["develop"])
    assert ns.value_led is False        # store_true, unset
    assert ns.min_value is None         # explicit None default (maps to 0.0)


def test_parser_value_led_flag_sets_true():
    ns = _parser().parse_args(["develop", "--value-led"])
    assert ns.value_led is True


def test_parser_min_value_parses_float():
    ns = _parser().parse_args(["develop", "--min-value", "0.5"])
    assert ns.min_value == 0.5


# --------------------------------------------------------------------------- #
# --value-led -> compile_goal(value_led=True)                                  #
# --------------------------------------------------------------------------- #
def test_value_led_flag_routes_value_led_true_into_compile_goal(tmp_path, monkeypatch):
    seen = _capture_compile_goal(monkeypatch)
    rc = _develop_goal(_dev_ns(tmp_path, goal="ship-value", value_led=True),
                       tmp_path, "ship-value", 3, False, False)
    assert rc == 1  # stub goal-result has no objectives -> exit 1, fine for routing
    assert seen["value_led"] is True
    assert seen["goal"] == "ship-value"


def test_default_routes_value_led_false_into_compile_goal(tmp_path, monkeypatch):
    # No flag set: the byte-identical default the engine proves unchanged.
    seen = _capture_compile_goal(monkeypatch)
    _develop_goal(_dev_ns(tmp_path, goal="reduce-debt"),
                  tmp_path, "reduce-debt", 3, False, False)
    assert seen["value_led"] is False


def test_value_led_end_to_end_reorders_concrete_first(tmp_path):
    # Real engine (no monkeypatch): the CLI flag's effect is the same proven
    # reorder — implement-stub (1.00) is attempted ahead of dataclassify (0.50).
    _stub_and_dataclass_project(tmp_path)
    rc = _develop_goal(_dev_ns(tmp_path, goal="ship-value", value_led=True),
                       tmp_path, "ship-value", 1, False, False)
    assert rc == 0
    # Cross-check against the engine directly under the same args.
    gr = compile_goal(str(tmp_path), "ship-value", value_led=True, max_steps=1,
                      verify=False, apply=False)
    assert gr.objectives.index("implement-stub") < gr.objectives.index("dataclassify")


# --------------------------------------------------------------------------- #
# --min-value -> compile_objective(min_move_value=...)                         #
# --------------------------------------------------------------------------- #
def test_min_value_flag_routes_floor_into_compile_objective(tmp_path, monkeypatch):
    calls = _capture_compile_objective(monkeypatch)
    _develop_objective(_dev_ns(tmp_path, min_value=0.5),
                       tmp_path, "dead-params", None, 3, False, False)
    assert calls and calls[0]["min_move_value"] == 0.5


def test_default_min_value_routes_zero_floor_into_compile_objective(tmp_path, monkeypatch):
    # Unset --min-value (None) maps to the engine's byte-identical 0.0 default.
    calls = _capture_compile_objective(monkeypatch)
    _develop_objective(_dev_ns(tmp_path), tmp_path, "dead-params", None, 3, False, False)
    assert calls and calls[0]["min_move_value"] == 0.0


def test_min_value_flag_routes_into_auto_sweep(tmp_path, monkeypatch):
    # The --auto sweep is compile_objective-backed too, so --min-value reaches it.
    calls = _capture_compile_objective(monkeypatch)
    monkeypatch.setattr(m, "_auto_selected_objectives",
                        lambda target, concrete: ["dead-params"])
    _develop_auto(_dev_ns(tmp_path, auto=True, min_value=0.35),
                  tmp_path, None, 3, False, False)
    assert calls and calls[0]["min_move_value"] == 0.35


# --------------------------------------------------------------------------- #
# the None -> 0.0 floor mapping, in isolation                                  #
# --------------------------------------------------------------------------- #
def test_min_move_value_helper_maps_none_to_zero():
    assert _min_move_value(argparse.Namespace(min_value=None)) == 0.0


def test_min_move_value_helper_passes_through_float():
    assert _min_move_value(argparse.Namespace(min_value=0.42)) == 0.42


def test_min_move_value_helper_missing_attr_is_zero():
    # Defensive getattr default: a Namespace without the field is treated as off.
    assert _min_move_value(argparse.Namespace()) == 0.0
