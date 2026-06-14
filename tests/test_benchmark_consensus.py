"""Tests for scripts/benchmark_consensus.py.

The benchmark measures the ClaimEvaluator's memory-cache hit rate and speedup.
Wall-clock numbers are non-deterministic and never asserted; what IS pinned is
the deterministic structure: seeded claim generation, the result dict's shape,
and the warm-cache hit rate (a re-evaluated batch hits the cache for every
claim). Runs are confined to ``tmp_path`` so no ``.apex`` dir leaks into the repo.
"""

from __future__ import annotations

from pathlib import Path

import scripts.benchmark_consensus as bc
from scripts.benchmark_consensus import benchmark, generate_claims, main


def test_generate_claims_is_seeded_and_deterministic():
    a = generate_claims(8)
    b = generate_claims(8)
    assert a == b
    assert len(a) == 8
    # A different seed yields a different sequence.
    assert generate_claims(8, seed=99) != a


def test_generate_claims_uses_only_known_vocabulary():
    claims = generate_claims(20)
    # Every claim is a template instantiated with a known target.
    for claim in claims:
        assert any(claim.startswith(t.split("{")[0]) for t in bc.CLAIM_TEMPLATES)
        assert any(target in claim for target in bc.TARGETS)


def test_generate_zero_claims_is_empty():
    assert generate_claims(0) == []


def test_benchmark_result_shape_and_warm_cache_hits(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    claims = generate_claims(4)

    results = benchmark(claims, claims, repeats=2)

    assert set(results) == {"no_memory", "with_memory", "hit_rates", "speedups"}
    # One sample per repeat for the per-run series.
    assert len(results["no_memory"]) == 2
    assert len(results["with_memory"]) == 2
    assert len(results["hit_rates"]) == 2
    # Warm cache: the second evaluation of the same batch hits every claim.
    assert results["hit_rates"] == [1.0, 1.0]


def test_benchmark_zero_repeats_yields_empty_series(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = benchmark(["x"], ["x"], repeats=0)
    assert results["no_memory"] == []
    assert results["hit_rates"] == []
    assert results["speedups"] == []
    assert results["with_memory"] == []


def test_benchmark_empty_claims_have_zero_hit_rate(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # No claims -> no second_results -> hit rate falls back to 0.0, no crash.
    results = benchmark([], [], repeats=1)
    assert results["hit_rates"] == [0.0]
    assert len(results["no_memory"]) == 1


def test_main_runs_end_to_end(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["benchmark_consensus.py", "--claims=3", "--repeats=2"])

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Benchmark: 3 claims" in out
    assert "Average cache hit rate: 100.0%" in out
    assert "Run 1:" in out and "Run 2:" in out
