"""The 'balanced trade-off' annotation for an interior frontier point.

The existing suites cover the extreme reasons (highest impact / lowest effort /
highest value / best ROI) and the dedup/dominance set logic, but never a
non-dominated point that is the extreme on *none* of the four objectives — the
case that earns the lone "balanced trade-off" label. This file pins that branch.

Deterministic and hermetic: hand-built items, no tmp_path, no wall-clock.
Style mirrors the sibling pareto suites (a local ``_Item`` dataclass).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.idea_pareto import pareto_frontier


@dataclass
class _Item:
    branch_path: str
    title: str
    impact: float
    effort: float
    value: float
    roi: float
    phase: str = "Stabilize"


def test_interior_point_is_labelled_balanced_tradeoff():
    # Four mutually non-dominated ideas. Each corner owns an extreme:
    #   a -> highest impact, b -> lowest effort + best ROI, c -> highest value.
    # m sits in the interior: middling on impact, effort, value AND roi, so it is
    # the extreme on none of them and earns ONLY the "balanced trade-off" reason.
    a = _Item("x.a", "impact king", impact=1.0, effort=0.9, value=0.3, roi=0.33)
    b = _Item("x.b", "cheap", impact=0.2, effort=0.1, value=0.4, roi=4.0)
    c = _Item("x.c", "value king", impact=0.3, effort=0.8, value=1.0, roi=1.25)
    m = _Item("x.m", "balanced", impact=0.6, effort=0.5, value=0.6, roi=1.2)
    front = pareto_frontier([a, b, c, m])
    by_path = {p.branch_path: p for p in front}
    # The interior point survives (non-dominated) and is labelled as the balanced one.
    assert "x.m" in by_path
    assert by_path["x.m"].reasons == ["balanced trade-off"]
    # A corner that owns an extreme never gets the balanced label.
    assert "balanced trade-off" not in by_path["x.a"].reasons


def test_balanced_label_is_deterministic_across_runs():
    items = [
        _Item("x.a", "impact king", 1.0, 0.9, 0.3, 0.33),
        _Item("x.b", "cheap", 0.2, 0.1, 0.4, 4.0),
        _Item("x.c", "value king", 0.3, 0.8, 1.0, 1.25),
        _Item("x.m", "balanced", 0.6, 0.5, 0.6, 1.2),
    ]
    first = {p.branch_path: tuple(p.reasons) for p in pareto_frontier(items)}
    second = {p.branch_path: tuple(p.reasons) for p in pareto_frontier(items)}
    assert first == second
    assert first["x.m"] == ("balanced trade-off",)
