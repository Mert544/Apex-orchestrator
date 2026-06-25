"""Value-aware planner lead — concrete LEADS on the --concrete board, the default
fast board stays byte-identical (the round-21 trust property, made structural).

A buyer-value weight (sourced from the SHIPPED ``move_value.objective_value``
model) is threaded into ``GoalRanking.priority`` as a fourth multiplicative factor
and into the ``rank_objectives`` tie-break as a value-descending key — but it is
POPULATED with the real buyer value ONLY on the ``include_expensive=True`` board
(the ``apex plan/ascend --concrete`` preview), and held NEUTRAL at 1.0 on the
default fast board and as the field default. So the SURFACING path leads with
Tier-1 concrete while the EXECUTION default board (and ``_auto_selected_objectives``
at ``concrete=False``) is unchanged: no silent pytest work without ``--concrete``.

New pure module ``app/engine/objective_value.py`` provides the value lens; this
suite pins the accessor, the ranking lead, the value-aware tie-break, the
default-board neutrality, determinism, the no-cycle import, and the to_dict
surface.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import app.engine.ascend as asc
from app.engine.ascend import GoalRanking, rank_objectives
from app.engine.move_value import DEFAULT_VALUE, objective_value
from app.engine.objective_compiler import available_objectives
from app.engine.objective_value import NEUTRAL_WEIGHT, objective_value_weight


# --------------------------------------------------------------------------- #
# the value lens (objective_value.py) — sourced from the shipped move_value    #
# --------------------------------------------------------------------------- #
def test_objective_value_weight_named_tiers() -> None:
    # Tier-1 flagship concretes dominate; Tier-3 idiom tidies are low.
    assert objective_value_weight("implement-stub") == 1.00
    assert objective_value_weight("cover-gaps") == 0.90
    assert objective_value_weight("strengthen-tests") == 0.88
    assert objective_value_weight("wire-exports") == 0.90
    assert objective_value_weight("sort-imports") == 0.18
    assert objective_value_weight("modernize") == 0.25


def test_objective_value_weight_unknown_is_move_value_default() -> None:
    # An unknown objective returns the move_value DEFAULT (0.30) — finite, >0, so a
    # brand-new ability is never starved (mirrors move_value's no-starvation clause).
    assert objective_value_weight("not-an-objective") == 0.30
    assert objective_value_weight("not-an-objective") == DEFAULT_VALUE
    assert NEUTRAL_WEIGHT == 1.0


def test_objective_value_weight_is_the_move_value_table() -> None:
    # Single source of truth: the weight IS move_value.objective_value, no second
    # hand-curated category table. Tie the value lens to the LIVE registry: every
    # available objective is finite and in (0, 1].
    for name in available_objectives():
        w = objective_value_weight(name)
        assert w == objective_value(name)
        assert 0.0 < w <= 1.0, (name, w)


def test_objective_value_weight_invariant_across_hashseed() -> None:
    # Pure frozen-dict lookup → no set/dict-iteration order in the output, so the
    # weight is identical under any PYTHONHASHSEED.
    src = (
        "from app.engine.objective_value import objective_value_weight as w;"
        "print(round(w('implement-stub'),4), round(w('sort-imports'),4),"
        " round(w('not-an-objective'),4))"
    )
    outs = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        res = subprocess.run([sys.executable, "-c", src], capture_output=True,
                             text=True, env=env)
        assert res.returncode == 0, res.stderr
        outs.add(res.stdout.strip())
    assert len(outs) == 1, outs


# --------------------------------------------------------------------------- #
# GoalRanking: the new field, priority factor, and to_dict surface             #
# --------------------------------------------------------------------------- #
def test_value_weight_defaults_neutral_and_off_priority_at_default() -> None:
    # The field defaults to 1.0 and is neutral, so the manual-construction priority
    # assertions stay byte-identical (these mirror test_ascend.py L70-74/246-249).
    assert GoalRanking("x", 3.0, "tidy", payoff=0.0).value_weight == 1.0
    assert GoalRanking("x", 3.0, "tidy", payoff=0.0).priority == 3.0
    assert GoalRanking("x", 3.0, "tidy", payoff=2.0).priority == 9.0
    assert GoalRanking("x", 10.0, "tidy", reliability=0.15).priority == 1.5


def test_value_weight_multiplies_priority_when_set() -> None:
    # When set != 1.0 (only rank_objectives does this, on the --concrete board) the
    # weight is the fourth multiplicative factor.
    assert GoalRanking("x", 2.0, "tidy", value_weight=0.5).priority == 1.0
    assert GoalRanking("x", 4.0, "tidy", payoff=1.0, reliability=0.5,
                       value_weight=0.25).priority == 1.0


def test_to_dict_surfaces_value_weight_and_still_omits_expensive() -> None:
    d = GoalRanking("implement-stub", 2.0, "lands-code", value_weight=1.0).to_dict()
    assert d["value_weight"] == 1.0
    # expensive stays omitted (keeps test_ascend_cost_tiebreak_eyml.py L32 green).
    assert "expensive" not in d
    # Rounded to 3 places, like the other float fields.
    assert GoalRanking("x", 1.0, "g", value_weight=0.87654).to_dict()["value_weight"] == 0.877


# --------------------------------------------------------------------------- #
# the ranking lead: concrete LEADS on the --concrete board                     #
# --------------------------------------------------------------------------- #
def _no_learning(monkeypatch) -> None:
    monkeypatch.setattr(asc, "payoff_weights", lambda root: {})
    monkeypatch.setattr(asc, "land_factors", lambda root: {})


def test_concrete_board_leads_with_tier1_concrete(tmp_path: Path, monkeypatch) -> None:
    # On the --concrete board a Tier-1 concrete (implement-stub pending=2, weight
    # 1.0 → priority 2.0) ranks AT OR ABOVE a high-pending idiom tidy (sort-imports
    # pending=10, weight 0.18 → priority 1.8) that would have LED under the old
    # pending-only formula.
    _no_learning(monkeypatch)

    def fake_map():
        return {"implement-stub": (lambda r: 2.0, lambda r: []),
                "sort-imports": (lambda r: 10.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["implement-stub", "sort-imports"])
    # Both flagged expensive so the include_expensive board keeps both (isolating
    # the value lead from the expensive-skip gate).
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"implement-stub", "sort-imports"})

    ranked = rank_objectives(str(tmp_path), include_expensive=True)
    assert ranked[0].objective == "implement-stub"
    assert ranked[0].value_weight == 1.0
    assert ranked[1].objective == "sort-imports"
    assert round(ranked[0].priority, 3) == 2.0
    assert round(ranked[1].priority, 3) == 1.8


def test_value_aware_tiebreak_concrete_wins_equal_priority(tmp_path: Path,
                                                           monkeypatch) -> None:
    # Two objectives with EQUAL priority on the --concrete board, one Tier-1
    # concrete (high weight) one tidy (low weight) → the concrete ranks first via
    # the inserted -r.value_weight middle key. Equal priority is engineered by
    # giving the tidy MORE pending so pending*weight matches.
    _no_learning(monkeypatch)

    # implement-stub: pending=2, weight 1.00 → priority 2.0
    # modernize:      pending=8, weight 0.25 → priority 2.0  (a priority TIE)
    def fake_map():
        return {"implement-stub": (lambda r: 2.0, lambda r: []),
                "modernize": (lambda r: 8.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    # modernize registered FIRST: under the OLD (-priority, expensive, order) key it
    # would lead the tie; the value key now lifts the concrete above it.
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["modernize", "implement-stub"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"implement-stub", "modernize"})

    ranked = rank_objectives(str(tmp_path), include_expensive=True)
    assert round(ranked[0].priority, 6) == round(ranked[1].priority, 6)  # a tie
    assert ranked[0].objective == "implement-stub"  # value key breaks it
    assert ranked[1].objective == "modernize"


def test_same_fixture_default_board_is_value_neutral(tmp_path: Path,
                                                     monkeypatch) -> None:
    # The SAME fixture on the DEFAULT board (include_expensive=False): weights are
    # neutral 1.0, so the value key is inert and the tie collapses to the existing
    # expensive/registration key — registration order (modernize first).
    _no_learning(monkeypatch)

    def fake_map():
        return {"a-stub": (lambda r: 2.0, lambda r: []),
                "z-tidy": (lambda r: 2.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives", lambda: ["z-tidy", "a-stub"])
    # Neither expensive → both survive the default board.
    monkeypatch.setattr("app.engine.develop_registry.expensive_names", lambda: set())

    ranked = rank_objectives(str(tmp_path))  # default board
    assert all(r.value_weight == 1.0 for r in ranked)
    # Registration order preserved on the tie (the value key is a constant 1.0).
    assert [r.objective for r in ranked] == ["z-tidy", "a-stub"]


# --------------------------------------------------------------------------- #
# default-board neutrality (the trust property) — purely additive on default   #
# --------------------------------------------------------------------------- #
def test_default_board_every_value_weight_is_neutral(tmp_path: Path,
                                                     monkeypatch) -> None:
    # On the default board (include_expensive=False) EVERY GoalRanking.value_weight
    # is 1.0 and the ordering is byte-identical to a run with the weight stubbed to
    # 1.0 — proves the change is purely additive on the autonomous default path.
    _no_learning(monkeypatch)

    def fake_map():
        return {"implement-stub": (lambda r: 5.0, lambda r: []),  # high-value, expensive
                "modernize": (lambda r: 3.0, lambda r: []),
                "sort-imports": (lambda r: 4.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives",
        lambda: ["implement-stub", "modernize", "sort-imports"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"implement-stub"})

    board = rank_objectives(str(tmp_path))  # default board
    assert all(r.value_weight == 1.0 for r in board)
    # Pure pending-descending (sort-imports 4 > modernize 3); expensive filtered.
    assert [r.objective for r in board] == ["sort-imports", "modernize"]

    # Stub the weight to 1.0 even on the --concrete path: same fixture, the default
    # board is identical to it filtered to non-expensive — additivity proof.
    monkeypatch.setattr(asc, "objective_value_weight", lambda name: 1.0)
    stubbed = rank_objectives(str(tmp_path))
    assert [r.objective for r in stubbed] == [r.objective for r in board]
    assert [r.value_weight for r in stubbed] == [r.value_weight for r in board]


# --------------------------------------------------------------------------- #
# determinism                                                                  #
# --------------------------------------------------------------------------- #
def test_concrete_board_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    # Two rank_objectives(include_expensive=True) calls on the same fixture return
    # identical ordering AND identical to_dict value_weight values.
    _no_learning(monkeypatch)

    def fake_map():
        return {"implement-stub": (lambda r: 2.0, lambda r: []),
                "cover-gaps": (lambda r: 3.0, lambda r: []),
                "sort-imports": (lambda r: 9.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(
        asc, "available_objectives",
        lambda: ["implement-stub", "cover-gaps", "sort-imports"])
    monkeypatch.setattr(
        "app.engine.develop_registry.expensive_names",
        lambda: {"implement-stub", "cover-gaps", "sort-imports"})

    a = rank_objectives(str(tmp_path), include_expensive=True)
    b = rank_objectives(str(tmp_path), include_expensive=True)
    assert [r.objective for r in a] == [r.objective for r in b]
    assert [r.to_dict()["value_weight"] for r in a] == \
           [r.to_dict()["value_weight"] for r in b]


# --------------------------------------------------------------------------- #
# the no-cycle import guard (architecture-grade check)                         #
# --------------------------------------------------------------------------- #
def test_no_import_cycle_for_the_value_lens() -> None:
    # objective_value -> move_value only; ascend -> objective_value. Both import
    # cleanly in a fresh interpreter after the new top-level import.
    src = "import app.engine.objective_value; import app.engine.ascend; print('ok')"
    res = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ok"
