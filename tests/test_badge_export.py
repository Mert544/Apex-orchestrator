from __future__ import annotations

import json

import pytest

from app.reporting.badge_export import (
    coverage_badge,
    findings_badge,
    grade_badge,
)


def _parse(blob: str) -> dict:
    """Parse a badge JSON string and assert it carries the endpoint schema."""
    data = json.loads(blob)
    assert isinstance(data, dict)
    assert data["schemaVersion"] == 1
    assert set(data) == {"schemaVersion", "label", "message", "color"}
    assert isinstance(data["label"], str)
    assert isinstance(data["message"], str)
    assert isinstance(data["color"], str)
    return data


# ---------------------------------------------------------------- grade_badge


@pytest.mark.parametrize(
    "letter,expected_color",
    [
        ("A+", "brightgreen"),
        ("A", "brightgreen"),
        ("A-", "brightgreen"),
        ("B+", "green"),
        ("B", "green"),
        ("B-", "green"),
        ("C+", "yellow"),
        ("C", "yellow"),
        ("C-", "yellow"),
        ("D+", "orange"),
        ("D", "orange"),
        ("D-", "orange"),
        ("F", "red"),
    ],
)
def test_grade_badge_color_bands(letter: str, expected_color: str):
    data = _parse(grade_badge(letter, 88))
    assert data["label"] == "apex grade"
    assert data["color"] == expected_color
    assert letter in data["message"]
    assert "(88)" in data["message"]


def test_grade_badge_lowercase_letter_bands_same():
    # Banding is case-insensitive: a lowercase grade lands in the same band.
    assert _parse(grade_badge("a", 95))["color"] == "brightgreen"
    assert _parse(grade_badge("c-", 71))["color"] == "yellow"


def test_grade_badge_empty_letter_is_red_and_placeholder():
    data = _parse(grade_badge("", 50))
    assert data["color"] == "red"
    # Message never blank — empty letter renders a placeholder.
    assert data["message"] == "? (50)"


def test_grade_badge_unknown_letter_is_red():
    assert _parse(grade_badge("Z", 40))["color"] == "red"


def test_grade_badge_score_is_clamped():
    assert "(0)" in _parse(grade_badge("F", -20))["message"]
    assert "(100)" in _parse(grade_badge("A+", 250))["message"]


def test_grade_badge_edge_scores():
    assert "(0)" in _parse(grade_badge("F", 0))["message"]
    assert "(100)" in _parse(grade_badge("A+", 100))["message"]


# ------------------------------------------------------------- coverage_badge


@pytest.mark.parametrize(
    "pct,expected_color",
    [
        (100, "brightgreen"),
        (90, "brightgreen"),
        (89, "green"),
        (75, "green"),
        (74, "yellow"),
        (50, "yellow"),
        (49, "red"),
        (0, "red"),
    ],
)
def test_coverage_badge_thresholds(pct: int, expected_color: str):
    data = _parse(coverage_badge(pct))
    assert data["label"] == "coverage"
    assert data["color"] == expected_color
    assert data["message"] == f"{pct}%"


def test_coverage_badge_clamps_out_of_range():
    assert _parse(coverage_badge(-5))["message"] == "0%"
    assert _parse(coverage_badge(150))["message"] == "100%"
    assert _parse(coverage_badge(150))["color"] == "brightgreen"


# ------------------------------------------------------------- findings_badge


@pytest.mark.parametrize(
    "count,expected_color",
    [
        (0, "brightgreen"),
        (1, "orange"),
        (9, "orange"),
        (10, "red"),
        (500, "red"),
    ],
)
def test_findings_badge_bands(count: int, expected_color: str):
    data = _parse(findings_badge(count))
    assert data["label"] == "apex findings"
    assert data["color"] == expected_color
    assert data["message"] == str(count)


def test_findings_badge_negative_clamped_not_clean():
    data = _parse(findings_badge(-3))
    assert data["message"] == "0"
    # Clamped to 0 -> reads as clean brightgreen, never a stray color.
    assert data["color"] == "brightgreen"


# ----------------------------------------------------------------- invariants


def test_every_builder_emits_valid_json():
    for blob in (grade_badge("B+", 85), coverage_badge(80), findings_badge(3)):
        _parse(blob)


def test_determinism_same_input_same_output():
    assert grade_badge("A", 99) == grade_badge("A", 99)
    assert coverage_badge(63) == coverage_badge(63)
    assert findings_badge(7) == findings_badge(7)


def test_message_escaping_is_safe():
    # A pathological letter with a quote/newline must stay valid JSON.
    data = _parse(grade_badge('X"\n', 10))
    assert data["color"] == "red"
    assert '"' in data["message"]
