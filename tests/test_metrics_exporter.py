from __future__ import annotations

from app.metrics.exporter import MetricsMiddleware, PrometheusExporter


def test_exporter_counter():
    exp = PrometheusExporter()
    exp.counter("runs_total", 1, {"plan": "scan"})
    text = exp.render()
    assert "runs_total" in text
    assert "plan=\"scan\"" in text


def test_exporter_gauge():
    exp = PrometheusExporter()
    exp.gauge("memory_claims", 42)
    text = exp.render()
    assert "memory_claims" in text
    assert "42" in text


def test_exporter_snapshot():
    exp = PrometheusExporter()
    exp.counter("a", 1)
    snap = exp.snapshot()
    assert snap["metrics_count"] == 1
    assert snap["unique_names"] == 1


def test_exporter_clear():
    exp = PrometheusExporter()
    exp.counter("a", 1)
    exp.clear()
    assert exp.render() == ""


def test_middleware_record_run():
    exp = PrometheusExporter()
    mw = MetricsMiddleware(exp)
    mw.record_run("project_scan", 12.5, 10, 2)
    text = mw.render()
    assert "apex_runs_total" in text
    assert "apex_run_duration_seconds" in text
    assert "apex_claims_found" in text
    assert "apex_patches_applied" in text


def test_middleware_record_test():
    exp = PrometheusExporter()
    mw = MetricsMiddleware(exp)
    mw.record_test(10, 2, 5.0)
    text = mw.render()
    assert "apex_tests_total" in text
    assert "apex_tests_passed" in text
    assert "apex_tests_failed" in text
