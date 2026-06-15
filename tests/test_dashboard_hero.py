"""Tests for the dashboard vital-signs hero fragment renderer."""

from __future__ import annotations

from app.reporting.dashboard_hero import render_vitals


def _full() -> str:
    return render_vitals(
        grade_letter="B-",
        grade_score=84,
        coverage_pct=88,
        security_findings=0,
        scope_pct=93,
        idea_count=30,
        runnable_actions=3,
        top_move="Add tests to app/engine/idea_permutation.py",
    )


def test_contains_expected_numbers_and_labels():
    out = _full()
    # Numbers present.
    assert "B-" in out
    assert "84" in out
    assert "88%" in out
    assert "93%" in out
    assert "30" in out
    assert "3" in out
    # Labels present.
    assert "Grade" in out
    assert "Coverage" in out
    assert "security findings" in out  # plural for 0
    assert "in scope" in out
    assert "ideas" in out
    assert "runnable now" in out
    # Structured, class-tagged markup; no inline styles.
    assert "class='vitals'" in out
    assert "class='vital'" in out
    assert "class='vital-num'" in out
    assert "class='vital-label'" in out
    assert "style=" not in out


def test_valid_fragment_shape():
    out = _full()
    assert out.startswith("<div class='vitals'>")
    assert out.count("<div class='vitals'>") == 1
    # The optional top move is appended after the tile row.
    assert "class='vital-top-move'" in out


def test_singular_nouns():
    out = render_vitals(
        grade_letter="A",
        grade_score=99,
        coverage_pct=100,
        security_findings=1,
        scope_pct=100,
        idea_count=1,
        runnable_actions=1,
    )
    assert "1 security finding<" not in out  # sanity: it's inside a span
    assert ">security finding<" in out  # singular, not plural
    assert ">idea<" in out  # singular


def test_script_injection_in_grade_is_escaped():
    out = render_vitals(
        grade_letter="<script>alert('x')</script>",
        grade_score=0,
        coverage_pct=0,
        security_findings=0,
        scope_pct=0,
        idea_count=0,
        runnable_actions=0,
    )
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_script_injection_in_top_move_is_escaped():
    out = render_vitals(
        grade_letter="C",
        grade_score=50,
        coverage_pct=50,
        security_findings=0,
        scope_pct=50,
        idea_count=5,
        runnable_actions=0,
        top_move="<script>evil()</script>",
    )
    assert "&lt;script&gt;" in out
    assert "<script>" not in out
    assert "evil()" in out  # text preserved, just escaped


def test_negative_metric_tile_omitted():
    out = render_vitals(
        grade_letter="B",
        grade_score=80,
        coverage_pct=-1,  # not applicable -> omitted
        security_findings=2,
        scope_pct=90,
        idea_count=10,
        runnable_actions=4,
    )
    assert "Coverage" not in out
    # Other tiles remain.
    assert "Grade" in out
    assert "in scope" in out


def test_none_metric_tile_omitted():
    out = render_vitals(
        grade_letter="B",
        grade_score=80,
        coverage_pct=None,  # type: ignore[arg-type]
        security_findings=None,  # type: ignore[arg-type]
        scope_pct=90,
        idea_count=10,
        runnable_actions=4,
    )
    assert "Coverage" not in out
    assert "security finding" not in out
    assert "in scope" in out


def test_empty_grade_letter_uses_score():
    out = render_vitals(
        grade_letter="",
        grade_score=72,
        coverage_pct=60,
        security_findings=0,
        scope_pct=70,
        idea_count=8,
        runnable_actions=2,
    )
    assert "Grade" in out
    assert "72" in out


def test_grade_omitted_when_letter_empty_and_score_none():
    out = render_vitals(
        grade_letter="",
        grade_score=None,  # type: ignore[arg-type]
        coverage_pct=50,
        security_findings=0,
        scope_pct=50,
        idea_count=1,
        runnable_actions=0,
    )
    assert "Grade" not in out
    assert "Coverage" in out


def test_no_top_move_omits_paragraph():
    out = render_vitals(
        grade_letter="A",
        grade_score=95,
        coverage_pct=90,
        security_findings=0,
        scope_pct=95,
        idea_count=20,
        runnable_actions=5,
        top_move="   ",  # whitespace-only -> omitted
    )
    assert "vital-top-move" not in out


def test_determinism():
    a = _full()
    b = _full()
    assert a == b


def test_empty_zero_inputs_safe():
    out = render_vitals(
        grade_letter="",
        grade_score=0,
        coverage_pct=0,
        security_findings=0,
        scope_pct=0,
        idea_count=0,
        runnable_actions=0,
    )
    # Minimal but valid: the tiles container is always present.
    assert out.startswith("<div class='vitals'>")
    assert "0%" in out
    assert "runnable now" in out


def test_all_not_applicable_returns_minimal_fragment():
    out = render_vitals(
        grade_letter="",
        grade_score=None,  # type: ignore[arg-type]
        coverage_pct=-1,
        security_findings=-1,
        scope_pct=-1,
        idea_count=-1,
        runnable_actions=-1,
    )
    # Never crashes; returns an empty-but-valid container.
    assert out == "<div class='vitals'></div>"


def test_non_numeric_metric_coerced_or_omitted():
    out = render_vitals(
        grade_letter="B",
        grade_score=80,
        coverage_pct="not a number",  # type: ignore[arg-type]
        security_findings=0,
        scope_pct=90,
        idea_count=10,
        runnable_actions=4,
    )
    # Bad coverage value omitted gracefully, rest intact.
    assert "Coverage" not in out
    assert "in scope" in out
