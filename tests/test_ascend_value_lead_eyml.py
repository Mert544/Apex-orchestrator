"""value-lead — a value-aware DEFAULT objective board for cheap fixes (opt-in).

By default ``rank_objectives`` holds the buyer-value weight NEUTRAL at 1.0 on the
fast default board (it leads ONLY the ``--concrete`` board), so a high-pending
idiom tidy (``sort-imports`` value 0.18) outranks a cheap Tier-1 fix (``harden``
value 0.65) — buyer value is invisible where it costs the same to run. The opt-in
``value_lead`` flag widens the SAME value lens (``objective_value_weight``) onto
the default board so the cheap Tier-1 fix leads — WITHOUT pulling in the expensive
objectives (membership stays gated solely by ``include_expensive``).

This suite pins, mirroring tests/test_objective_value_planner_lead_eyml.py:
  - the default board (``value_lead=False`` AND ``include_expensive=False``) is
    byte-identical to before: every ``value_weight`` is exactly 1.0 and the order
    is pure pending-descending (the round-21 trust property);
  - ``value_lead=True`` on the CHEAP board re-weights it so a cheap Tier-1 fix
    leads a high-pending tidy (order flips ONLY with the flag);
  - the MANDATORY soundness trap: ``value_lead=True`` does NOT unlock an EXPENSIVE
    objective (``implement-stub`` stays filtered) — membership is gated SOLELY by
    ``include_expensive``, so the cheap board still runs ZERO pytest for selection;
  - monotonicity: value RE-WEIGHTS / breaks ties but NEVER overrides a strictly
    higher pending×weight (mirrors test_ascend_cost_tiebreak_eyml.py);
  - ``apex plan --json`` is byte-identical off-path (subprocess), plus determinism
    and PYTHONHASHSEED invariance on both paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import app.engine.ascend as asc
from app.engine.ascend import GoalRanking, rank_objectives


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _no_learning(monkeypatch) -> None:
    """Neutralise payoff/reliability so pending×value alone drives the score (a
    fresh project): this isolates the value lead from learned signals."""
    monkeypatch.setattr(asc, "payoff_weights", lambda root: {})
    monkeypatch.setattr(asc, "land_factors", lambda root: {})


def _fixture_project(tmp_path: Path) -> Path:
    """A minimal real project the subprocess ``apex plan`` can rank quickly."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _plan_json(target: Path, *args: str, seed: str | None = None) -> str:
    """Run ``apex plan --json`` (optionally with extra flags / a hash seed) and
    return its raw stdout — the exact bytes ``apex plan --json`` emits."""
    env = dict(os.environ)
    if seed is not None:
        env["PYTHONHASHSEED"] = seed
    res = subprocess.run(
        [sys.executable, "-m", "app.cli", "plan", "--json",
         "--target", str(target), *args],
        capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    return res.stdout


# --------------------------------------------------------------------------- #
# GoalRanking: value_lead changes NOTHING about the dataclass surface          #
# --------------------------------------------------------------------------- #
def test_value_lead_adds_no_field_and_default_weight_is_neutral() -> None:
    # value_lead is a rank_objectives flag, NOT a GoalRanking field — the manual
    # construction surface is untouched (mirrors test_objective_value_planner_lead).
    gr = GoalRanking("harden", 3.0, "harden")
    assert gr.value_weight == 1.0   # field default stays neutral
    assert gr.priority == 3.0       # pending-only, byte-identical
    assert "value_lead" not in gr.to_dict()


# --------------------------------------------------------------------------- #
# the default board (value_lead=False) is byte-identical — the off-path        #
# --------------------------------------------------------------------------- #
def test_default_board_harden_below_sort_imports_off_path(tmp_path: Path,
                                                          monkeypatch) -> None:
    # The exact off-path scenario from the brief: harden (pending 3, weight INERT
    # 1.0 -> priority 3) sits BELOW sort-imports (pending 5, weight inert 1.0 ->
    # priority 5). Buyer value is invisible without the flag — byte-identical to
    # today.
    _no_learning(monkeypatch)

    def fake_map():
        return {"harden": (lambda r: 3.0, lambda r: []),
                "sort-imports": (lambda r: 5.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["harden", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    ranked = rank_objectives(str(tmp_path))  # default board, value_lead off
    assert all(r.value_weight == 1.0 for r in ranked)
    assert [r.objective for r in ranked] == ["sort-imports", "harden"]
    assert round(ranked[0].priority, 3) == 5.0
    assert round(ranked[1].priority, 3) == 3.0


def test_default_board_every_value_weight_neutral_with_value_lead_off(
        tmp_path: Path, monkeypatch) -> None:
    # The change is PURELY ADDITIVE on the default path: value_lead defaulting off
    # leaves the board identical to a run with the weight stubbed to 1.0 — the
    # round-21 trust property, restated for the new flag.
    _no_learning(monkeypatch)

    def fake_map():
        return {"harden": (lambda r: 4.0, lambda r: []),
                "raise-from": (lambda r: 4.0, lambda r: []),
                "sort-imports": (lambda r: 6.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["harden", "raise-from", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    board = rank_objectives(str(tmp_path))  # value_lead off (default)
    assert all(r.value_weight == 1.0 for r in board)
    # sort-imports (6) leads; harden & raise-from tie on 4 -> registration order.
    assert [r.objective for r in board] == ["sort-imports", "harden", "raise-from"]

    # Stub the weight to 1.0 and turn the flag ON: identical, proving the default is
    # the same as a neutral-weight value-lead run (additivity).
    monkeypatch.setattr(asc, "objective_value_weight", lambda name: 1.0)
    stubbed = rank_objectives(str(tmp_path), value_lead=True)
    assert [r.objective for r in stubbed] == [r.objective for r in board]
    assert all(r.value_weight == 1.0 for r in stubbed)


# --------------------------------------------------------------------------- #
# value_lead=True on the CHEAP board re-weights it (order flips ONLY here)      #
# --------------------------------------------------------------------------- #
def test_value_lead_cheap_board_harden_leads_sort_imports(tmp_path: Path,
                                                          monkeypatch) -> None:
    # The brief's on-path: with value_lead the cheap Tier-1 harden
    # (3 * 0.65 = 1.95) LEADS the high-pending tidy sort-imports (5 * 0.18 = 0.90).
    # The SAME fixture as the off-path test — only the flag flips the order.
    _no_learning(monkeypatch)

    def fake_map():
        return {"harden": (lambda r: 3.0, lambda r: []),
                "sort-imports": (lambda r: 5.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["harden", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    ranked = rank_objectives(str(tmp_path), value_lead=True)
    assert ranked[0].objective == "harden"
    assert round(ranked[0].value_weight, 2) == 0.65
    assert round(ranked[0].priority, 3) == 1.95
    assert ranked[1].objective == "sort-imports"
    assert round(ranked[1].value_weight, 2) == 0.18
    assert round(ranked[1].priority, 3) == 0.9


def test_value_lead_uses_real_value_weights_no_concrete(tmp_path: Path,
                                                       monkeypatch) -> None:
    # value_lead pulls the REAL objective_value_weight onto the cheap board (NOT a
    # neutral 1.0) — for the actual cheap Tier-1 objectives harden/raise-from.
    _no_learning(monkeypatch)

    def fake_map():
        return {"harden": (lambda r: 1.0, lambda r: []),
                "raise-from": (lambda r: 1.0, lambda r: []),
                "sort-imports": (lambda r: 1.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives",
        lambda: ["sort-imports", "harden", "raise-from"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    ranked = rank_objectives(str(tmp_path), value_lead=True)
    # Equal pending (1.0 each) -> buyer value alone orders: harden 0.65 >
    # raise-from 0.64 > sort-imports 0.18 (sort-imports led under pending-only).
    assert [r.objective for r in ranked] == ["harden", "raise-from", "sort-imports"]
    assert round(ranked[0].value_weight, 2) == 0.65
    assert round(ranked[-1].value_weight, 2) == 0.18


# --------------------------------------------------------------------------- #
# THE MANDATORY SOUNDNESS TRAP: value_lead must NOT unlock expensive            #
# --------------------------------------------------------------------------- #
def test_value_lead_does_not_unlock_expensive_implement_stub(tmp_path: Path,
                                                            monkeypatch) -> None:
    # The line the auditor checks: an EXPENSIVE high-value objective
    # (implement-stub, value 1.00) is STILL FILTERED from the board under
    # value_lead=True — membership is gated SOLELY by include_expensive, value_lead
    # only RE-WEIGHTS what is already cheap. So value_lead adds ZERO new pytest.
    _no_learning(monkeypatch)

    def fake_map():
        return {"implement-stub": (lambda r: 9.0, lambda r: []),  # high-value, expensive
                "harden": (lambda r: 3.0, lambda r: []),
                "sort-imports": (lambda r: 5.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives",
        lambda: ["implement-stub", "harden", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"implement-stub"})

    ranked = rank_objectives(str(tmp_path), value_lead=True)
    names = [r.objective for r in ranked]
    assert "implement-stub" not in names           # STILL filtered — no unlock
    # The cheap board IS re-weighted: harden (3*0.65=1.95) leads sort-imports
    # (5*0.18=0.90) — value_lead works, without touching membership.
    assert names == ["harden", "sort-imports"]


def test_value_lead_membership_identical_to_default_board(tmp_path: Path,
                                                         monkeypatch) -> None:
    # MEMBERSHIP (the SET of objectives) is byte-identical between the default board
    # and the value_lead board — value_lead changes ORDER/weights only, never which
    # objectives appear. The expensive one is absent from BOTH.
    _no_learning(monkeypatch)

    def fake_map():
        return {"implement-stub": (lambda r: 9.0, lambda r: []),
                "harden": (lambda r: 3.0, lambda r: []),
                "raise-from": (lambda r: 2.0, lambda r: []),
                "sort-imports": (lambda r: 5.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives",
        lambda: ["implement-stub", "harden", "raise-from", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"implement-stub"})

    default = {r.objective for r in rank_objectives(str(tmp_path))}
    led = {r.objective for r in rank_objectives(str(tmp_path), value_lead=True)}
    assert default == led                          # same membership set
    assert "implement-stub" not in led             # expensive absent from both


def test_value_lead_with_concrete_still_includes_expensive(tmp_path: Path,
                                                          monkeypatch) -> None:
    # The two flags are orthogonal: include_expensive controls MEMBERSHIP, value_lead
    # controls (and here REDUNDANTLY shares) the value WEIGHT. With BOTH on, the
    # expensive objective is present (membership) AND value-weighted, exactly as the
    # --concrete board already behaves.
    _no_learning(monkeypatch)

    def fake_map():
        return {"implement-stub": (lambda r: 2.0, lambda r: []),
                "sort-imports": (lambda r: 5.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives", lambda: ["implement-stub", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"implement-stub"})

    ranked = rank_objectives(str(tmp_path), include_expensive=True, value_lead=True)
    names = [r.objective for r in ranked]
    assert "implement-stub" in names               # membership via include_expensive
    # implement-stub 2*1.00=2.0 leads sort-imports 5*0.18=0.90.
    assert names == ["implement-stub", "sort-imports"]


# --------------------------------------------------------------------------- #
# monotonicity: value RE-WEIGHTS / breaks ties, never overrides strictly-higher #
# --------------------------------------------------------------------------- #
def test_value_lead_never_overrides_strictly_higher_pending_weight(tmp_path: Path,
                                                                  monkeypatch) -> None:
    # A high-pending tidy whose pending×value still EXCEEDS a cheap Tier-1 fix keeps
    # the lead: value re-weights, it does not override a strictly-higher score
    # (mirrors test_ascend_cost_tiebreak_eyml.py's "never overrides priority").
    _no_learning(monkeypatch)

    # sort-imports: 20 * 0.18 = 3.6  vs  harden: 3 * 0.65 = 1.95 -> tidy still wins.
    def fake_map():
        return {"harden": (lambda r: 3.0, lambda r: []),
                "sort-imports": (lambda r: 20.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["harden", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    ranked = rank_objectives(str(tmp_path), value_lead=True)
    assert ranked[0].objective == "sort-imports"   # strictly higher pending×weight
    assert round(ranked[0].priority, 3) == 3.6
    assert ranked[1].objective == "harden"
    assert round(ranked[1].priority, 3) == 1.95


def test_value_lead_breaks_a_priority_tie_by_value(tmp_path: Path,
                                                  monkeypatch) -> None:
    # A genuine priority TIE on the value_lead board breaks toward the higher-value
    # objective via the -r.value_weight middle sort key (the same key the --concrete
    # board uses), not registration order.
    _no_learning(monkeypatch)

    # harden: 4 * 0.65 = 2.6  ;  sort-imports: pending tuned so 2.6 too.
    # 2.6 / 0.18 = 14.444...; use harden 0.65*4=2.6 and modernize 0.25 with pending
    # 10.4 -> 2.6, registered FIRST so only the value key can lift harden above it.
    def fake_map():
        return {"modernize": (lambda r: 10.4, lambda r: []),
                "harden": (lambda r: 4.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["modernize", "harden"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    ranked = rank_objectives(str(tmp_path), value_lead=True)
    assert round(ranked[0].priority, 6) == round(ranked[1].priority, 6)  # a tie
    assert ranked[0].objective == "harden"          # value key breaks it
    assert ranked[1].objective == "modernize"


# --------------------------------------------------------------------------- #
# determinism on both paths                                                    #
# --------------------------------------------------------------------------- #
def test_value_lead_board_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    _no_learning(monkeypatch)

    def fake_map():
        return {"harden": (lambda r: 3.0, lambda r: []),
                "raise-from": (lambda r: 4.0, lambda r: []),
                "sort-imports": (lambda r: 9.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives",
        lambda: ["harden", "raise-from", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: set())

    a = rank_objectives(str(tmp_path), value_lead=True)
    b = rank_objectives(str(tmp_path), value_lead=True)
    assert [r.objective for r in a] == [r.objective for r in b]
    assert [r.to_dict()["value_weight"] for r in a] == \
           [r.to_dict()["value_weight"] for r in b]


# --------------------------------------------------------------------------- #
# apex plan --json is byte-identical OFF-path (subprocess) + hashseed-invariant #
# --------------------------------------------------------------------------- #
def test_plan_json_default_byte_identical_off_path(tmp_path: Path) -> None:
    # Two default ``apex plan --json`` runs (NO --value-lead) on the same fixture
    # produce byte-identical stdout, and EVERY value_weight is the neutral 1.0 — the
    # off-path is exactly today's output. (The existing
    # test_default_board_every_value_weight_is_neutral pins the same invariant in
    # -process; this re-pins it through the real CLI contract.)
    target = _fixture_project(tmp_path)
    a = _plan_json(target)
    b = _plan_json(target)
    assert a == b                                  # byte-identical default
    rows = json.loads(a)
    assert rows, "fixture should carry at least one objective"
    assert all(r["value_weight"] == 1.0 for r in rows)
    assert all("implement-stub" != r["objective"] for r in rows)  # expensive absent


def test_plan_json_default_is_hashseed_invariant(tmp_path: Path) -> None:
    # The default board's JSON is identical under different PYTHONHASHSEED values —
    # no set/dict-iteration order leaks into the off-path output.
    target = _fixture_project(tmp_path)
    outs = {_plan_json(target, seed=s) for s in ("0", "1", "12345")}
    assert len(outs) == 1, outs


def test_plan_json_value_lead_reorders_but_keeps_membership(tmp_path: Path) -> None:
    # The --value-lead CLI path re-weights the board (so its JSON DIFFERS from the
    # default — the flag does something) yet keeps the SAME membership and still
    # filters the expensive objectives (no implement-stub) — the no-unlock proof
    # through the real CLI. Deterministic + hashseed-invariant on the on-path too.
    target = _fixture_project(tmp_path)
    default = json.loads(_plan_json(target))
    led = json.loads(_plan_json(target, "--value-lead"))

    # Same membership SET (value_lead changes order/weights, never which appear).
    assert {r["objective"] for r in default} == {r["objective"] for r in led}
    # Expensive still filtered on the value_lead board.
    assert all(r["objective"] != "implement-stub" for r in led)
    # The on-path is itself deterministic and hashseed-invariant.
    led_outs = {_plan_json(target, "--value-lead", seed=s) for s in ("0", "7")}
    assert len(led_outs) == 1, led_outs
    # On the value_lead board the surfaced weights are the REAL buyer values for the
    # actionable objectives (not all pinned to 1.0) — proves the lens is live.
    actionable = [r for r in led if r["priority"] > 0]
    assert actionable and any(r["value_weight"] != 1.0 for r in actionable)
