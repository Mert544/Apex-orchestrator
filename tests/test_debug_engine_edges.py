from __future__ import annotations

import json

from app.engine.debug_engine import (
    BreakpointCondition,
    DebugEngine,
    PerformanceRecord,
)


class TestPerformanceRecordEdges:
    def test_to_dict_with_calls_computes_avg(self):
        rec = PerformanceRecord("fn", "mod")
        rec.call_count = 2
        rec.total_time_ms = 10.0
        rec.max_time_ms = 7.0
        rec.min_time_ms = 3.0
        d = rec.to_dict()
        assert d["calls"] == 2
        assert d["avg_ms"] == 5.0
        assert d["min_ms"] == 3.0

    def test_to_dict_no_calls_zero_min(self):
        rec = PerformanceRecord("fn", "mod")
        d = rec.to_dict()
        assert d["avg_ms"] == 0
        # min_time_ms is still inf -> reported as 0
        assert d["min_ms"] == 0


class TestBreakpointConditionEdges:
    def test_claim_count_over_below_threshold(self):
        bp = BreakpointCondition(claim_count_over=10)
        assert bp.check({"claim_count": 5}) is False

    def test_claim_count_over_above_threshold(self):
        bp = BreakpointCondition(claim_count_over=10)
        assert bp.check({"claim_count": 20}) is True

    def test_custom_fn_false_blocks(self):
        bp = BreakpointCondition(custom_fn=lambda ctx: False)
        assert bp.check({"phase": "x"}) is False

    def test_custom_fn_true_passes(self):
        bp = BreakpointCondition(custom_fn=lambda ctx: ctx.get("phase") == "x")
        assert bp.check({"phase": "x"}) is True


class _RecordingCollector:
    def __init__(self):
        self.errors = []

    def add_error(self, source, message, details):
        self.errors.append((source, message, details))

    def summary(self):
        return {"count": len(self.errors)}


class TestErrorCollectorIntegration:
    def test_attach_error_collector(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        col = _RecordingCollector()
        d.attach_error_collector(col)
        assert d._error_collector is col

    def test_error_level_trace_forwarded(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        col = _RecordingCollector()
        d.attach_error_collector(col)
        d.trace("error", "boom", {"k": "v"}, level=DebugEngine.LEVEL_ERROR)
        assert col.errors == [("debug", "boom", {"k": "v"})]

    def test_report_includes_error_collector_summary(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        col = _RecordingCollector()
        d.attach_error_collector(col)
        d.trace("error", "boom", level=DebugEngine.LEVEL_ERROR)
        r = d.report()
        assert r["error_collector"] == {"count": 1}


class TestDisabledNoOps:
    def test_trace_call_disabled_returns_original(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=False)

        def fn(x):
            return x + 1

        wrapped = d.trace_call(fn)
        assert wrapped is fn
        assert wrapped(1) == 2
        assert len(d._traces) == 0

    def test_snapshot_disabled_no_op(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=False)
        d.snapshot(claims=[{"text": "a", "status": "open"}])
        assert len(d._snapshots) == 0


class TestBreakpointManagement:
    def test_clear_breakpoints(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.set_breakpoint(BreakpointCondition(phase="error"))
        assert len(d._breakpoints) == 1
        d.clear_breakpoints()
        assert d._breakpoints == []

    def test_resume_clears_paused(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.set_breakpoint(BreakpointCondition(phase="error"))
        d.trace("error", "broke")
        assert d._paused
        d.resume()
        assert d._paused is False


class TestSnapshotEviction:
    def test_snapshot_max_eviction(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.SNAPSHOT_MAX = 3
        for i in range(5):
            d.snapshot(claims=[{"text": f"c{i}", "status": "open"}])
        assert len(d._snapshots) == 3
        # Oldest evicted: first remaining is the 3rd snapshot
        assert d._snapshots[0].open_claims == ["c2"]


class TestDiagnoseEdges:
    def test_diagnose_last_trace_error_phase(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.trace("error", "fatal failure")
        issues = d.diagnose()
        assert any("Last trace ended in error" in i for i in issues)

    def test_diagnose_last_trace_exception_in_detail(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        d.trace("call_error", "Unhandled Exception raised here")
        issues = d.diagnose()
        assert any("Last trace ended in error" in i for i in issues)

    def test_diagnose_empty_inputs_no_issues(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        assert d.diagnose() == []


class TestAnomalyExplosion:
    def test_claim_explosion_anomaly(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        claims = [{"text": f"c{i}", "status": "open"} for i in range(150)]
        d.snapshot(claims=claims)
        assert any("Claim explosion" in a for a in d._snapshots[0].anomalies)

    def test_detect_anomalies_empty(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        assert d._detect_anomalies([], None) == []


class TestCompareWithPrevious:
    def test_compare_needs_two_runs(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        result = d.compare_with_previous()
        assert result == {"error": "Need at least 2 debug runs to compare"}

    def test_compare_with_one_existing_run(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        # One persisted report exists; current report() makes a second internally
        # but compare requires >=2 files BEFORE running current report.
        d.report()
        result = d.compare_with_previous()
        assert result == {"error": "Need at least 2 debug runs to compare"}

    def test_compare_computes_deltas(self, tmp_path):
        d = DebugEngine(str(tmp_path), enabled=True)
        debug_dir = tmp_path / ".apex" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        # Two pre-existing persisted reports
        (debug_dir / "debug-1.json").write_text(
            json.dumps({"trace_count": 1, "anomalies": ["old"], "total_time_sec": 1.0}),
            encoding="utf-8",
        )
        (debug_dir / "debug-2.json").write_text(
            json.dumps({"trace_count": 2, "anomalies": ["old", "stale"], "total_time_sec": 2.0}),
            encoding="utf-8",
        )
        # Generate some current state with a claim-explosion anomaly
        claims = [{"text": f"c{i}", "status": "open"} for i in range(150)]
        d.snapshot(claims=claims)
        result = d.compare_with_previous()
        assert "trace_delta" in result
        assert "anomaly_delta" in result
        assert "new_anomalies" in result
        assert "resolved_anomalies" in result
        assert "time_delta_sec" in result
        # previous = files[-2] after current report() writes a 3rd file; its
        # anomalies are absent from current -> they show up as resolved.
        assert result["resolved_anomalies"]
        assert "old" in result["resolved_anomalies"]
        # Claim explosion anomaly is new
        assert any("Claim explosion" in a for a in result["new_anomalies"])
