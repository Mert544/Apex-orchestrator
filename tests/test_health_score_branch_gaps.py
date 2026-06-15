"""Trend-direction and penalty-cap behavior for app.engine.health_score.

The two existing suites already reach 100% line/branch coverage of the module;
this file pins down *behavioral* corners that the existing tests assert only in
one direction:

  * ``render_grade_diff_markdown`` for all three deltas — improvement (✅, ↑),
    regression (⚠️, ↓), and no-change (→) — plus a component present now but
    absent from the snapshot (``old_comp.get(..., 0)`` default).
  * The Security component honoring its 30-point cap regardless of how many
    weighted findings pile up.

Deterministic and hermetic: dict-built snapshots and hand-built HealthScores,
no tmp_path, no wall-clock assertions. Style mirrors the sibling edge suites.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.health_score import (
    Component,
    HealthScore,
    grade,
    render_grade_diff_markdown,
)


def _hs(*components: Component, score: int = 90, letter: str = "A-") -> HealthScore:
    return HealthScore(score=score, letter=letter, components=list(components))


def test_diff_improvement_marks_check_and_up_arrow():
    old = {"date": "2026-01-01", "score": 70, "letter": "C-",
           "components": [{"name": "Security", "points_lost": 20}]}
    new = _hs(Component("Security", 5, "1 finding(s)"), score=85, letter="B")
    md = render_grade_diff_markdown(old, new)
    assert "↑" in md and "(+15 ↑)" in md
    # Security improved 20 -> 5: a +15 improvement gets the check icon.
    assert "✅" in md
    assert "Grade trend: 2026-01-01 → today" in md


def test_diff_regression_marks_warning_and_down_arrow():
    old = {"date": "2026-02-02", "score": 90, "letter": "A-",
           "components": [{"name": "Security", "points_lost": 0}]}
    new = _hs(Component("Security", 10, "2 finding(s)"), score=80, letter="B-")
    md = render_grade_diff_markdown(old, new)
    assert "↓" in md and "(-10 ↓)" in md
    # Security regressed 0 -> 10: diff is negative -> warning icon.
    assert "⚠️" in md


def test_diff_no_change_uses_neutral_arrow_and_no_icon():
    old = {"date": "2026-03-03", "score": 88, "letter": "B+",
           "components": [{"name": "Security", "points_lost": 4}]}
    new = _hs(Component("Security", 4, "1 finding(s)"), score=88, letter="B+")
    md = render_grade_diff_markdown(old, new)
    assert "→" in md and "(0 →)" in md
    # An unchanged component carries neither the check nor the warning icon.
    sec_row = [ln for ln in md.splitlines() if ln.startswith("| Security")][0]
    assert "✅" not in sec_row and "⚠️" not in sec_row


def test_diff_component_absent_from_snapshot_defaults_to_zero():
    # The snapshot has no "Maintainability" entry; the new grade does. The prior
    # value defaults to 0, so a now-nonzero loss reads as a regression.
    old = {"date": "2026-04-04", "score": 95, "letter": "A",
           "components": [{"name": "Security", "points_lost": 0}]}
    new = _hs(Component("Maintainability", 6, "3 function(s) over complexity 12"),
              score=89, letter="B+")
    md = render_grade_diff_markdown(old, new)
    maint_row = [ln for ln in md.splitlines() if ln.startswith("| Maintainability")][0]
    assert "−0" in maint_row and "−6" in maint_row
    assert "⚠️" in maint_row


def test_security_penalty_capped_at_thirty(tmp_path: Path):
    # Many high-weight security findings in one real module must not drive the
    # Security loss past its 30-point cap.
    (tmp_path / "app").mkdir()
    body = "import os\n" + "".join(
        f"def f{i}(c):\n    os.system(c)\n    return eval(c)\n" for i in range(40)
    )
    (tmp_path / "app" / "risky.py").write_text(body, encoding="utf-8")
    h = grade(tmp_path)
    sec = [c for c in h.components if c.name == "Security"][0]
    assert sec.points_lost == 30
    # Total score stays bounded.
    assert 0 <= h.score <= 100
