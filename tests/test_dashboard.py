from __future__ import annotations

import time
import urllib.request

import pytest

from app.engine.dashboard import DashboardServer
from app.engine.dashboard_data import DashboardDataCollector


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        import json
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture(scope="module")
def dashboard_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dashboard")
    server = DashboardServer(str(tmp), host="127.0.0.1", port=18686)
    import threading
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield server
    server.shutdown()


class TestDashboardUI:
    def test_dashboard_index(self, dashboard_server):
        html = _http_get("http://127.0.0.1:18686/")
        assert b"Apex Corp. HQ" in html
        assert b"3D Isometric Office Dashboard" in html
        assert b"Reception" in html
        assert b"Board Room" in html
        assert b"Dev Office" in html
        assert b"QA Lab" in html
        assert b"Security" in html
        assert b"R&D Lab" in html
        assert b"Archive" in html
        assert b"HR / Swarm" in html
        assert b"Break Room" in html
        assert b"Gym" in html

    def test_dashboard_3d_structure(self, dashboard_server):
        html = _http_get("http://127.0.0.1:18686/")
        assert b"scene-container" in html
        assert b"scene" in html
        assert b"floor" in html
        assert b"room-3d" in html
        assert b"face-top" in html
        assert b"face-front" in html
        assert b"face-right" in html
        assert b"preserve-3d" in html
        assert b"rotateX(60deg)" in html

    def test_dashboard_svg_characters(self, dashboard_server):
        html = _http_get("http://127.0.0.1:18686/")
        assert b"worker-svg" in html
        assert b"viewBox=\"0 0 80 100\"" in html
        # Check SVG body parts (rects for legs, circles for heads, etc.)
        assert b"<ellipse" in html
        assert b"<rect" in html
        assert b"<circle" in html
        assert b"<path" in html

    def test_dashboard_animations(self, dashboard_server):
        html = _http_get("http://127.0.0.1:18686/")
        assert b"typing-arm-left" in html
        assert b"flashlight-beam" in html
        assert b"steam-1" in html
        assert b"thought-bubble" in html

    def test_dashboard_interactivity(self, dashboard_server):
        html = _http_get("http://127.0.0.1:18686/")
        assert b"openDetail" in html
        assert b"closeDetail" in html
        assert b'detail-panel' in html
        assert b'detail-overlay' in html

    def test_dashboard_dark_theme(self, dashboard_server):
        html = _http_get("http://127.0.0.1:18686/")
        assert b"#0f172a" in html  # dark background
        assert b"#1e293b" in html  # dark card


class TestDashboardAPIs:
    def test_api_status(self, dashboard_server):
        data = _http_get_json("http://127.0.0.1:18686/api/status")
        assert "project_root" in data

    def test_api_telemetry(self, dashboard_server):
        data = _http_get_json("http://127.0.0.1:18686/api/telemetry")
        assert "session_cost_usd" in data
        assert "session_tokens_in" in data
        assert "session_tokens_out" in data

    def test_api_departments(self, dashboard_server):
        data = _http_get_json("http://127.0.0.1:18686/api/departments")
        assert "reception" in data
        assert "board" in data
        assert "dev" in data
        assert "qa" in data
        assert "security" in data
        assert "rnd" in data
        assert "archive" in data
        assert "swarm" in data
        assert "break" in data
        assert "gym" in data
        for dept in data.values():
            assert "status" in dept
            assert "last_action" in dept

    def test_api_ticker(self, dashboard_server):
        data = _http_get_json("http://127.0.0.1:18686/api/ticker")
        assert "events" in data
        assert isinstance(data["events"], list)
        for ev in data["events"]:
            assert "time" in ev
            assert "msg" in ev
            assert "severity" in ev


class TestDashboardDataCollector:
    def test_collector_basic(self, tmp_path):
        collector = DashboardDataCollector(str(tmp_path))
        deps = collector.get_all_departments()
        assert len(deps) == 10
        assert deps["reception"]["total_files"] == 0
        assert deps["dev"]["transforms_available"] == 11
        assert deps["rnd"]["reflection_depth"] == 4

    def test_collector_with_memory(self, tmp_path):
        memory_dir = tmp_path / ".epistemic"
        memory_dir.mkdir(parents=True)
        memory_file = memory_dir / "memory.json"
        memory_file.write_text(
            '{"runs": [{"timestamp": "2024-01-01T12:00:00", "plan": "project_scan", "report": {"critical_untested_modules": ["a.py"], "dependency_hubs": ["hub.py"]}}]}',
            encoding="utf-8",
        )
        collector = DashboardDataCollector(str(tmp_path))
        board = collector.get_board_data()
        assert board["active_plan"] == "project_scan"
        assert board["open_claims"] == 1
        archive = collector.get_archive_data()
        assert archive["total_runs"] == 1

    def test_collector_security_scan(self, tmp_path):
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("eval(user_input)", encoding="utf-8")
        collector = DashboardDataCollector(str(tmp_path))
        sec = collector.get_security_data()
        assert sec["risky_functions"] == 1
        assert sec["status"] == "alert"

    def test_collector_ticker(self, tmp_path):
        collector = DashboardDataCollector(str(tmp_path))
        events = collector.get_ticker_events()
        assert len(events) >= 2
        assert events[0]["severity"] in ("info", "ok", "warn", "alert")
