"""Characterization test: refactored ``_hero_vitals`` stays byte-identical.

The oracle below is the verbatim pre-refactor body of ``_hero_vitals`` (the
inline metric extraction, best-effort grade pass, ``render_vitals`` call, and
chart/top-move assembly). It is driven over a broad cross-product of lightweight
stand-in input objects -- coverage present/absent, security counts, scope ratios
(including ``None``/junk that degrades to ``0``), idea counts, runnable-step
counts, and top-move titles with HTML-special characters that must be escaped.

For every case we compare the FULL rendered HTML string produced by the live
``_hero_vitals`` against the oracle. Both paths import the same untouched
``dashboard_charts``/``dashboard_hero``/``health_score`` modules, so any divergence
in emitted bytes -- from metric coercion to chart gating -- fails here.
"""

from __future__ import annotations

import itertools

from app.reporting.dashboard import _esc, _hero_vitals


class _Profile:
    def __init__(self, analyzed_ratio):
        self.analyzed_ratio = analyzed_ratio


class _Step:
    def __init__(self, title):
        self.title = title


class _ActionPlan:
    def __init__(self, steps, runnable):
        self.steps = steps
        self._runnable = runnable

    def executable_steps(self):
        # Mirror the real API: a list whose length is the runnable count.
        return [object()] * self._runnable


class _IdeaReport:
    def __init__(self, total):
        self.stats = {"total_ideas": total} if total is not None else {}


def _oracle(project_root, profile, findings, idea_report, action_plan) -> str:
    """Verbatim copy of the pre-refactor ``_hero_vitals`` implementation."""
    from app.reporting.dashboard_charts import grade_gauge, scope_bar
    from app.reporting.dashboard_hero import render_vitals

    sec = findings.get("security", {}) or {}
    cov = findings.get("coverage", {}) or {}
    cov_pct = int(cov.get("coverage_ratio", 0) * 100) if "coverage_ratio" in cov else -1
    sec_n = sec.get("findings_count", 0) or 0
    scope_pct = int(round(float(getattr(profile, "analyzed_ratio", 1.0) or 0.0) * 100))
    idea_count = idea_report.stats.get("total_ideas", 0)
    runnable = len(action_plan.executable_steps())
    steps = getattr(action_plan, "steps", None) or []
    top_move = steps[0].title if steps else ""

    grade_letter, grade_score = "", None
    try:
        from app.engine.health_score import grade as _grade

        g = _grade(project_root)
        grade_letter, grade_score = g.letter, g.score
    except Exception:
        grade_letter, grade_score = "", None

    vitals = render_vitals(
        grade_letter=grade_letter,
        grade_score=grade_score,
        coverage_pct=cov_pct,
        security_findings=sec_n,
        scope_pct=scope_pct,
        idea_count=idea_count,
        runnable_actions=runnable,
        top_move="",
    )
    gauge = grade_gauge(grade_score, grade_letter) if isinstance(grade_score, int) and grade_score >= 0 else ""
    scope_svg = scope_bar(scope_pct) if scope_pct >= 0 else ""
    charts = f"<div class='hero-charts'>{gauge}{scope_svg}</div>" if (gauge or scope_svg) else ""
    top_html = f"<p class='vital-top-move'>{_esc(top_move)}</p>" if top_move else ""
    return f"<div class='hero-vitals'>{vitals}{charts}</div>{top_html}"


def _findings_cases():
    return [
        {},
        {"coverage": {}},
        {"coverage": {"coverage_ratio": 0.0}},
        {"coverage": {"coverage_ratio": 0.873}},
        {"coverage": {"coverage_ratio": 1.0}},
        {"security": {}},
        {"security": {"findings_count": 0}},
        {"security": {"findings_count": 1}},
        {"security": {"findings_count": 7}},
        {"security": None, "coverage": None},
        {"security": {"findings_count": 3}, "coverage": {"coverage_ratio": 0.5}},
    ]


def _cases():
    profiles = [
        _Profile(1.0),
        _Profile(0.0),
        _Profile(0.426),
        _Profile(None),
        _Profile(0.999),
    ]
    idea_reports = [_IdeaReport(0), _IdeaReport(1), _IdeaReport(12), _IdeaReport(None)]
    step_sets = [
        ([], 0),
        ([_Step("Fix the build")], 1),
        ([_Step("<script>x</script>"), _Step("second")], 0),
        ([_Step("a & b < c")], 3),
        ([_Step("  spaced  ")], 2),
    ]

    axes = [_findings_cases(), profiles, idea_reports, step_sets]
    longest = max(len(a) for a in axes)
    cyc = [itertools.cycle(a) for a in axes]
    cases = []
    for _ in range(longest * 3):
        findings, profile, idea_report, (steps, runnable) = (next(c) for c in cyc)
        cases.append((findings, profile, idea_report, _ActionPlan(steps, runnable)))
    return cases


def test_hero_vitals_byte_identical(monkeypatch):
    project_root = "/tmp/charz-project"
    mismatches = 0
    for findings, profile, idea_report, action_plan in _cases():
        got = _hero_vitals(project_root, profile, findings, idea_report, action_plan)
        exp = _oracle(project_root, profile, findings, idea_report, action_plan)
        if got != exp:
            mismatches += 1
    assert mismatches == 0


def test_hero_vitals_with_forced_grade(monkeypatch):
    """Drive the grade-present branch (gauge rendered) deterministically."""

    class _Grade:
        letter = "A"
        score = 91

    def fake_grade(_root):
        return _Grade()

    import app.engine.health_score as hs

    monkeypatch.setattr(hs, "grade", fake_grade, raising=True)

    profile = _Profile(0.5)
    findings = {"coverage": {"coverage_ratio": 0.9}, "security": {"findings_count": 2}}
    idea_report = _IdeaReport(4)
    action_plan = _ActionPlan([_Step("Top move & go")], 2)

    got = _hero_vitals("/tmp/p", profile, findings, idea_report, action_plan)
    exp = _oracle("/tmp/p", profile, findings, idea_report, action_plan)
    assert got == exp
    # Sanity: the forced grade path actually rendered a gauge + top move.
    assert "hero-charts" in got
    assert "vital-top-move" in got
