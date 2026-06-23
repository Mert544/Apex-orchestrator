"""ITEM 5 — within-run blocked-set memory in the climb.

ascend()'s round loop used to re-rank an objective whose every candidate blocked
straight back to the top each round, re-paying its (expensive) compile_objective
scan that already proved it cannot progress. The fix carries a per-run in-memory
``blocked_run`` set: an objective that lands NOTHING this round (moves == 0) is
remembered and excluded from later rounds' ranking via ``rank_objectives(...,
exclude=blocked_run)``.

These deterministic witnesses pin the contract:
  * ``rank_objectives`` ``exclude`` drops the named objectives and ONLY those —
    ``None``/empty leave the board byte-identical (the default path is unchanged).
  * a blocked objective is not re-passed to ``compile_objective`` in round 2
    (a call-count proof, with ``compile_objective`` monkeypatched).
  * a climb where nothing blocks is unchanged (every round still scans its move).
  * ``blocked_run`` is per-run: it resets across two separate ``ascend()`` calls.
"""

from __future__ import annotations

import app.engine.ascend as asc
from app.engine.ascend import rank_objectives


def _fake_board(monkeypatch, fitness: dict[str, float]) -> None:
    """Register ``fitness``'s objectives as the whole board with constant pending,
    and silence the learned/dreamed signals so ranking is pure pending order."""
    monkeypatch.setattr(asc, "payoff_weights", lambda r: {})
    monkeypatch.setattr(asc, "land_factors", lambda r: {})
    monkeypatch.setattr(asc, "available_objectives", lambda: list(fitness))

    def fake_map():
        return {name: (lambda r, p=pending: p, lambda r: []) for name, pending in fitness.items()}

    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)


# --- rank_objectives exclude ---------------------------------------------------

def test_rank_objectives_exclude_drops_named(tmp_path, monkeypatch):
    _fake_board(monkeypatch, {"alpha": 9.0, "beta": 5.0, "gamma": 3.0})
    names = ["alpha", "beta", "gamma"]

    full = [r.objective for r in rank_objectives(str(tmp_path), names)]
    assert full == ["alpha", "beta", "gamma"]  # pure pending order

    # Excluding the worst drops ONLY it; the survivors keep their relative order.
    dropped = [r.objective for r in rank_objectives(str(tmp_path), names, exclude={"alpha"})]
    assert dropped == ["beta", "gamma"]


def test_rank_objectives_exclude_none_and_empty_are_identical(tmp_path, monkeypatch):
    # exclude=None (the default) and an empty set both leave the board untouched —
    # byte-identical name list AND order to the no-exclude call.
    _fake_board(monkeypatch, {"alpha": 9.0, "beta": 5.0, "gamma": 3.0})
    names = ["alpha", "beta", "gamma"]

    default = [(r.objective, r.priority) for r in rank_objectives(str(tmp_path), names)]
    explicit_none = [(r.objective, r.priority)
                     for r in rank_objectives(str(tmp_path), names, exclude=None)]
    empty = [(r.objective, r.priority)
             for r in rank_objectives(str(tmp_path), names, exclude=set())]
    assert default == explicit_none == empty


def test_rank_objectives_exclude_unknown_name_is_noop(tmp_path, monkeypatch):
    # Excluding a name that is not on the board changes nothing.
    _fake_board(monkeypatch, {"alpha": 9.0, "beta": 5.0})
    names = ["alpha", "beta"]
    base = [r.objective for r in rank_objectives(str(tmp_path), names)]
    excl = [r.objective for r in rank_objectives(str(tmp_path), names, exclude={"not-real"})]
    assert base == excl == ["alpha", "beta"]


# --- the climb stops re-scanning a proven blocker -----------------------------

def test_blocked_objective_not_rescanned_next_round(tmp_path, monkeypatch):
    """``blocker`` blocks every candidate (0 moves) while ``mover`` always lands a
    move. Round 1 ranks blocker first (more pending) and scans BOTH; round 2 must
    exclude blocker (it landed nothing) and so scan ONLY mover again. The proof is
    the per-objective compile_objective call count: blocker exactly once across
    the whole climb, mover once per round."""
    _fake_board(monkeypatch, {"blocker": 10.0, "mover": 5.0})
    monkeypatch.setattr(asc, "_grade", lambda r: 90)  # constant grade

    calls: dict[str, int] = {}

    class _Campaign:
        def __init__(self, steps):
            self.steps = steps

    def fake_compile(project_root, *, objective, **kw):
        calls[objective] = calls.get(objective, 0) + 1
        # blocker can never move; mover always lands exactly one verified move.
        return _Campaign([] if objective == "blocker" else [object()])

    monkeypatch.setattr(asc, "compile_objective", fake_compile)

    report = asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=2)

    assert calls["blocker"] == 1   # scanned once, then remembered & excluded
    assert calls["mover"] == 2     # mover still scanned every round
    # Both rounds landed mover; the climb never spent a second blocker scan.
    assert [r.objective for r in report.rounds] == ["mover", "mover"]


def test_no_blocker_climb_is_unchanged(tmp_path, monkeypatch):
    """When nothing blocks, blocked_run stays empty and the climb behaves exactly
    as before: the single worst objective is developed every round, scanned once
    per round, and never excluded."""
    _fake_board(monkeypatch, {"mover": 4.0})
    monkeypatch.setattr(asc, "_grade", lambda r: 90)

    calls = {"n": 0}

    class _Campaign:
        steps = [object()]

    def fake_compile(project_root, *, objective, **kw):
        calls["n"] += 1
        assert objective == "mover"
        return _Campaign()

    monkeypatch.setattr(asc, "compile_objective", fake_compile)

    report = asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=3)
    assert calls["n"] == 3                      # one scan per round, no exclusions
    assert len(report.rounds) == 3
    assert all(r.objective == "mover" for r in report.rounds)


def test_blocked_run_resets_across_ascend_calls(tmp_path, monkeypatch):
    """blocked_run is per-run in-memory state, fresh on every ascend() call. A
    blocker excluded in one climb is scanned AGAIN at the start of the next climb
    — the memory never persists across calls."""
    _fake_board(monkeypatch, {"blocker": 10.0, "mover": 5.0})
    monkeypatch.setattr(asc, "_grade", lambda r: 90)

    calls: dict[str, int] = {}

    class _Campaign:
        def __init__(self, steps):
            self.steps = steps

    def fake_compile(project_root, *, objective, **kw):
        calls[objective] = calls.get(objective, 0) + 1
        return _Campaign([] if objective == "blocker" else [object()])

    monkeypatch.setattr(asc, "compile_objective", fake_compile)

    asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=2)
    assert calls["blocker"] == 1   # first climb scans blocker once

    asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=2)
    # The second climb starts with a FRESH blocked set, so blocker is scanned
    # once more (round 1) before being re-remembered → 2 total, not 1.
    assert calls["blocker"] == 2


def test_all_candidates_blocked_is_a_fixpoint(tmp_path, monkeypatch):
    """If every ranked objective blocks in round 1, the climb declares a fixpoint
    (no round recorded) — the blocked set is irrelevant to the outcome here, but
    this pins that the extracted helper still returns None → forced fixpoint."""
    _fake_board(monkeypatch, {"blocker": 10.0})
    monkeypatch.setattr(asc, "_grade", lambda r: 90)

    class _Campaign:
        steps: list = []

    monkeypatch.setattr(asc, "compile_objective", lambda *a, **k: _Campaign())

    report = asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    assert report.fixpoint is True
    assert report.rounds == []
