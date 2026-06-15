from __future__ import annotations

from dataclasses import dataclass

from app.engine.idea_pareto import (
    ParetoPoint,
    knee_point,
    pareto_frontier,
)


@dataclass
class _Item:
    branch_path: str
    title: str
    impact: float
    effort: float
    value: float
    roi: float
    phase: str = "Stabilize"


def test_empty_is_safe():
    assert knee_point([]) is None
    # A frontier that computes to empty (no items) also yields None.
    assert knee_point(pareto_frontier([])) is None


def test_clear_knee_is_best_value_per_effort():
    # cheap buys 0.9 value for 0.1 effort (ratio 9); big buys 0.8 for 0.9 (~0.9).
    # Both are non-dominated trade-offs, but cheap is the bang-for-buck knee.
    big = _Item("x.big", "architectural", impact=1.0, effort=0.9, value=0.8, roi=1.1)
    cheap = _Item("x.cheap", "tiny", impact=0.5, effort=0.1, value=0.9, roi=5.0)
    front = pareto_frontier([big, cheap])
    pick = knee_point(front)
    assert pick is not None
    assert pick.branch_path == "x.cheap"


def test_accepts_raw_items_and_computes_frontier():
    big = _Item("x.big", "architectural", impact=1.0, effort=0.9, value=0.8, roi=1.1)
    cheap = _Item("x.cheap", "tiny", impact=0.5, effort=0.1, value=0.9, roi=5.0)
    # Passing raw items (not ParetoPoints) should give the same pick.
    pick = knee_point([big, cheap])
    assert isinstance(pick, ParetoPoint)
    assert pick.branch_path == "x.cheap"


def test_zero_effort_is_finite_and_wins():
    free = _Item("x.free", "free win", impact=0.6, effort=0.0, value=0.5, roi=99.0)
    paid = _Item("x.paid", "paid", impact=0.9, effort=0.4, value=0.9, roi=2.25)
    pick = knee_point([free, paid])
    assert pick is not None
    assert pick.branch_path == "x.free"  # no division-by-zero blow-up


def test_ties_break_deterministically_on_path():
    # Same objective vector -> same ratio; pareto dedup keeps one, but build the
    # ParetoPoints directly to exercise the tiebreak with two equal-ratio points.
    a = ParetoPoint("x.a", "a", "Stabilize", impact=0.6, effort=0.2, value=0.6, roi=3.0)
    b = ParetoPoint("x.b", "b", "Stabilize", impact=0.8, effort=0.4, value=1.2, roi=3.0)
    # a: 0.6/0.2 = 3.0 ; b: 1.2/0.4 = 3.0 -> tie on ratio.
    # Tiebreak: higher value (b=1.2) wins before path is consulted.
    pick = knee_point([a, b])
    assert pick is not None and pick.branch_path == "x.b"

    # Exact same value too -> falls through to lexicographically smallest path.
    c = ParetoPoint("x.z", "z", "Stabilize", impact=0.6, effort=0.2, value=0.6, roi=3.0)
    d = ParetoPoint("x.a", "a", "Stabilize", impact=0.6, effort=0.2, value=0.6, roi=3.0)
    pick2 = knee_point([c, d])
    assert pick2 is not None and pick2.branch_path == "x.a"


def test_determinism_twice_and_compare():
    items = [
        _Item("x.a", "a", 1.0, 0.2, 0.9, 5.0),
        _Item("x.b", "b", 0.6, 0.1, 0.5, 6.0),
        _Item("x.c", "c", 0.3, 0.5, 0.3, 0.6),
        _Item("x.d", "d", 0.8, 0.3, 0.95, 3.2),
    ]
    first = knee_point(items)
    second = knee_point(items)
    assert first is not None and second is not None
    assert first.branch_path == second.branch_path
    assert first.to_dict() == second.to_dict()


def test_knee_is_a_frontier_point():
    items = [
        _Item("x.a", "a", 1.0, 0.2, 0.9, 5.0),
        _Item("x.b", "b", 0.6, 0.1, 0.5, 6.0),
        _Item("x.dom", "dominated", 0.1, 0.9, 0.1, 0.1),
    ]
    front_paths = {p.branch_path for p in pareto_frontier(items)}
    pick = knee_point(items)
    assert pick is not None and pick.branch_path in front_paths
