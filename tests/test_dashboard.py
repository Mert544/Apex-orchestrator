from __future__ import annotations

from pathlib import Path

import pytest

from app.dashboard import DashboardStore, DashboardReport, ApexDashboardServer


class TestDashboardStore:
    def test_add_and_get_recent(self, tmp_path: Path):
        store = DashboardStore(tmp_path)
        store.add_report(DashboardReport(
            timestamp=1000.0, goal="test", plan="p", mode="report",
            total_steps=5, passed_steps=4, failed_steps=1, duration_sec=2.0,
        ))
        recent = store.get_recent(10)
        assert len(recent) == 1
        assert recent[0].goal == "test"

    def test_trends(self, tmp_path: Path):
        store = DashboardStore(tmp_path)
        store.add_report(DashboardReport(
            timestamp=1.0, goal="g1", plan="p", mode="report",
            total_steps=3, passed_steps=3, failed_steps=0, duration_sec=1.0,
        ))
        store.add_report(DashboardReport(
            timestamp=2.0, goal="g2", plan="p", mode="report",
            total_steps=3, passed_steps=2, failed_steps=1, duration_sec=2.0,
        ))
        trends = store.get_trends()
        assert trends["total_runs"] == 2
        assert trends["success_rate"] == 0.5
        assert trends["avg_duration"] == 1.5

    def test_persistence(self, tmp_path: Path):
        store1 = DashboardStore(tmp_path)
        store1.add_report(DashboardReport(
            timestamp=1.0, goal="g", plan="p", mode="report",
            total_steps=1, passed_steps=1, failed_steps=0, duration_sec=0.5,
        ))
        store2 = DashboardStore(tmp_path)
        assert len(store2.reports) == 1


class TestApexDashboardServer:
    def test_start_stop(self, tmp_path: Path):
        server = ApexDashboardServer(tmp_path, host="127.0.0.1", port=18767)
        server.start()
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:18767/api/status", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 200
        server.stop()

    def test_api_reports(self, tmp_path: Path):
        server = ApexDashboardServer(tmp_path, host="127.0.0.1", port=18768)
        server.start()
        server.add_report(DashboardReport(
            timestamp=1.0, goal="g", plan="p", mode="report",
            total_steps=1, passed_steps=1, failed_steps=0, duration_sec=0.5,
        ))
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:18768/api/reports", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = resp.read().decode("utf-8")
            assert "g" in data
        server.stop()
