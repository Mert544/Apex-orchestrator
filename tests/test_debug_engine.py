from __future__ import annotations

import pytest

from app.engine.debug_engine import BreakpointCondition, DebugEngine


class TestDebugEngine:
    def test_trace_disabled(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=False)
        d.trace("test", "hello")
        assert len(d._traces) == 0

    def test_trace_enabled(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.trace("claim", "Security risk", {"file": "x.py"})
        assert len(d._traces) == 1
        assert d._traces[0].phase == "claim"
        assert d._traces[0].detail == "Security risk"

    def test_trace_max_limit(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.TRACE_MAX = 5
        for i in range(10):
            d.trace("phase", f"msg{i}")
        assert len(d._traces) == 5
        assert d._traces[0].detail == "msg5"

    def test_trace_call_decorator(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)

        @d.trace_call
        def sample_fn(x):
            return x * 2

        result = sample_fn(5)
        assert result == 10
        phases = [t.phase for t in d._traces]
        assert "call_enter" in phases
        assert "call_exit" in phases
        # Performance recorded (key includes <locals> prefix inside class)
        assert len(d._performance) == 1
        key = list(d._performance.keys())[0]
        assert "sample_fn" in key
        assert d._performance[key].call_count == 1

    def test_trace_call_decorator_error(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)

        @d.trace_call
        def fail_fn():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            fail_fn()
        phases = [t.phase for t in d._traces]
        assert "call_enter" in phases
        assert "call_error" in phases

    def test_snapshot(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.snapshot(
            memory={"key1": "val1"},
            claims=[{"text": "a", "status": "open"}, {"text": "b", "status": "resolved"}],
            branch_map={"x.a": {}},
            telemetry={"cost": 0.01},
        )
        assert len(d._snapshots) == 1
        s = d._snapshots[0]
        assert s.claim_count == 2
        assert s.open_claims == ["a"]

    def test_breakpoint_hit(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.set_breakpoint(BreakpointCondition(phase="error"))
        d.trace("ok", "fine")
        assert not d._paused
        d.trace("error", "something broke")
        assert d._paused
        assert len(d._pause_log) == 1

    def test_breakpoint_detail_contains(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.set_breakpoint(BreakpointCondition(detail_contains="CRITICAL"))
        d.trace("claim", "low priority")
        assert not d._paused
        d.trace("claim", "CRITICAL security flaw")
        assert d._paused

    def test_diagnose_memory_leak(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        big_mem = {f"k{i}": "v" for i in range(1500)}
        issues = d.diagnose(memory=big_mem)
        assert any("Memory store oversized" in i for i in issues)

    def test_diagnose_claim_explosion(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        claims = [{"status": "open", "text": f"c{i}"} for i in range(60)]
        issues = d.diagnose(claims=claims)
        assert any("Too many open claims" in i for i in issues)

    def test_diagnose_deep_claims(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        claims = [{"status": "open", "text": "x", "depth": 7} for _ in range(5)]
        issues = d.diagnose(claims=claims)
        assert any("deep open claims" in i for i in issues)

    def test_diagnose_no_evidence(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        claims = [{"status": "open", "text": "x"} for _ in range(10)]
        issues = d.diagnose(claims=claims)
        assert any("without evidence" in i for i in issues)

    def test_diagnose_slow_functions(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d._performance["slow_fn"] = d._performance.get("slow_fn")
        from app.engine.debug_engine import PerformanceRecord
        rec = PerformanceRecord("slow_fn", "test")
        rec.call_count = 1
        rec.total_time_ms = 2000
        d._performance["slow_fn"] = rec
        issues = d.diagnose()
        assert any("slower than 1s" in i for i in issues)

    def test_report_persists_to_disk(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.trace("scan", "started")
        d.snapshot(claims=[{"status": "open", "text": "test"}])
        r = d.report()
        assert "total_time_sec" in r
        assert r["trace_count"] == 1
        assert r["snapshot_count"] == 1
        assert "performance" in r
        debug_dir = tmp_path / ".apex" / "debug"
        assert debug_dir.exists()
        files = list(debug_dir.glob("debug-*.json"))
        assert len(files) == 1

    def test_build_call_graph(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.trace("call_enter", "outer()")
        d.trace("call_enter", "inner()")
        d.trace("call_exit", "inner()")
        d.trace("call_exit", "outer()")
        graph = d.build_call_graph()
        assert "root" in graph
        assert "outer" in graph["root"]

    def test_detect_duplicate_claims(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        claims = [{"text": "same"} for _ in range(5)]
        d.snapshot(claims=claims)
        assert any("Duplicate claims" in a for a in d._snapshots[0].anomalies)

    def test_detect_branch_explosion(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        big_map = {f"x.{i}": {} for i in range(60)}
        d.snapshot(claims=[], branch_map=big_map)
        assert any("Deep branch map" in a for a in d._snapshots[0].anomalies)

    def test_trace_pattern_loop_detection(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        for _ in range(12):
            d.trace("retry", "attempting")
        r = d.report()
        assert any("infinite loop" in p for p in r["pattern_issues"])

    def test_trace_pattern_long_gap(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        import time
        d.trace("a", "start")
        d._traces[0].timestamp = 0.0
        d.trace("b", "end")
        d._traces[1].timestamp = 40.0
        r = d.report()
        assert any("Long execution gap" in p for p in r["pattern_issues"])
