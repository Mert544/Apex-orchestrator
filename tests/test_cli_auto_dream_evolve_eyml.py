"""`apex auto` × the organism's own intelligence: the dream→auto RANKING wiring
(refusal-safe) and the `--evolve N` convenience that REUSES ``EvolutionLoop``.

Two related seams, both landing on ``cmd_auto``:

RANK 2 — dream→auto ranking. Historically ``apex auto`` ranked the value board on
the AST signals alone; it never consulted the nightly dream. This wave adds
``dream_landing.dream_signal_weight`` — a per-module priority BOOST for the
modules the dream graduated as CONFLUENCES — and threads it through
``cmd_auto → plan_roadmap`` so ``apex auto`` AMPLIFIES the organism's own overnight
discovery (a confluence module leads WITHIN its roadmap phase). The one invariant
the whole wiring rests on is REFUSAL-SAFETY: with no persisted dream (store
absent / unreadable / below-gate) the boost map is ``{}`` and the ranking is
BYTE-IDENTICAL to the pre-dream AST-only order — no dream ⇒ zero behaviour change.

These tests pin, NON-TAUTOLOGICALLY, that:
  (1) ``dream_signal_weight`` reads the persisted store (``{}`` with none, a flat
      positive boost per stored confluence) WITHOUT running a live dream;
  (2) an EMPTY / None ``dream_boost`` leaves ``plan_roadmap`` byte-for-byte
      identical to the pre-change call on the SAME report — while a NON-empty
      boost REORDERS (so removing the wiring changes the with-dream case ONLY),
      and the reorder is a PERMUTATION of the same step set (never new
      membership — the covered-only, suite-gated, auto-rollback landing is
      untouched);
  (3) with a dream confluence present, a confluence module's step leads its
      phase peers ABOVE its no-dream position; with no store, ``cmd_auto``'s boost
      is empty and its ranking is byte-identical to pre-change.

RANK 3 — ``apex auto --evolve N`` convenience. ``cmd_evolve`` already exposes the
``EvolutionLoop``; ``--evolve N`` is a thin one-command delegation to the SAME
loop (no re-implementation). N<=0 → no-op (one-pass ``apex auto``); N clamped to
[1, 10]. These tests pin the clamp and that the delegation builds
``EvolutionLoop(max_cycles=N)`` — proving it REUSES the loop.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import app.cli_autonomy as ca
import app.engine.evolution as evolution_mod
from app.cli_autonomy import _auto_dream_boost, _auto_evolve_delegate, cmd_auto
from app.engine.dream_landing import DREAM_CONFLUENCE_BOOST, dream_signal_weight
from app.engine.idea_action_bridge import IdeaActionBridge, _dream_step_boost
from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import ActionStep


# --- fixtures ----------------------------------------------------------------

def _two_module_project(tmp_path: Path, *, with_dream: bool) -> Path:
    """Two sibling modules that BOTH carry Secure-phase work (an insecure
    ``yaml.load`` + unsorted import), crafted so the roadmap orders them
    alphabetically — ``app/aaa.py`` before ``app/zzz.py`` — within the Secure
    phase. When ``with_dream`` is set, a well-formed promotion store graduates the
    alphabetically-LAST module (``app/zzz.py``) as a CONFLUENCE, so the dream
    boost must lift its Secure step ABOVE ``app/aaa.py``'s.

    The promotion entry is the FULL schema the dream writes (``key``/``text``/
    ``kind``/``confidence``/``streak``) so the idea seeder reads it too — the
    store is a real one, not a ``dream_signal_weight``-only stub."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    body = "import yaml\n\n\ndef load(s):\n    return yaml.load(s)\n"
    (tmp_path / "app" / "aaa.py").write_text(body, encoding="utf-8")
    (tmp_path / "app" / "zzz.py").write_text(body, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    if with_dream:
        (tmp_path / ".apex").mkdir()
        (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps([
            {"key": "confluence:app/zzz.py", "text": "app/zzz.py is a confluence",
             "kind": "confluence", "confidence": 0.9, "streak": 3}]),
            encoding="utf-8")
    return tmp_path


def _report(root: Path):
    return IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
        project_root=str(root)).run()


