"""Gap-closing tests for dream_landing's helper edges and defensive branches.

The existing dream_landing suites cover the live/stored derivation and the value
re-rank happy paths. This wave pins the remaining leaves cheaply (no real dream or
compiler campaign — all fast, deterministic unit exercises):

  * ``_confluence_key_module`` — a non-confluence key and a confluence naming a
    file that does not exist both yield "";
  * ``_live_confluence_modules`` — a dream that cannot even be imported/run names
    no confluence (returns [], never invents one);
  * ``dream_signal_weight`` — the per-module flat boost over an explicit module
    list and over an empty store (the refusal-safe {} default);
  * ``_module_landable_value`` — a sweep objective missing from the objectives map
    is skipped, and an objective whose move generator RAISES is skipped — neither
    crashes the value scan nor fabricates a score.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

import sys

import app.engine.dream_landing as dl
import app.engine.objective_compiler as oc
from app.engine.dream_landing import (
    DREAM_CONFLUENCE_BOOST,
    _confluence_key_module,
    _live_confluence_modules,
    dream_signal_weight,
)


# --- _confluence_key_module edges ----------------------------------------------

def test_non_confluence_key_yields_empty(tmp_path):
    # Not a confluence:<module> key -> "" (dropped), regardless of the root.
    assert _confluence_key_module("triple:a+b+c", str(tmp_path)) == ""
    assert _confluence_key_module("association:x", str(tmp_path)) == ""


def test_confluence_key_for_missing_file_yields_empty(tmp_path):
    # A confluence naming a file that does not exist under the root is stale -> "".
    assert _confluence_key_module("confluence:no_such_module.py", str(tmp_path)) == ""


def test_confluence_key_for_existing_file_yields_module(tmp_path):
    (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
    assert _confluence_key_module("confluence:real.py", str(tmp_path)) == "real.py"


# --- _live_confluence_modules: a dream that cannot run names nothing ------------

def test_live_confluence_modules_import_failure_returns_empty(tmp_path, monkeypatch):
    # If the dream engine cannot be imported/run, the live derivation invents no
    # confluence — it degrades to [] (never a fabricated module).
    monkeypatch.setitem(sys.modules, "app.engine.dream", None)
    assert _live_confluence_modules(str(tmp_path)) == []


# --- dream_signal_weight: flat boost, refusal-safe default ---------------------

def test_signal_weight_boosts_supplied_modules(tmp_path):
    # Each supplied module earns the flat positive constant; blanks are dropped.
    out = dream_signal_weight(str(tmp_path), modules=["a.py", "", "b.py"])
    assert out == {"a.py": DREAM_CONFLUENCE_BOOST, "b.py": DREAM_CONFLUENCE_BOOST}


def test_signal_weight_no_store_is_empty(tmp_path):
    # No persisted promotion store -> {} (the refusal-safe, zero-behaviour default).
    assert dream_signal_weight(str(tmp_path)) == {}


def test_signal_weight_empty_module_list_is_empty(tmp_path):
    assert dream_signal_weight(str(tmp_path), modules=[]) == {}


# --- _module_landable_value: defensive per-objective skips ----------------------

def test_landable_value_skips_objective_absent_from_map(tmp_path, monkeypatch):
    # A sweep objective that is not in the objectives map has no spec -> skipped,
    # so the value scan stays empty rather than raising a KeyError.
    monkeypatch.setattr(dl, "_dream_sweep_objectives",
                        lambda _root: ["objective-not-in-map-xyz"])
    assert dl._module_landable_value(str(tmp_path)) == {}


def test_landable_value_skips_objective_whose_generator_raises(tmp_path, monkeypatch):
    # An objective whose move generator blows up is skipped (best-effort), never
    # crashing the value scan and never crediting a phantom module.
    def _raise(_root):
        raise RuntimeError("cannot enumerate")

    monkeypatch.setattr(oc, "_objectives_map", lambda: {"boom-obj": (None, _raise)})
    monkeypatch.setattr(dl, "_dream_sweep_objectives", lambda _root: ["boom-obj"])
    assert dl._module_landable_value(str(tmp_path)) == {}
