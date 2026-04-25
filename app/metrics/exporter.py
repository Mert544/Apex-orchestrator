from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Metric:
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class PrometheusExporter:
    """Simple in-memory Prometheus-style metrics exporter.

    Usage:
        exporter = PrometheusExporter()
        exporter.counter("apex_runs_total", 1, {"plan": "project_scan"})
        exporter.gauge("apex_memory_claims", 42)
        print(exporter.render())
    """

    def __init__(self) -> None:
        self._metrics: list[Metric] = []
        self._lock = threading.Lock()

    def counter(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._metrics.append(Metric(name=name, value=value, labels=labels or {}))

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._metrics.append(Metric(name=name, value=value, labels=labels or {}))

    def histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._metrics.append(Metric(name=name, value=value, labels=labels or {}))

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            grouped: dict[str, list[Metric]] = {}
            for m in self._metrics:
                grouped.setdefault(m.name, []).append(m)

            for name, metrics in grouped.items():
                type_hint = "counter" if "_total" in name else "gauge"
                lines.append(f"# TYPE {name} {type_hint}")
                for m in metrics:
                    label_str = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
                    if label_str:
                        lines.append(f'{name}{{{label_str}}} {m.value}')
                    else:
                        lines.append(f'{name} {m.value}')
                lines.append("")

            return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "metrics_count": len(self._metrics),
                "unique_names": len({m.name for m in self._metrics}),
                "latest": [
                    {"name": m.name, "value": m.value, "labels": m.labels}
                    for m in self._metrics[-10:]
                ],
            }

    def clear(self) -> None:
        with self._lock:
            self._metrics.clear()


class MetricsMiddleware:
    """Middleware to record Apex run metrics."""

    def __init__(self, exporter: PrometheusExporter | None = None) -> None:
        self.exporter = exporter or PrometheusExporter()

    def record_run(self, plan: str, duration_seconds: float, claims_found: int, patches_applied: int) -> None:
        self.exporter.counter("apex_runs_total", 1, {"plan": plan})
        self.exporter.gauge("apex_run_duration_seconds", duration_seconds, {"plan": plan})
        self.exporter.gauge("apex_claims_found", claims_found)
        self.exporter.gauge("apex_patches_applied", patches_applied)

    def record_test(self, passed: int, failed: int, duration_seconds: float) -> None:
        self.exporter.counter("apex_tests_total", passed + failed)
        self.exporter.gauge("apex_tests_passed", passed)
        self.exporter.gauge("apex_tests_failed", failed)
        self.exporter.gauge("apex_test_duration_seconds", duration_seconds)

    def render(self) -> str:
        return self.exporter.render()
