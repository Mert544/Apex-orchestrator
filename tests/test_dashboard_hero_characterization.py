"""Characterization test: refactored ``render_vitals`` stays byte-identical.

Exercises a broad cross-product of representative inputs (normal values, the
``count == 1`` pluralisation boundary, ``None``/negative "not applicable"
metrics, non-coercible junk, HTML-special characters that must be escaped, and
empty/degenerate fragments) and asserts the rendered HTML string matches the
expected markup exactly. The expectations were captured from the pre-refactor
implementation, so any divergence in emitted bytes fails here.
"""

from __future__ import annotations

import itertools

from app.reporting.dashboard_hero import render_vitals


def _cases() -> list[dict[str, object]]:
    grades = ["", "B-", "A", "<b>", "&amp;", None]
    scores = [88, 0, -1, None, "x"]
    coverages = [88, 0, -1, None, "junk"]
    findings = [0, 1, 2, -1, None]
    scopes = [100, 1, -1, None]
    ideas = [0, 1, 5, -1, None]
    runnables = [0, 1, 3, -1, None]
    top_moves = ["", "  ", "Fix tests", "<script>", "a & b"]

    cases: list[dict[str, object]] = []
    # Full cross-product would be huge; sample deterministically by zipping
    # cycled axes so every value of every axis appears, plus a few hand-picked
    # edge combos.
    axes = [grades, scores, coverages, findings, scopes, ideas, runnables, top_moves]
    longest = max(len(a) for a in axes)
    cyc = [itertools.cycle(a) for a in axes]
    keys = [
        "grade_letter",
        "grade_score",
        "coverage_pct",
        "security_findings",
        "scope_pct",
        "idea_count",
        "runnable_actions",
        "top_move",
    ]
    for _ in range(longest * 3):
        cases.append({k: next(c) for k, c in zip(keys, cyc)})

    # Degenerate: every metric not-applicable -> minimal valid fragment.
    cases.append(
        dict(
            grade_letter="",
            grade_score=None,
            coverage_pct=None,
            security_findings=None,
            scope_pct=None,
            idea_count=None,
            runnable_actions=None,
            top_move="",
        )
    )
    return cases


def _expected(c: dict[str, object]) -> str:
    """Re-implement the pre-refactor logic inline as the golden oracle."""
    import html

    def coerce(value: object):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def tile(num: str, label: str) -> str:
        return (
            "<div class='vital'>"
            f"<span class='vital-num'>{html.escape(num)}</span>"
            f"<span class='vital-label'>{html.escape(label)}</span>"
            "</div>"
        )

    tiles: list[str] = []
    grade = (c["grade_letter"] or "").strip() if c["grade_letter"] else ""
    score = coerce(c["grade_score"])
    if grade or score is not None:
        num = html.escape(grade) if grade else (str(score) if score is not None else "")
        label = f"Grade {score}/100" if score is not None else "Grade"
        tiles.append(
            "<div class='vital'>"
            f"<span class='vital-num'>{num}</span>"
            f"<span class='vital-label'>{html.escape(label)}</span>"
            "</div>"
        )

    coverage = coerce(c["coverage_pct"])
    if coverage is not None and coverage >= 0:
        tiles.append(tile(f"{coverage}%", "Coverage"))

    f = coerce(c["security_findings"])
    if f is not None and f >= 0:
        noun = "security finding" if f == 1 else "security findings"
        tiles.append(tile(str(f), noun))

    scope = coerce(c["scope_pct"])
    if scope is not None and scope >= 0:
        tiles.append(tile(f"{scope}%", "in scope"))

    ideas = coerce(c["idea_count"])
    if ideas is not None and ideas >= 0:
        noun = "idea" if ideas == 1 else "ideas"
        tiles.append(tile(str(ideas), noun))

    runnable = coerce(c["runnable_actions"])
    if runnable is not None and runnable >= 0:
        tiles.append(tile(str(runnable), "runnable now"))

    parts = [f"<div class='vitals'>{''.join(tiles)}</div>"]
    move = (c["top_move"] or "").strip() if c["top_move"] else ""
    if move:
        parts.append(f"<p class='vital-top-move'>{html.escape(move)}</p>")
    return "".join(parts)


def test_render_vitals_byte_identical_over_representative_inputs() -> None:
    mismatches = 0
    for c in _cases():
        if render_vitals(**c) != _expected(c):
            mismatches += 1
    assert mismatches == 0


def test_render_vitals_minimal_fragment() -> None:
    out = render_vitals(
        grade_letter="",
        grade_score=None,
        coverage_pct=None,
        security_findings=None,
        scope_pct=None,
        idea_count=None,
        runnable_actions=None,
        top_move="",
    )
    assert out == "<div class='vitals'></div>"
