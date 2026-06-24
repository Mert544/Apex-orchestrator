"""Cost-aware tiebreak in rank_objectives (DECISION ITEM 2).

Among priority TIES on the --concrete board, the CHEAPER objective is preferred
so a cheap verified win banks before an expensive rollback-prone scan. Cost only
breaks ties — it never overrides the priority score — and the default fast board
(which filters out expensive objectives) stays byte-identical to before.
"""

from __future__ import annotations

from pathlib import Path

import app.engine.ascend as asc
from app.engine.ascend import GoalRanking, rank_objectives


def _no_learning(monkeypatch) -> None:
    """Neutralise payoff/reliability so pending alone drives the score (a fresh
    project): this isolates the cost tiebreak from learned signals."""
    monkeypatch.setattr(asc, "payoff_weights", lambda root: {})
    monkeypatch.setattr(asc, "land_factors", lambda root: {})


def test_goal_ranking_expensive_field_defaults_false_and_off_priority() -> None:
    # The new field defaults False and is NOT part of the score: two rankings that
    # differ only in `expensive` have identical priority (cost breaks ties only).
    cheap = GoalRanking(objective="a", pending=2.0, goal="g")
    pricey = GoalRanking(objective="b", pending=2.0, goal="g", expensive=True)
    assert cheap.expensive is False
    assert cheap.priority == pricey.priority
    # It is also omitted from the dashboard dict (kept byte-identical).
    assert "expensive" not in pricey.to_dict()


def test_cheap_before_expensive_on_priority_tie(tmp_path: Path, monkeypatch) -> None:
    # Two objectives with identical pending (a priority tie); the EXPENSIVE one is
    # registered FIRST, so the old (-priority, order) key would have ranked it on
    # top. The cost tiebreak now banks the cheap one first.
    _no_learning(monkeypatch)

    def fake_map():
        return {"scan-heavy": (lambda r: 2.0, lambda r: []),
                "cheap-fix": (lambda r: 2.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["scan-heavy", "cheap-fix"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"scan-heavy"})

    ranked = rank_objectives(str(tmp_path), include_expensive=True)
    assert [r.objective for r in ranked] == ["cheap-fix", "scan-heavy"]
    assert ranked[0].expensive is False
    assert ranked[1].expensive is True


def test_expensive_tiebreak_never_overrides_priority(tmp_path: Path, monkeypatch) -> None:
    # Cost ONLY breaks ties: a higher-pending expensive objective still outranks a
    # cheaper one with less pending work — priority dominates the sort key.
    _no_learning(monkeypatch)

    def fake_map():
        return {"scan-heavy": (lambda r: 5.0, lambda r: []),
                "cheap-fix": (lambda r: 2.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["cheap-fix", "scan-heavy"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"scan-heavy"})

    ranked = rank_objectives(str(tmp_path), include_expensive=True)
    # Despite being expensive, scan-heavy wins on its strictly higher pending.
    assert [r.objective for r in ranked] == ["scan-heavy", "cheap-fix"]


def test_default_board_order_unchanged_by_cost_key(tmp_path: Path, monkeypatch) -> None:
    # On the default board every expensive objective is FILTERED OUT, so the middle
    # sort key is a constant False for every survivor — the order is byte-identical
    # to the pre-feature (-priority, order) ranking. Here scan-heavy would sort
    # before cheap-fix by registration order, and it still does (it is dropped,
    # leaving only cheap-fix, while a non-expensive tie keeps registration order).
    _no_learning(monkeypatch)

    def fake_map():
        return {"alpha": (lambda r: 2.0, lambda r: []),
                "beta": (lambda r: 2.0, lambda r: []),
                "scan-heavy": (lambda r: 2.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["alpha", "beta", "scan-heavy"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names",
                        lambda: {"scan-heavy"})

    default = rank_objectives(str(tmp_path))
    # Expensive dropped; the two cheap survivors keep pure registration order.
    assert [r.objective for r in default] == ["alpha", "beta"]
    assert all(r.expensive is False for r in default)


def test_cost_key_inert_when_no_expensive_present(tmp_path: Path, monkeypatch) -> None:
    # Empty edge: with NO objective flagged expensive, every middle key is False and
    # the ranking is exactly pending-descending then registration order, unchanged.
    _no_learning(monkeypatch)

    def fake_map():
        return {"one": (lambda r: 3.0, lambda r: []),
                "two": (lambda r: 1.0, lambda r: []),
                "three": (lambda r: 3.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives",
                        lambda: ["one", "two", "three"])
    monkeypatch.setattr("app.engine.develop_registry.expensive_names", lambda: set())

    ranked = rank_objectives(str(tmp_path), include_expensive=True)
    # one and three tie on pending=3 (registration order one<three), two is last.
    assert [r.objective for r in ranked] == ["one", "three", "two"]
    assert all(r.expensive is False for r in ranked)
