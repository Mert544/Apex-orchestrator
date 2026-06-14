from __future__ import annotations

from app.engine.idea_investment import CurvePoint, render_investment_markdown


def test_render_without_knee_omits_recommendation_but_keeps_table():
    # No point flagged as a knee -> the "Recommended investment" block is skipped
    # (the False branch of `if knee is not None`), yet the table still renders.
    points = [
        CurvePoint(budget=0.5, total_impact=0.4, n_ideas=1, marginal_return=0.8),
        CurvePoint(budget=1.0, total_impact=0.7, n_ideas=2, marginal_return=0.6),
    ]
    md = render_investment_markdown(points)
    assert "Recommended investment" not in md
    assert "⟵ knee" not in md
    assert "| Effort budget | Ideas | Total impact | Marginal | |" in md
    # Both rows present with their budgets.
    assert "| 0.5 |" in md
    assert "| 1.0 |" in md


def test_render_zero_impact_points_use_fallback_max_and_minimum_bar():
    # All impacts zero -> `max(...) or 1.0` falls back to 1.0 and every bar is the
    # one-block minimum from `max(1, round(...))`.
    points = [
        CurvePoint(budget=0.5, total_impact=0.0, n_ideas=0, marginal_return=0.0),
        CurvePoint(budget=1.0, total_impact=0.0, n_ideas=0, marginal_return=0.0),
    ]
    md = render_investment_markdown(points)
    assert "`█`" in md  # single-block bar from the max(1, ...) guard
    assert "Recommended investment" not in md
