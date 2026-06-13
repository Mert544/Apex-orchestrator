#!/usr/bin/env python3
"""Benchmark script for measuring agent consensus cache hit rate and speedup.

Usage:
    python scripts/benchmark_consensus.py --claims=50 --repeats=3
"""
from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

# Ensure project root on path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.evaluator import ClaimEvaluator


CLAIM_TEMPLATES = [
    "Add docstrings to {target}",
    "Use eval() for {target} configuration",
    "Reduce dependency coupling in {target}",
    "Add test coverage for {target}",
    "Refactor {target} to use async",
    "Remove os.system() from {target}",
    "Add type annotations to {target}",
    "Validate input in {target}",
    "Extract {target} into separate module",
    "Add guard clause to {target}",
]

TARGETS = [
    "auth module", "checkout flow", "user service", "database layer",
    "api client", "payment gateway", "notification service", "cache layer",
    "search indexer", "report generator", "email sender", "file processor",
    "webhook handler", "scheduler", "logger", "config loader",
    "session manager", "rate limiter", "middleware", "router",
]


def generate_claims(count: int, seed: int = 42) -> list[str]:
    rng = random.Random(seed)
    claims: list[str] = []
    for _ in range(count):
        template = rng.choice(CLAIM_TEMPLATES)
        target = rng.choice(TARGETS)
        claims.append(template.format(target=target))
    return claims


def benchmark(no_memory_claims: list[str], with_memory_claims: list[str], repeats: int) -> dict:
    results = {
        "no_memory": [],
        "with_memory": [],
        "hit_rates": [],
        "speedups": [],
    }

    for run in range(repeats):
        # No memory baseline
        evaluator_no_mem = ClaimEvaluator(memory_dir=None)
        start = time.perf_counter()
        evaluator_no_mem.evaluate_batch(no_memory_claims)
        no_mem_time = time.perf_counter() - start
        results["no_memory"].append(no_mem_time)

        # With memory (first run = cold cache)
        tmp_dir = Path(f".apex/benchmark_run_{run}")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        evaluator_mem = ClaimEvaluator(memory_dir=str(tmp_dir))

        start = time.perf_counter()
        first_results = evaluator_mem.evaluate_batch(with_memory_claims)
        first_time = time.perf_counter() - start

        # Second run = warm cache
        start = time.perf_counter()
        second_results = evaluator_mem.evaluate_batch(with_memory_claims)
        second_time = time.perf_counter() - start

        # Calculate hit rate
        cached = sum(1 for r in second_results if r.metadata.get("cached"))
        hit_rate = cached / len(second_results) if second_results else 0.0
        results["hit_rates"].append(hit_rate)

        # Speedup: first vs second run
        if second_time > 0:
            speedup = first_time / second_time
            results["speedups"].append(speedup)

        # Also compare no-memory vs warm-cache
        if no_mem_time > 0 and second_time > 0:
            overall_speedup = no_mem_time / second_time
        else:
            overall_speedup = 1.0
        results["with_memory"].append(overall_speedup)

        # Cleanup
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark agent consensus with/without memory")
    parser.add_argument("--claims", type=int, default=50, help="Number of unique claims")
    parser.add_argument("--repeats", type=int, default=3, help="Number of benchmark runs")
    args = parser.parse_args()

    print(f"Benchmark: {args.claims} claims × {args.repeats} runs")
    print("=" * 50)

    claims = generate_claims(args.claims)
    results = benchmark(claims, claims, args.repeats)

    avg_hit_rate = sum(results["hit_rates"]) / len(results["hit_rates"]) * 100
    avg_speedup = sum(results["speedups"]) / len(results["speedups"])
    avg_overall = sum(results["with_memory"]) / len(results["with_memory"])

    print("\nResults:")
    print(f"  Average cache hit rate: {avg_hit_rate:.1f}%")
    print(f"  Average warm-cache speedup: {avg_speedup:.2f}x")
    print(f"  Average overall speedup (no-memory vs warm-cache): {avg_overall:.2f}x")
    print("\nPer-run details:")
    for i, (hit, speed, overall) in enumerate(zip(results["hit_rates"], results["speedups"], results["with_memory"])):
        print(f"  Run {i+1}: {hit*100:.1f}% hits, {speed:.2f}x warm, {overall:.2f}x overall")

    return 0


if __name__ == "__main__":
    sys.exit(main())
