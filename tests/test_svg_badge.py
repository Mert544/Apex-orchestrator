"""Tests for the offline SVG badge renderer (app/reporting/svg_badge.py)."""

from __future__ import annotations

from app.reporting.svg_badge import (
    coverage_badge_svg,
    grade_badge_svg,
    render_badge_svg,
)


def test_output_is_svg_element():
    svg = render_badge_svg("build", "passing", "brightgreen")
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")


def test_label_and_message_present():
    svg = render_badge_svg("coverage", "87%", "green")
    assert ">coverage</text>" in svg
    assert ">87%</text>" in svg


def test_special_chars_escaped():
    svg = render_badge_svg("<&>", "a<b", "blue")
    # Raw dangerous characters must not appear inside escaped text runs.
    assert ">&lt;&amp;&gt;</text>" in svg
    assert ">a&lt;b</text>" in svg
    assert "<&>" not in svg


def test_color_maps_to_hex():
    svg = render_badge_svg("x", "y", "red")
    assert "#e05d44" in svg


def test_unknown_color_falls_back_to_blue():
    svg = render_badge_svg("x", "y", "chartreuse")
    assert "#007ec6" in svg


def test_literal_hex_color_passes_through():
    svg = render_badge_svg("x", "y", "#abcdef")
    assert "#abcdef" in svg


def test_width_grows_with_longer_text():
    short = render_badge_svg("a", "b", "blue")
    longer = render_badge_svg("a", "bbbbbbbbbb", "blue")

    def width(s: str) -> int:
        start = s.index('width="') + len('width="')
        end = s.index('"', start)
        return int(s[start:end])

    assert width(longer) > width(short)


def test_determinism():
    a = render_badge_svg("apex", "ok", "green")
    b = render_badge_svg("apex", "ok", "green")
    assert a == b


def test_grade_badge_convenience():
    svg = grade_badge_svg("A+", 95)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert ">apex grade</text>" in svg
    assert ">A+ (95)</text>" in svg
    # A* band -> brightgreen.
    assert "#4c1" in svg


def test_grade_badge_clamps_score_and_handles_empty_letter():
    svg = grade_badge_svg("", 250)
    assert ">? (100)</text>" in svg
    # Empty/unknown letter -> red band.
    assert "#e05d44" in svg


def test_grade_badge_low_band_is_red():
    svg = grade_badge_svg("F", 12)
    assert ">F (12)</text>" in svg
    assert "#e05d44" in svg


def test_coverage_badge_convenience():
    svg = coverage_badge_svg(92)
    assert ">coverage</text>" in svg
    assert ">92%</text>" in svg
    assert "#4c1" in svg  # >=90 brightgreen


def test_coverage_badge_thresholds_and_clamp():
    assert "#97ca00" in coverage_badge_svg(80)   # >=75 green
    assert "#dfb317" in coverage_badge_svg(60)   # >=50 yellow
    assert "#e05d44" in coverage_badge_svg(10)   # <50 red
    # Clamp out-of-range high.
    assert ">100%</text>" in coverage_badge_svg(300)
    # Clamp out-of-range low.
    assert ">0%</text>" in coverage_badge_svg(-5)
