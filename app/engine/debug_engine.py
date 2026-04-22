from __future__ import annotations

import functools
import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class ExecutionTrace:
    """A single step in the execution trace."""

    timestamp: float
    phase: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)
    stack_depth: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "phase": self.phase,
            "detail": self.detail,
            "metadata": self.metadata,
            "stack_depth": self.stack_depth,
            "duration_ms": self.duration_ms,
        }


@dataclass
class DebugSnapshot:
    """Snapshot of system state at a point in time."""

    timestamp: float
    memory_keys: list[str] = field(default_factory=list)
    claim_count: int = 0
    open_claims: list[str] = field(default_factory=list)
    branch_map: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "memory_keys": self.memory_keys,
            "claim_count": self.claim_count,
            "open_claims": self.open_claims,
            "branch_map_summary": list(self.branch_map.keys())[:20],
            "telemetry": self.telemetry,
            "anomalies": self.anomalies,
        }


@dataclass
class PerformanceRecord:
    """Performance data for a traced function call."""

    function_name: str
    module_name: str
    call_count: int = 0
    total_time_ms: float = 0.0
    max_time_ms: float = 0.0
    min_time_ms: float = float("inf")

    def to_dict(self) -> dict[str, Any]:
        avg = self.total_time_ms / self.call_count if self.call_count else 0
        return {
            "function": self.function_name,
            "module": self.module_name,
            "calls": self.call_count,
            "total_ms": round(self.total_time_ms, 3),
            "avg_ms": round(avg, 3),
            "max_ms": round(self.max_time_ms, 3),
            "min_ms": round(self.min_time_ms, 3) if self.min_time_ms != float("inf") else 0,
        }


