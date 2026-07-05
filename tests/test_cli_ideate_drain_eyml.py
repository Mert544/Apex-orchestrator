"""`apex ideate --actions --apply --drain`: the CLI seam that reaches the bridge's
already-tested cascade-drain (re-detect only the changed files, re-apply to a
fixpoint through the SAME per-step gate + rollback) — plus the replan closure that
keeps every extra round scoped to the user's own --phase/--auto/synthesis choices.

These are CLI-wiring pins (the drain mechanism itself is proven in
tests/test_cascade_drain_eyml.py): the bridge methods are faked so each assertion
is about what `_ideate_action_plan` PASSES, and the one correctness-critical test
proves the replan closure re-plans with the user's phase/auto/synthesis preserved
(the bridge's own _default_replan drops them — a real scope-escape on round 2+).
"""

from __future__ import annotations

import argparse

import app.cli_ideate as ci
import app.engine.idea_permutation as ip
from app.engine.idea_action_bridge import IdeaActionBridge


class _FakeStep:
    def __init__(self, target: str, executable: bool = True) -> None:
        self.target = target
        self.executable = executable


class _FakePlan:
    def __init__(self, steps=None) -> None:
        self.steps = list(steps or [])


def _args(**ov) -> argparse.Namespace:
    base = dict(mode="supervised", draft=False, apply=True, prove=False,
                roadmap=False, phase=None, top=0, auto=False,
                max_apply=0, max_attempts=0, drain=False, max_rounds=8)
    base.update(ov)
    return argparse.Namespace(**base)


def _capture_apply(monkeypatch) -> dict:
    captured: dict = {}

    def fake_apply(self, plan, root, **kw):
        captured["kwargs"] = kw
        captured["plan"] = plan
        return {"applied": 0, "rolled_back": 0, "blocked": 0,
                "total_executable": 0, "results": []}

    monkeypatch.setattr(IdeaActionBridge, "apply_plan", fake_apply)
    return captured


# --- threading the drain / attempts kwargs ----------------------------------

def test_no_drain_passes_byte_identical_defaults(monkeypatch):
    cap = _capture_apply(monkeypatch)
    monkeypatch.setattr(IdeaActionBridge, "plan_tree",
                        lambda self, report, **kw: _FakePlan())
    ci._ideate_action_plan(_args(drain=False), object(), "/proj")
    kw = cap["kwargs"]
    assert kw["drain"] is False
    assert kw["replan"] is None          # bridge's own path stays engaged
    assert kw["max_rounds"] == 8
    assert kw["max_attempts"] is None    # 0 → off → None


def test_drain_passes_true_and_a_callable_replan(monkeypatch):
    cap = _capture_apply(monkeypatch)
    monkeypatch.setattr(IdeaActionBridge, "plan_tree",
                        lambda self, report, **kw: _FakePlan())
    ci._ideate_action_plan(_args(drain=True, max_rounds=3), object(), "/proj")
    kw = cap["kwargs"]
    assert kw["drain"] is True
    assert callable(kw["replan"])
    assert kw["max_rounds"] == 3


def test_max_attempts_threads_through(monkeypatch):
    cap = _capture_apply(monkeypatch)
    monkeypatch.setattr(IdeaActionBridge, "plan_tree",
                        lambda self, report, **kw: _FakePlan())
    ci._ideate_action_plan(_args(max_attempts=5), object(), "/proj")
    assert cap["kwargs"]["max_attempts"] == 5


def test_max_rounds_zero_is_preserved_not_coerced_to_default(monkeypatch):
    # An explicit --max-rounds 0 (no extra drain rounds) must reach the bridge as
    # 0, not be coerced to the default 8 by a truthiness fallback.
    cap = _capture_apply(monkeypatch)
    monkeypatch.setattr(IdeaActionBridge, "plan_tree",
                        lambda self, report, **kw: _FakePlan())
    ci._ideate_action_plan(_args(drain=True, max_rounds=0), object(), "/proj")
    assert cap["kwargs"]["max_rounds"] == 0


# --- the correctness-critical test: no scope escape on drain rounds ---------

def test_replan_closure_preserves_phase_auto_and_synthesis(monkeypatch):
    cap = _capture_apply(monkeypatch)
    roadmap_calls: list[dict] = []

    def fake_roadmap(self, report, **kw):
        roadmap_calls.append(kw)
        return _FakePlan([_FakeStep("a.py"), _FakeStep("b.py")])

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", fake_roadmap)
    # The closure re-runs the engine — fake it so no real analysis happens.
    monkeypatch.setattr(
        ip, "IdeaPermutationEngine",
        lambda project_root=None: type("E", (), {"run": lambda self: object()})())

    args = _args(drain=True, roadmap=True, phase="Stabilize", auto=True,
                 cover_gaps=True)
    ci._ideate_action_plan(args, object(), "/proj")

    replan = cap["kwargs"]["replan"]
    plan = replan(["a.py"])  # invoke it exactly as the drain loop would

    # The closure's re-plan (the last call) must carry the USER's choices —
    # NOT the bridge default's bare plan_tree with no phase/auto/synthesis.
    last = roadmap_calls[-1]
    assert last["phase"] == "Stabilize"
    assert last["auto"] is True
    assert last["cover_gaps"] is True
    # …and be narrowed (POSIX-normalized) to the changed set.
    assert [s.target for s in plan.steps] == ["a.py"]


def test_replan_closure_uses_plan_tree_when_not_roadmap(monkeypatch):
    cap = _capture_apply(monkeypatch)
    tree_calls: list[dict] = []

    def fake_tree(self, report, **kw):
        tree_calls.append(kw)
        return _FakePlan([_FakeStep("x.py")])

    monkeypatch.setattr(IdeaActionBridge, "plan_tree", fake_tree)
    monkeypatch.setattr(
        ip, "IdeaPermutationEngine",
        lambda project_root=None: type("E", (), {"run": lambda self: object()})())

    ci._ideate_action_plan(_args(drain=True, roadmap=False, auto=True), object(), "/proj")
    replan = cap["kwargs"]["replan"]
    plan = replan(["x.py"])
    assert tree_calls[-1]["auto"] is True
    assert [s.target for s in plan.steps] == ["x.py"]


# --- Part C surfacing (additive, only when armed) ---------------------------

def test_print_shows_drain_and_attempts_when_present(capsys):
    ci._print_apply_results({
        "mode": "supervised", "applied": 2, "rolled_back": 0, "blocked": 0,
        "total_executable": 2, "results": [],
        "drain_rounds": 3, "converged": True,
        "attempted": 5, "attempts_exhausted": False,
    })
    out = capsys.readouterr().out
    assert "drained 3 round(s) — converged" in out
    assert "5 apply attempt(s)" in out


def test_print_shows_stopped_and_exhausted(capsys):
    ci._print_apply_results({
        "mode": "supervised", "applied": 1, "rolled_back": 0, "blocked": 0,
        "total_executable": 1, "results": [],
        "drain_rounds": 8, "converged": False,
        "attempted": 9, "attempts_exhausted": True,
    })
    out = capsys.readouterr().out
    assert "stopped at max-rounds" in out
    assert "budget exhausted" in out


def test_print_hides_drain_and_attempts_when_absent(capsys):
    ci._print_apply_results({
        "mode": "supervised", "applied": 0, "rolled_back": 0, "blocked": 0,
        "total_executable": 0, "results": [],
    })
    out = capsys.readouterr().out
    assert "drained" not in out
    assert "apply attempt" not in out
