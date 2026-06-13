from __future__ import annotations

from pathlib import Path

import pytest

from app.benchmarking.suite import PerformanceBenchmark


class TestPerformanceBenchmark:
    def test_run_all(self):
        bench = PerformanceBenchmark()
        results = bench.run_all()
        assert len(results) == 4
        names = [r.name for r in results]
        assert "security_agent_50files" in names
        assert "consensus_batch_30claims" in names
        assert "vector_store_100entries" in names
        assert "memory_cache_50entries" in names

    def test_save_and_report(self, tmp_path: Path):
        bench = PerformanceBenchmark()
        bench.run_all()
        out = tmp_path / "bench.json"
        bench.save(out)
        assert out.exists()
        report = bench.report()
        assert "Performance Benchmark" in report
        assert "ms/iter" in report

    def test_regression_detection(self, tmp_path: Path):
        bench = PerformanceBenchmark()
        bench.results = []
        from app.benchmarking.suite import BenchmarkResult
        bench.results.append(BenchmarkResult(name="test", duration_ms=100, iterations=1, avg_ms=100.0))

        baseline = tmp_path / "baseline.json"
        baseline.write_text('[{"name": "test", "avg_ms": 10.0}]')
        regressed = bench.has_regression(baseline, threshold=2.0)
        assert len(regressed) == 1
        assert "test:" in regressed[0]

    def test_no_regression(self, tmp_path: Path):
        bench = PerformanceBenchmark()
        bench.results = []
        from app.benchmarking.suite import BenchmarkResult
        bench.results.append(BenchmarkResult(name="test", duration_ms=15, iterations=1, avg_ms=15.0))

        baseline = tmp_path / "baseline.json"
        baseline.write_text('[{"name": "test", "avg_ms": 10.0}]')
        regressed = bench.has_regression(baseline, threshold=2.0)
        assert not regressed
