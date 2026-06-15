"""The dashboard wires the metric_bars and sparkline charts into real sections.

``metric_bars`` becomes a normalized "Health bars" block under the overview KPI
grid; ``sparkline`` becomes a findings trend inside the self-improvement
trajectory section. Both are deterministic, self-contained inline SVG and must
degrade gracefully when their data is absent.
"""

from __future__ import annotations

from app.reporting.dashboard import _health_bars, _trajectory_section


class _Profile:
    analyzed_ratio = 0.9


def test_health_bars_render_each_available_metric():
    html = _health_bars(
        _Profile(),
        {"coverage": {"coverage_ratio": 0.8}, "security": {"findings_count": 2}},
    )
    assert "<svg" in html and "Health bars" in html
    for label in ("Test coverage", "In scope (Python)", "Security"):
        assert label in html


def test_health_bars_omit_unavailable_coverage():
    # No coverage_ratio key -> the coverage row is omitted, others remain.
    html = _health_bars(_Profile(), {"security": {"findings_count": 0}})
    assert "Test coverage" not in html
    assert "Security" in html


def test_health_bars_security_mapping_is_monotonic():
    # 0 findings -> full bar (fraction 1.0); more findings -> strictly shorter.
    class _P:  # no analyzed_ratio, no coverage -> only the security row
        pass

    clean = _health_bars(_P(), {"security": {"findings_count": 0}})
    noisy = _health_bars(_P(), {"security": {"findings_count": 5}})
    assert "<svg" in clean and "<svg" in noisy
    # The clean bar's colored fill must be wider than the noisy one's (more
    # green = healthier). Match the fill rect (the one carrying a band color),
    # not the SVG canvas or the grey track.
    import re

    def _fill_width(h: str) -> float:
        m = re.search(r'<rect x="120"[^>]*width="([\d.]+)"[^>]*fill="#(?:2e9e5b|d9a300|d24b3e)"', h)
        assert m, h
        return float(m.group(1))

    assert _fill_width(clean) > _fill_width(noisy)


def test_health_bars_deterministic():
    f = {"coverage": {"coverage_ratio": 0.5}, "security": {"findings_count": 1}}
    assert _health_bars(_Profile(), f) == _health_bars(_Profile(), f)


def _hist() -> list[dict]:
    return [
        {"ts": "t1", "applied": 1, "before": {"security_findings": 7}, "after": {"security_findings": 5}},
        {"ts": "t2", "applied": 2, "after": {"security_findings": 3}},
        {"ts": "t3", "applied": 1, "after": {"security_findings": 1}},
    ]


def test_trajectory_sparkline_present_with_two_or_more_runs():
    html = _trajectory_section(_hist())
    assert "<polyline" in html and "findings trend" in html


def test_trajectory_sparkline_omitted_for_single_run():
    html = _trajectory_section(_hist()[:1])
    assert "<polyline" not in html  # one point is not a trend
    assert "Self-improvement trajectory" in html  # the section still renders


def test_trajectory_empty_history_renders_nothing():
    assert _trajectory_section([]) == ""


def test_trajectory_section_is_deterministic():
    assert _trajectory_section(_hist()) == _trajectory_section(_hist())
