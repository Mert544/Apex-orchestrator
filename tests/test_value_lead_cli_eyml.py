"""CLI wiring of the opt-in ``--value-lead`` objective-board flag.

The ENGINE change lives in ``app.engine.ascend.rank_objectives`` (the new
``value_lead`` param re-weights the DEFAULT board by buyer value without unlocking
expensive objectives); these tests pin the CLI PLUMBING that exposes it:

  - ``apex plan --value-lead`` routes ``value_lead=True`` into ``rank_objectives``;
  - ``apex ascend --value-lead`` routes ``value_lead=True`` into ``ascend``;
  - ``apex develop --auto --value-lead`` routes it into ``_auto_selected_objectives``
    (and through to the board selection);
  - the DEFAULT (no flag) path routes ``value_lead=False`` everywhere — byte-identical
    to today;
  - on ``develop`` the NEW ``--value-lead`` (board re-weighting, ``dest=value_lead``)
    COEXISTS with the pre-existing ``--value-led`` (``--goal`` leaf ordering,
    ``dest=value_led``): the two distinct flags parse independently.

Style mirrors tests/test_develop_value_led_cli_eyml.py: build the real parser /
an ``argparse.Namespace``, monkeypatch the underlying callable to a sentinel that
captures the routed kwargs, invoke the handler, and assert. No real pytest
subprocess is spawned.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import cmd_ascend, cmd_plan, register_parsers


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    register_parsers(sub)
    return p


def _plan_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), goal="", concrete=False,
                value_lead=False, json=True)
    base.update(over)
    return argparse.Namespace(**base)


def _ascend_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), goal="", apply=False, max_rounds=4,
                max_steps=25, fast=False, until="", no_verify=True,
                concrete=False, value_lead=False, json=True)
    base.update(over)
    return argparse.Namespace(**base)


def _capture_rank(monkeypatch) -> dict:
    """Replace ``rank_objectives`` (as imported inside ``cmd_plan``) with a
    sentinel that records the kwargs it was called with."""
    seen: dict = {}

    def _fake(root, restrict=None, **kw):
        seen["root"] = root
        seen["restrict"] = restrict
        seen.update(kw)
        return []

    monkeypatch.setattr("app.engine.ascend.rank_objectives", _fake)
    monkeypatch.setattr("app.engine.ascend.render_plan_markdown",
                        lambda rankings: "# PLAN")
    return seen


def _capture_ascend(monkeypatch) -> dict:
    """Replace ``ascend`` (as imported inside ``cmd_ascend``) with a sentinel."""
    seen: dict = {}

    class _Rep:
        def to_dict(self) -> dict:
            return {}

    def _fake(root, **kw):
        seen["root"] = root
        seen.update(kw)
        return _Rep()

    monkeypatch.setattr("app.engine.ascend.ascend", _fake)
    monkeypatch.setattr("app.engine.ascend.render_ascend_markdown",
                        lambda report: "# ASCEND")
    return seen


# --------------------------------------------------------------------------- #
# the parser exposes --value-lead on plan / ascend / develop, OFF by default   #
# --------------------------------------------------------------------------- #
def test_plan_parser_defines_value_lead_off_by_default() -> None:
    assert _parser().parse_args(["plan"]).value_lead is False


def test_plan_parser_value_lead_sets_true() -> None:
    assert _parser().parse_args(["plan", "--value-lead"]).value_lead is True


def test_ascend_parser_defines_value_lead_off_by_default() -> None:
    assert _parser().parse_args(["ascend"]).value_lead is False


def test_ascend_parser_value_lead_sets_true() -> None:
    assert _parser().parse_args(["ascend", "--value-lead"]).value_lead is True


def test_develop_parser_defines_value_lead_off_by_default() -> None:
    assert _parser().parse_args(["develop"]).value_lead is False


def test_develop_parser_value_lead_sets_true() -> None:
    assert _parser().parse_args(["develop", "--auto", "--value-lead"]).value_lead is True


def test_develop_value_lead_and_value_led_coexist() -> None:
    # The NEW --value-lead (board, dest=value_lead) and the pre-existing --value-led
    # (--goal leaves, dest=value_led) are DISTINCT flags that parse independently —
    # no collision despite the one-letter spelling difference.
    led = _parser().parse_args(["develop", "--goal", "g", "--value-led"])
    assert led.value_led is True and led.value_lead is False
    lead = _parser().parse_args(["develop", "--auto", "--value-lead"])
    assert lead.value_lead is True and lead.value_led is False
    both = _parser().parse_args(["develop", "--value-led", "--value-lead"])
    assert both.value_led is True and both.value_lead is True


# --------------------------------------------------------------------------- #
# --value-lead -> rank_objectives(value_lead=True) on plan                     #
# --------------------------------------------------------------------------- #
def test_plan_value_lead_routes_true_into_rank_objectives(tmp_path, monkeypatch) -> None:
    seen = _capture_rank(monkeypatch)
    assert cmd_plan(_plan_ns(tmp_path, value_lead=True)) == 0
    assert seen["value_lead"] is True
    assert seen["include_expensive"] is False       # value_lead never implies concrete


def test_plan_default_routes_value_lead_false(tmp_path, monkeypatch) -> None:
    seen = _capture_rank(monkeypatch)
    assert cmd_plan(_plan_ns(tmp_path)) == 0
    assert seen["value_lead"] is False              # byte-identical default


# --------------------------------------------------------------------------- #
# --value-lead -> ascend(value_lead=True)                                      #
# --------------------------------------------------------------------------- #
def test_ascend_value_lead_routes_true_into_ascend(tmp_path, monkeypatch) -> None:
    seen = _capture_ascend(monkeypatch)
    assert cmd_ascend(_ascend_ns(tmp_path, value_lead=True)) == 0
    assert seen["value_lead"] is True
    assert seen["include_expensive"] is False


def test_ascend_default_routes_value_lead_false(tmp_path, monkeypatch) -> None:
    seen = _capture_ascend(monkeypatch)
    assert cmd_ascend(_ascend_ns(tmp_path)) == 0
    assert seen["value_lead"] is False


# --------------------------------------------------------------------------- #
# --value-lead -> _auto_selected_objectives(..., value_lead=True) on develop   #
# --------------------------------------------------------------------------- #
def test_develop_auto_value_lead_routes_into_board_selection(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    def _fake_select(target, concrete, value_lead=False):
        seen["concrete"] = concrete
        seen["value_lead"] = value_lead
        return []

    monkeypatch.setattr(m, "_auto_selected_objectives", _fake_select)
    ns = argparse.Namespace(target=str(tmp_path), concrete=False, value_lead=True,
                            allow_weak=False, fast=False, min_value=None, json=True)
    assert m._develop_auto(ns, tmp_path, None, 3, False, False) == 0
    assert seen["value_lead"] is True
    assert seen["concrete"] is False


def test_develop_auto_default_routes_value_lead_false(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    def _fake_select(target, concrete, value_lead=False):
        seen["value_lead"] = value_lead
        return []

    monkeypatch.setattr(m, "_auto_selected_objectives", _fake_select)
    ns = argparse.Namespace(target=str(tmp_path), concrete=False, value_lead=False,
                            allow_weak=False, fast=False, min_value=None, json=True)
    assert m._develop_auto(ns, tmp_path, None, 3, False, False) == 0
    assert seen["value_lead"] is False


def test_auto_selected_objectives_threads_value_lead(tmp_path, monkeypatch) -> None:
    # _auto_selected_objectives forwards value_lead into rank_objectives unchanged.
    seen: dict = {}

    class _R:
        objective = "harden"
        pending = 1.0

    def _fake(root, include_expensive=False, value_lead=False):
        seen["include_expensive"] = include_expensive
        seen["value_lead"] = value_lead
        return [_R()]

    monkeypatch.setattr("app.engine.ascend.rank_objectives", _fake)
    out = m._auto_selected_objectives(str(tmp_path), False, True)
    assert out == ["harden"]
    assert seen["value_lead"] is True
    assert seen["include_expensive"] is False
    # Default (no value_lead arg) stays False — byte-identical selection.
    seen.clear()
    m._auto_selected_objectives(str(tmp_path), False)
    assert seen["value_lead"] is False
