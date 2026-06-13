from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any


@dataclass
class BenchmarkResult:
    name: str
    duration_ms: float
    iterations: int
    avg_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class PerformanceBenchmark:
    """CI-integrated performance benchmark suite for Apex agents.

    Usage:
        bench = PerformanceBenchmark()
        bench.run_all()
        bench.save(".apex/benchmark-results.json")
    """

    def __init__(self) -> None:
        self.results: list[BenchmarkResult] = []

    def run_all(self) -> list[BenchmarkResult]:
        self.results = []
        self._benchmark_security_agent()
        self._benchmark_consensus_batch()
        self._benchmark_vector_store()
        self._benchmark_memory_cache()
        return self.results

    def _benchmark_security_agent(self, iterations: int = 10) -> None:
        from app.agents.skills import SecurityAgent
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i in range(50):
                (tmp_path / f"file_{i}.py").write_text(f"def func_{i}(): pass\n")

            agent = SecurityAgent()
            start = time.perf_counter()
            for _ in range(iterations):
                agent.run(project_root=tmp_path)
            elapsed = (time.perf_counter() - start) * 1000

            self.results.append(BenchmarkResult(
                name="security_agent_50files",
                duration_ms=elapsed,
                iterations=iterations,
                avg_ms=round(elapsed / iterations, 2),
                metadata={"files": 50},
            ))

    def _benchmark_consensus_batch(self, iterations: int = 5) -> None:
        from app.agents.evaluator import ClaimEvaluator

        claims = [f"Claim {i}: eval() found in file{i}.py" for i in range(30)]
        evaluator = ClaimEvaluator()
        start = time.perf_counter()
        for _ in range(iterations):
            evaluator.evaluate_batch(claims)
        elapsed = (time.perf_counter() - start) * 1000

        self.results.append(BenchmarkResult(
            name="consensus_batch_30claims",
            duration_ms=elapsed,
            iterations=iterations,
            avg_ms=round(elapsed / iterations, 2),
            metadata={"claims": 30},
        ))

    def _benchmark_vector_store(self, iterations: int = 10) -> None:
        from app.memory.vector_store import VectorStore

        store = VectorStore()
        for i in range(100):
            store.add(f"eval() in file{i}.py", {"id": i})

        start = time.perf_counter()
        for _ in range(iterations):
            store.search("eval usage", top_k=5)
        elapsed = (time.perf_counter() - start) * 1000

        self.results.append(BenchmarkResult(
            name="vector_store_100entries",
            duration_ms=elapsed,
            iterations=iterations,
            avg_ms=round(elapsed / iterations, 2),
            metadata={"entries": 100},
        ))

    def _benchmark_memory_cache(self, iterations: int = 20) -> None:
        from app.agents.memory import AgentMemory
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            mem = AgentMemory(memory_dir=tmp)
            # Warm cache
            for i in range(50):
                mem.remember(f"claim {i}", [], "APPROVE")

            start = time.perf_counter()
            for _ in range(iterations):
                for i in range(50):
                    mem.recall(f"claim {i}")
            elapsed = (time.perf_counter() - start) * 1000

            self.results.append(BenchmarkResult(
                name="memory_cache_50entries",
                duration_ms=elapsed,
                iterations=iterations,
                avg_ms=round(elapsed / iterations, 2),
                metadata={"entries": 50},
            ))

    def save(self, path: str | Path) -> None:
        data = [
            {
                "name": r.name,
                "duration_ms": r.duration_ms,
                "iterations": r.iterations,
                "avg_ms": r.avg_ms,
                "metadata": r.metadata,
            }
            for r in self.results
        ]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def report(self) -> str:
        lines = ["# Apex Performance Benchmark", ""]
        for r in self.results:
            lines.append(f"- **{r.name}**: {r.avg_ms}ms/iter ({r.iterations} iterations)")
        return "\n".join(lines)

    def has_regression(self, baseline_path: str | Path, threshold: float = 2.0) -> list[str]:
        """Compare against baseline. Returns list of regressed benchmarks."""
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        regressed = []
        for current in self.results:
            base = next((b for b in baseline if b["name"] == current.name), None)
            if base and current.avg_ms > base["avg_ms"] * threshold:
                regressed.append(f"{current.name}: {base['avg_ms']}ms -> {current.avg_ms}ms")
        return regressed