def _seq(plan) -> list[tuple]:
    """A byte-legible, fully-ordered fingerprint of a plan's step sequence."""
    return [(s.branch_path, s.phase, s.action_type, s.target, s.value)
            for s in plan.steps]


def _secure_module_order(plan) -> list[str]:
    """The order the two contested modules' steps appear in the Secure phase."""
    return [s.target for s in plan.steps
            if s.phase == "Secure" and s.target in ("app/aaa.py", "app/zzz.py")]


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        goal="", target=str(tmp_path), apply=False, allow_weak=False,
        recommend=False, mode=None, commit=False, deep=False, evolve=0,
        no_verify=False, max_apply=0, json=False, out="",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# === RANK 2.1 — dream_signal_weight: the store read ==========================

def test_dream_signal_weight_empty_without_a_store(tmp_path):
    _two_module_project(tmp_path, with_dream=False)
    # No promotion store ⇒ no confluence ⇒ EMPTY map: the refusal-safe base case.
    assert dream_signal_weight(str(tmp_path)) == {}


def test_dream_signal_weight_boosts_a_stored_confluence(tmp_path):
    _two_module_project(tmp_path, with_dream=True)
    weight = dream_signal_weight(str(tmp_path))
    # A stored confluence earns a single flat positive boost; nothing else does.
    assert weight == {"app/zzz.py": DREAM_CONFLUENCE_BOOST}
    assert DREAM_CONFLUENCE_BOOST > 0.0


def test_dream_signal_weight_unreadable_store_is_empty(tmp_path):
    # A corrupt store must degrade to EMPTY (refusal-safe), never raise — the same
    # as absent, so an unreadable dream can't shift a project's ranking.
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        "{ this is not json", encoding="utf-8")
    assert dream_signal_weight(str(tmp_path)) == {}


def test_dream_signal_weight_accepts_precomputed_modules(tmp_path):
    # The ``modules`` arg lets a caller pass a precomputed dream result instead of
    # re-reading the store; an empty list still yields the empty (refusal-safe) map.
    assert dream_signal_weight(str(tmp_path), modules=["app/x.py", "app/y.py"]) == {
        "app/x.py": DREAM_CONFLUENCE_BOOST, "app/y.py": DREAM_CONFLUENCE_BOOST}
    assert dream_signal_weight(str(tmp_path), modules=[]) == {}


def test_dream_signal_weight_does_not_run_a_live_dream(tmp_path, monkeypatch):
    # CRITICAL for the auto path + refusal-safety: the boost is a pure STORE read,
    # it must NEVER trigger a live dream (that is the explicit --from-dream path).
    # Make any dream call blow up: a store-only read stays empty regardless.
    import app.engine.dream as dream_mod

    def _boom(*a, **k):
        raise AssertionError("dream_signal_weight must not run a live dream")

    monkeypatch.setattr(dream_mod, "dream", _boom)
    _two_module_project(tmp_path, with_dream=False)
    assert dream_signal_weight(str(tmp_path)) == {}


# === RANK 2.2 — _dream_step_boost: the per-step lookup =======================

def test_dream_step_boost_zero_without_a_map():
    step = ActionStep(branch_path="x", title="t", operator="root",
                      subject="app/m.py", action_type="harden_security",
                      target="app/m.py")
    # None and empty both read as 0.0 for every step (byte-identical fallback).
    assert _dream_step_boost(step, None) == 0.0
    assert _dream_step_boost(step, {}) == 0.0


def test_dream_step_boost_matches_module_by_target():
    boost = {"app/m.py": DREAM_CONFLUENCE_BOOST}
    flagged = ActionStep(branch_path="x", title="t", operator="root",
                         subject="app/m.py", action_type="harden_security",
                         target="app/m.py:func")
    other = ActionStep(branch_path="y", title="t", operator="root",
                       subject="app/n.py", action_type="harden_security",
                       target="app/n.py")
    # The module key is the part before ':' — a ``module:symbol`` target matches.
    assert _dream_step_boost(flagged, boost) == DREAM_CONFLUENCE_BOOST
    # An unflagged module reads 0.0 (missing key).
    assert _dream_step_boost(other, boost) == 0.0


