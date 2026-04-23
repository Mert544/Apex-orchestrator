from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PhaseMetrics:
    """Lightweight per-phase timing collector."""

    phases: dict[str, float] = field(default_factory=dict)
    _start_times: dict[str, float] = field(default_factory=dict, repr=False)

    def start(self, phase: str) -> None:
        self._start_times[phase] = time.perf_counter()

    def end(self, phase: str) -> None:
        start = self._start_times.pop(phase, None)
        if start is not None:
            elapsed = (time.perf_counter() - start) * 1000
            self.phases[phase] = self.phases.get(phase, 0.0) + elapsed

    def to_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in self.phases.items()}

    def context(self, phase: str) -> "PhaseMetricsContext":
        return PhaseMetricsContext(self, phase)


class PhaseMetricsContext:
    """Context manager for a single phase."""

    def __init__(self, metrics: PhaseMetrics, phase: str) -> None:
        self.metrics = metrics
        self.phase = phase

    def __enter__(self) -> PhaseMetricsContext:
        self.metrics.start(self.phase)
        return self

    def __exit__(self, *args: Any) -> None:
        self.metrics.end(self.phase)