class BreakpointCondition:
    """Condition that triggers a breakpoint pause."""

    def __init__(
        self,
        phase: str | None = None,
        detail_contains: str | None = None,
        claim_count_over: int | None = None,
        custom_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.phase = phase
        self.detail_contains = detail_contains
        self.claim_count_over = claim_count_over
        self.custom_fn = custom_fn

    def check(self, context: dict[str, Any]) -> bool:
        if self.phase and context.get("phase") != self.phase:
            return False
        if self.detail_contains and self.detail_contains not in str(context.get("detail", "")):
            return False
        if self.claim_count_over is not None and context.get("claim_count", 0) <= self.claim_count_over:
            return False
        if self.custom_fn and not self.custom_fn(context):
            return False
        return True


class DebugEngine:
    """Trace, snapshot, profile, and diagnose Apex Orchestrator execution.

    Usage:
        debug = DebugEngine(project_root)

        # Manual trace
        debug.trace("claim", "Security risk", {"file": "auth.py"})

        # Auto-trace with decorator
        @debug.trace_call
        def my_function(x):
            return x * 2

        # Breakpoint
        debug.set_breakpoint(BreakpointCondition(phase="error"))

        # Snapshot state
        debug.snapshot(memory=mem, claims=claims)

        # Report
        debug.report()
    """

    TRACE_MAX = 10_000
    SNAPSHOT_MAX = 1_000

    def __init__(self, project_root: str = ".", enabled: bool = True) -> None:
        self.project_root = Path(project_root).resolve()
        self.enabled = enabled
        self._traces: list[ExecutionTrace] = []
        self._snapshots: list[DebugSnapshot] = []
        self._performance: dict[str, PerformanceRecord] = {}
        self._start_time = time.time()
        self._breakpoints: list[BreakpointCondition] = []
        self._paused = False
        self._pause_log: list[str] = []

    # ── Public API: Tracing ───────────────────────────────────────────

    def trace(self, phase: str, detail: str, metadata: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        if len(self._traces) >= self.TRACE_MAX:
            self._traces.pop(0)
        self._traces.append(
            ExecutionTrace(
                timestamp=time.time() - self._start_time,
                phase=phase,
                detail=detail,
                metadata=metadata or {},
                stack_depth=0,
            )
        )
        # Avoid recursive breakpoint checks on breakpoint traces
        if phase != "breakpoint":
            self._check_breakpoints({"phase": phase, "detail": detail})

    def trace_call(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator: auto-trace function entry/exit with timing."""
        if not self.enabled:
            return fn

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = f"{fn.__module__}.{fn.__qualname__}"
            start = time.perf_counter()
            self.trace("call_enter", f"{key}()", {"args_count": len(args), "kwargs_keys": list(kwargs.keys())})
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                self.trace("call_error", f"{key}() raised {type(e).__name__}: {e}")
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                self.trace("call_exit", f"{key}()", {"duration_ms": round(elapsed, 3)})
                self._record_performance(key, fn.__module__, elapsed)

        return wrapper

    # ── Public API: Breakpoints ───────────────────────────────────────

    def set_breakpoint(self, condition: BreakpointCondition) -> None:
        self._breakpoints.append(condition)

    def clear_breakpoints(self) -> None:
        self._breakpoints.clear()

    def resume(self) -> None:
        self._paused = False

    # ── Public API: Snapshots ─────────────────────────────────────────

    def snapshot(
        self,
        memory: dict[str, Any] | None = None,
        claims: list[dict[str, Any]] | None = None,
        branch_map: dict[str, Any] | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        if len(self._snapshots) >= self.SNAPSHOT_MAX:
            self._snapshots.pop(0)
        mem_keys = list(memory.keys()) if memory else []
        all_claims = claims or []
        open_claims = [c.get("text", "?")[:60] for c in all_claims if c.get("status") == "open"]
        anomalies = self._detect_anomalies(all_claims, branch_map)
        self._snapshots.append(
            DebugSnapshot(
                timestamp=time.time() - self._start_time,
                memory_keys=mem_keys,
                claim_count=len(all_claims),
                open_claims=open_claims,
                branch_map=branch_map or {},
                telemetry=telemetry or {},
                anomalies=anomalies,
            )
        )
        self._check_breakpoints({"claim_count": len(all_claims), "anomalies": anomalies})

    # ── Public API: Reporting ─────────────────────────────────────────

    def report(self) -> dict[str, Any]:
        total_time = time.time() - self._start_time
        all_anomalies: list[str] = []
        for s in self._snapshots:
            all_anomalies.extend(s.anomalies)

        report = {
            "total_time_sec": round(total_time, 3),
            "trace_count": len(self._traces),
            "snapshot_count": len(self._snapshots),
            "anomalies": list(set(all_anomalies)),
            "pattern_issues": self._find_trace_patterns(),
            "phase_breakdown": self._phase_breakdown(),
            "performance": sorted(
                [p.to_dict() for p in self._performance.values()],
                key=lambda x: x["total_ms"],
                reverse=True,
            )[:20],
            "pause_events": self._pause_log,
            "snapshots": [s.to_dict() for s in self._snapshots[-5:]],
            "recent_traces": [t.to_dict() for t in self._traces[-20:]],
        }

        debug_dir = self.project_root / ".apex" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        file_path = debug_dir / f"debug-{int(time.time())}.json"
        file_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    def diagnose(self, memory: dict[str, Any] | None = None, claims: list[dict[str, Any]] | None = None) -> list[str]:
        issues: list[str] = []
        if memory and len(memory) > 1000:
            issues.append("Memory store oversized — potential leak or missing eviction")
        if claims:
            open_count = sum(1 for c in claims if c.get("status") == "open")
            if open_count > 50:
                issues.append(f"Too many open claims ({open_count}) — possible infinite expansion")
            no_evidence = [c for c in claims if not c.get("evidence")]
            if len(no_evidence) > len(claims) * 0.5:
                issues.append(f"{len(no_evidence)} claims without evidence — quality degradation")
            # Check for stale claims
            stale = [c for c in claims if c.get("status") == "open" and c.get("depth", 0) > 5]
            if stale:
                issues.append(f"{len(stale)} deep open claims (>5 depth) — possible branch runaway")
        if self._traces:
            last_trace = self._traces[-1]
            if last_trace.phase == "error" or "exception" in last_trace.detail.lower():
                issues.append(f"Last trace ended in error: {last_trace.detail}")
        # Check performance
        slow_fns = [p for p in self._performance.values() if p.avg_time_ms() > 1000]
        if slow_fns:
            issues.append(f"{len(slow_fns)} functions slower than 1s avg")
        return issues

    def compare_with_previous(self) -> dict[str, Any]:
        """Compare current session with last persisted debug report."""
        debug_dir = self.project_root / ".apex" / "debug"
        files = sorted(debug_dir.glob("debug-*.json")) if debug_dir.exists() else []
        if len(files) < 2:
            return {"error": "Need at least 2 debug runs to compare"}

        previous = json.loads(files[-2].read_text(encoding="utf-8"))
        current = self.report()

        return {
            "trace_delta": current["trace_count"] - previous.get("trace_count", 0),
            "anomaly_delta": len(current["anomalies"]) - len(previous.get("anomalies", [])),
            "new_anomalies": [a for a in current["anomalies"] if a not in previous.get("anomalies", [])],
            "resolved_anomalies": [a for a in previous.get("anomalies", []) if a not in current["anomalies"]],
            "time_delta_sec": round(current["total_time_sec"] - previous.get("total_time_sec", 0), 3),
        }

    def build_call_graph(self) -> dict[str, list[str]]:
        """Build a call graph from call_enter/call_exit traces."""
        graph: dict[str, list[str]] = {}
        stack: list[str] = []
        for t in self._traces:
            if t.phase == "call_enter":
                caller = stack[-1] if stack else "root"
                callee = t.detail.replace("()", "")
                graph.setdefault(caller, []).append(callee)
                stack.append(callee)
            elif t.phase == "call_exit":
                if stack:
                    stack.pop()
        return graph

    # ── Internal helpers ──────────────────────────────────────────────

    def _check_breakpoints(self, context: dict[str, Any]) -> None:
        for bp in self._breakpoints:
            if bp.check(context):
                msg = f"Breakpoint hit: {context}"
                self._paused = True
                self._pause_log.append(msg)
                self.trace("breakpoint", msg)
                break

    def _record_performance(self, key: str, module: str, elapsed_ms: float) -> None:
        if key not in self._performance:
            self._performance[key] = PerformanceRecord(key, module)
        rec = self._performance[key]
        rec.call_count += 1
        rec.total_time_ms += elapsed_ms
        rec.max_time_ms = max(rec.max_time_ms, elapsed_ms)
        rec.min_time_ms = min(rec.min_time_ms, elapsed_ms)

    def _detect_anomalies(self, claims: list[dict[str, Any]], branch_map: dict[str, Any] | None) -> list[str]:
        issues: list[str] = []
        if len(claims) > 100:
            issues.append(f"Claim explosion: {len(claims)} claims generated")
        duplicate_texts: dict[str, int] = {}
        for c in claims:
            txt = c.get("text", "")
            duplicate_texts[txt] = duplicate_texts.get(txt, 0) + 1
        dups = {k: v for k, v in duplicate_texts.items() if v > 3}
        if dups:
            issues.append(f"Duplicate claims detected: {len(dups)} texts repeated >3x")
        if branch_map and len(branch_map) > 50:
            issues.append(f"Deep branch map: {len(branch_map)} branches — possible runaway recursion")
        return issues

    def _find_trace_patterns(self) -> list[str]:
        issues: list[str] = []
        phases = [t.phase for t in self._traces]
        if len(phases) >= 10:
            last_10 = phases[-10:]
            unique = set(last_10)
            if len(unique) <= 2:
                issues.append(f"Possible infinite loop: last 10 traces only in phases {unique}")
        if len(self._traces) >= 2:
            gaps = []
            for i in range(1, len(self._traces)):
                gap = self._traces[i].timestamp - self._traces[i - 1].timestamp
                gaps.append(gap)
            if gaps and max(gaps) > 30:
                issues.append(f"Long execution gap detected: {max(gaps):.1f}s between traces")
        return issues

    def _phase_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self._traces:
            counts[t.phase] = counts.get(t.phase, 0) + 1
        return counts


def avg_time_ms(self: PerformanceRecord) -> float:
    return self.total_time_ms / self.call_count if self.call_count else 0


PerformanceRecord.avg_time_ms = avg_time_ms  # type: ignore[attr-defined]