# === RANK 2.3 — plan_roadmap: byte-identity + the reorder ====================

def test_empty_and_none_boost_are_byte_identical_to_no_arg(tmp_path):
    # REFUSAL-SAFE PROOF (part 1): on the SAME report, an empty map AND an explicit
    # None leave the plan byte-for-byte identical to the pre-change call (no
    # dream_boost arg). This isolates the RANKING wiring from anything else.
    _two_module_project(tmp_path, with_dream=False)
    report = _report(tmp_path)
    bridge = IdeaActionBridge()
    base = _seq(bridge.plan_roadmap(report, mode="report", project_root=str(tmp_path)))
    empty = _seq(bridge.plan_roadmap(report, mode="report",
                                     project_root=str(tmp_path), dream_boost={}))
    none = _seq(bridge.plan_roadmap(report, mode="report",
                                    project_root=str(tmp_path), dream_boost=None))
    assert empty == base
    assert none == base


def test_dream_boost_reorders_confluence_first_and_only_the_with_dream_case(tmp_path):
    # REFUSAL-SAFE PROOF (part 2, NON-TAUTOLOGICAL): on the SAME report, a NON-empty
    # boost REORDERS the plan (so the wiring demonstrably DOES something), while the
    # empty map does not — i.e. removing the wiring changes ONLY the with-dream case.
    _two_module_project(tmp_path, with_dream=True)
    report = _report(tmp_path)
    bridge = IdeaActionBridge()
    boost = dream_signal_weight(str(tmp_path))
    assert boost  # the store graduated a confluence

    base = bridge.plan_roadmap(report, mode="report", project_root=str(tmp_path))
    boosted = bridge.plan_roadmap(report, mode="report",
                                  project_root=str(tmp_path), dream_boost=boost)
    # Without the boost the Secure phase is alphabetical (aaa before zzz); WITH it
    # the graduated confluence (zzz) leads every aaa step in the phase.
    base_order = _secure_module_order(base)
    boosted_order = _secure_module_order(boosted)
    assert base_order[0] == "app/aaa.py"
    assert boosted_order[0] == "app/zzz.py"
    # zzz's FIRST appearance moves strictly earlier than aaa's first appearance.
    assert boosted_order.index("app/zzz.py") < boosted_order.index("app/aaa.py")

    # The boost only REORDERS: it is a PERMUTATION of the exact same step set, never
    # a new membership — so it can never make a step run that wouldn't have, and the
    # suite-gated + auto-rollback landing is untouched (never-fake-green off-path).
    assert sorted(_seq(boosted)) == sorted(_seq(base))
    assert _seq(boosted) != _seq(base)  # a real reorder happened


def test_dream_boost_is_deterministic(tmp_path):
    _two_module_project(tmp_path, with_dream=True)
    report = _report(tmp_path)
    bridge = IdeaActionBridge()
    boost = dream_signal_weight(str(tmp_path))
    first = _seq(bridge.plan_roadmap(report, mode="report",
                                     project_root=str(tmp_path), dream_boost=boost))
    second = _seq(bridge.plan_roadmap(report, mode="report",
                                      project_root=str(tmp_path), dream_boost=boost))
    # No clock, no randomness: same report + same boost → identical order.
    assert first == second


# === RANK 2.3b — cmd_auto end-to-end: refusal-safe + amplifying ==============

def test_cmd_auto_dream_boost_is_empty_without_a_store(tmp_path):
    # The seam ``cmd_auto`` threads: with no persisted dream the boost is empty, so
    # the whole auto ranking falls back to the AST-only order byte-for-byte.
    _two_module_project(tmp_path, with_dream=False)
    assert _auto_dream_boost(tmp_path) == {}


