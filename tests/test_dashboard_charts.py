"""Tests for the standalone SVG dashboard chart helpers."""

from __future__ import annotations

from app.reporting.dashboard_charts import (
    grade_gauge,
    metric_bars,
    scope_bar,
    sparkline,
    stacked_bar,
)

_INJECT = "<script>alert(1)</script>"


def _is_svg(s: str) -> None:
    assert isinstance(s, str)
    assert s.startswith("<svg"), s[:40]
    assert s.rstrip().endswith("</svg>"), s[-40:]


# --- shape ------------------------------------------------------------------

def test_all_functions_return_svg():
    _is_svg(grade_gauge(72, "B"))
    _is_svg(scope_bar(63))
    _is_svg(metric_bars([("coverage", 0.4), ("security", 0.9)]))
    _is_svg(sparkline([1.0, 2.0, 1.5, 3.0]))


# --- grade_gauge geometry + escaping ---------------------------------------

def test_gauge_score_shown():
    assert "0/100" in grade_gauge(0, "F")
    assert "50/100" in grade_gauge(50, "C")
    assert "100/100" in grade_gauge(100, "A")


def test_gauge_clamps_out_of_range():
    assert "100/100" in grade_gauge(250, "A")
    assert "0/100" in grade_gauge(-40, "F")


def test_gauge_band_colors():
    # band thresholds: >=80 green, >=50 amber, else red
    assert "#2e9e5b" in grade_gauge(90, "A")
    assert "#d9a300" in grade_gauge(60, "C")
    assert "#d24b3e" in grade_gauge(10, "F")


def test_gauge_zero_arc_is_zero_length():
    # at score 0 the filled dash segment must be 0
    assert 'stroke-dasharray="0 ' in grade_gauge(0, "F")


def test_gauge_escapes_letter():
    out = grade_gauge(50, _INJECT)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


# --- scope_bar --------------------------------------------------------------

def test_scope_bar_label_and_boundaries():
    assert "0% analysed (Python)" in scope_bar(0)
    assert "50% analysed (Python)" in scope_bar(50)
    assert "100% analysed (Python)" in scope_bar(100)


def test_scope_bar_clamps():
    assert "100% analysed (Python)" in scope_bar(300)
    assert "0% analysed (Python)" in scope_bar(-5)


def test_scope_bar_fill_width_at_50():
    # bar_w = 316, fill at 50% = 158
    assert 'width="158"' in scope_bar(50)


# --- metric_bars ------------------------------------------------------------

def test_metric_bars_empty_safe():
    _is_svg(metric_bars([]))


def test_metric_bars_labels_present_and_escaped():
    out = metric_bars([(_INJECT, 0.5), ("ok", 0.2)])
    assert "ok" in out
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_metric_bars_clamps_fraction():
    # over/under-range fractions must not blow past the track width (194)
    out = metric_bars([("hi", 5.0), ("lo", -2.0)])
    assert 'width="194"' in out  # clamped to full
    # the negative one should produce a 0-width fill rect
    assert 'width="0"' in out


# --- sparkline --------------------------------------------------------------

def test_sparkline_empty_safe():
    _is_svg(sparkline([]))
    assert "polyline" not in sparkline([])


def test_sparkline_single_point():
    out = sparkline([5.0])
    _is_svg(out)


def test_sparkline_flat_series_midline():
    # a constant series sits on the vertical mid-line; just must not crash
    out = sparkline([2.0, 2.0, 2.0])
    _is_svg(out)
    assert "polyline" in out


# --- stacked_bar ------------------------------------------------------------

def test_stacked_bar_returns_svg():
    _is_svg(stacked_bar([("in-scope", 7.0), ("out", 3.0)]))


def test_stacked_bar_empty_safe():
    _is_svg(stacked_bar([]))


def test_stacked_bar_all_zero_safe():
    out = stacked_bar([("a", 0.0), ("b", 0.0)])
    _is_svg(out)
    assert "no composition data" in out


def test_stacked_bar_labels_present_and_escaped():
    out = stacked_bar([("<&>tag", 4.0), ("plain", 1.0)])
    assert "plain" in out
    assert "&lt;&amp;&gt;tag" in out
    assert "<&>tag" not in out


def test_stacked_bar_proportions_normalised():
    # two equal weights -> each fills half of bar_w (316) = 158
    out = stacked_bar([("a", 5.0), ("b", 5.0)])
    assert 'width="158"' in out
    assert "50%" in out


def test_stacked_bar_clamps_negative_weights():
    # negative weight is clamped to 0, so the positive one is 100% of the bar
    out = stacked_bar([("pos", 4.0), ("neg", -10.0)])
    assert "100%" in out
    assert "0%" in out
    # negative segment renders a 0-width fill rect
    assert 'width="0"' in out


def test_stacked_bar_segment_widths_sum_to_track():
    # three weights summing exactly to bar_w when proportions resolve cleanly
    out = stacked_bar([("a", 1.0), ("b", 1.0), ("c", 2.0)])
    # a=25% -> 79, b=25% -> 79, c=50% -> 158
    assert 'width="79"' in out
    assert 'width="158"' in out


# --- determinism ------------------------------------------------------------

def test_determinism():
    assert grade_gauge(73, "B") == grade_gauge(73, "B")
    assert scope_bar(42) == scope_bar(42)
    assert metric_bars([("a", 0.3), ("b", 0.7)]) == metric_bars([("a", 0.3), ("b", 0.7)])
    assert sparkline([1.0, 9.0, 4.0]) == sparkline([1.0, 9.0, 4.0])
    assert stacked_bar([("a", 3.0), ("b", 1.0)]) == stacked_bar([("a", 3.0), ("b", 1.0)])