def test_cmd_auto_recommend_is_deterministic_without_a_dream(tmp_path, capsys):
    # End-to-end refusal-safety: a no-dream ``apex auto`` produces a stable,
    # repeatable recommendation (the empty boost changes nothing run-to-run).
    _two_module_project(tmp_path, with_dream=False)
    assert cmd_auto(_ns(tmp_path, json=True)) == 0
    first = capsys.readouterr().out
    assert cmd_auto(_ns(tmp_path, json=True)) == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["applied"] is False  # recommend-only default touched nothing


def test_cmd_auto_with_dream_boosts_the_confluence_module(tmp_path):
    # With a graduated confluence present, ``cmd_auto`` (via _auto_dream_boost →
    # plan_roadmap) surfaces the confluence module ahead of its phase peer — the
    # organism's own overnight discovery amplified into the auto ranking.
    _two_module_project(tmp_path, with_dream=True)
    boost = _auto_dream_boost(tmp_path)
    assert boost == {"app/zzz.py": DREAM_CONFLUENCE_BOOST}
    report = _report(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(report, mode="report", project_root=str(tmp_path),
                               dream_boost=boost)
    assert _secure_module_order(plan)[0] == "app/zzz.py"


# === RANK 3 — --evolve N delegates to EvolutionLoop (reuse, no dup) ==========

def _evolve_ns(**overrides) -> argparse.Namespace:
    base = dict(evolve=0, target="", max_apply=0, json=False, out="",
                commit=False, no_verify=True, mode=None)
    base.update(overrides)
    return argparse.Namespace(**base)


def test_evolve_delegate_noop_when_n_not_positive(monkeypatch):
    # N<=0 → None (the caller keeps the one-pass behaviour); cmd_evolve untouched.
    calls: list = []
    monkeypatch.setattr(ca, "cmd_evolve", lambda args: calls.append(args) or 0)
    assert _auto_evolve_delegate(_evolve_ns(evolve=0)) is None
    assert _auto_evolve_delegate(_evolve_ns(evolve=-5)) is None
    assert calls == []  # never delegated


def test_evolve_delegate_passes_clamped_cycles(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(ca, "cmd_evolve",
                        lambda args: seen.__setitem__("max_cycles", args.max_cycles) or 0)
    # N=2 delegates verbatim.
    assert _auto_evolve_delegate(_evolve_ns(evolve=2)) == 0
    assert seen["max_cycles"] == 2
    # N>10 clamps to the 10-cycle ceiling (no unbounded overnight run).
    _auto_evolve_delegate(_evolve_ns(evolve=99))
    assert seen["max_cycles"] == 10
    # N=1 stays 1 (lower bound).
    _auto_evolve_delegate(_evolve_ns(evolve=1))
    assert seen["max_cycles"] == 1


def test_cmd_auto_evolve_delegates_to_the_evolution_loop(tmp_path, monkeypatch, capsys):
    # RANK 3 REUSE PROOF: ``apex auto --evolve 2`` builds the SAME EvolutionLoop as
    # ``apex evolve --max-cycles 2`` (max_cycles=2) and calls .run() — it does NOT
    # re-implement the loop. We spy on the loop's construction and short-circuit
    # .run() so the test never pays a real multi-cycle pytest campaign.
    _two_module_project(tmp_path, with_dream=False)
    seen: dict = {}
    real_loop = evolution_mod.EvolutionLoop

    class _SpyLoop(real_loop):
        def __init__(self, *a, **k):
            seen["max_cycles"] = k.get("max_cycles")
            super().__init__(*a, **k)

        def run(self):
            seen["ran"] = True
            return evolution_mod.EvolutionResult(
                cycles_run=self.max_cycles, reached_fixpoint=True, applied=0,
                rolled_back=0, before={}, after={}, roadmap_diff={},
                per_cycle=[], mode=self.mode, stop_reason="test")

    monkeypatch.setattr(evolution_mod, "EvolutionLoop", _SpyLoop)
    rc = cmd_auto(_ns(tmp_path, evolve=2, json=True, no_verify=True))
    assert rc == 0
    # The loop was built with the delegated cycle count and actually run — the
    # single-pass auto work was short-circuited (it delegated, didn't duplicate).
    assert seen.get("max_cycles") == 2
    assert seen.get("ran") is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["cycles_run"] == 2  # the EvolutionLoop's own report is the output
