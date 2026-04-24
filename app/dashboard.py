from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse


@dataclass
class DashboardReport:
    timestamp: float
    goal: str
    plan: str
    mode: str
    total_steps: int
    passed_steps: int
    failed_steps: int
    duration_sec: float
    summary: str = ""


class DashboardStore:
    """Simple in-memory + JSON file store for dashboard data."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.reports: list[DashboardReport] = []
        self._load()

    def add_report(self, report: DashboardReport) -> None:
        self.reports.append(report)
        self._save()

    def get_recent(self, n: int = 10) -> list[DashboardReport]:
        return sorted(self.reports, key=lambda r: r.timestamp, reverse=True)[:n]

    def get_trends(self) -> dict:
        if not self.reports:
            return {"total_runs": 0, "success_rate": 0.0, "avg_duration": 0.0}
        total = len(self.reports)
        passed = sum(1 for r in self.reports if r.failed_steps == 0)
        avg_dur = sum(r.duration_sec for r in self.reports) / total
        return {
            "total_runs": total,
            "success_rate": passed / total,
            "avg_duration": round(avg_dur, 2),
        }

    def _file(self) -> Path:
        return self.project_root / ".apex" / "dashboard-reports.json"

    def _save(self) -> None:
        self._file().parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "timestamp": r.timestamp,
                "goal": r.goal,
                "plan": r.plan,
                "mode": r.mode,
                "total_steps": r.total_steps,
                "passed_steps": r.passed_steps,
                "failed_steps": r.failed_steps,
                "duration_sec": r.duration_sec,
                "summary": r.summary,
            }
            for r in self.reports
        ]
        self._file().write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        f = self._file()
        if not f.exists():
            return
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            self.reports = [DashboardReport(**item) for item in data]
        except Exception:
            pass


def _daemon_status(project_root: Path) -> dict:
    from app.daemon import ApexDaemon
    running = ApexDaemon.is_running(project_root / ".apex" / "daemon.pid")
    return {"running": running}


class _DashboardHandler(BaseHTTPRequestHandler):
    store: DashboardStore
    project_root: Path

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_html(_DASHBOARD_HTML)
        elif path == "/api/status":
            self._send_json(_daemon_status(self.project_root))
        elif path == "/api/reports":
            recent = self.store.get_recent(20)
            self._send_json({"reports": [r.__dict__ for r in recent]})
        elif path == "/api/trends":
            self._send_json(self.store.get_trends())
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/report":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                report = DashboardReport(
                    timestamp=data.get("timestamp", time.time()),
                    goal=data.get("goal", ""),
                    plan=data.get("plan", ""),
                    mode=data.get("mode", ""),
                    total_steps=data.get("total_steps", 0),
                    passed_steps=data.get("passed_steps", 0),
                    failed_steps=data.get("failed_steps", 0),
                    duration_sec=data.get("duration_sec", 0.0),
                    summary=data.get("summary", ""),
                )
                self.store.add_report(report)
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
        else:
            self.send_error(404)


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Apex Orchestrator Dashboard</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; background: #f5f5f5; }
  h1 { color: #1a1a1a; }
  .card { background: #fff; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
  .metric { font-size: 2rem; font-weight: bold; color: #2563eb; }
  .label { color: #666; font-size: 0.9rem; }
  .status-running { color: #16a34a; }
  .status-stopped { color: #dc2626; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #e5e5e5; }
  th { color: #666; font-weight: 500; }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .badge-report { background: #dbeafe; color: #1e40af; }
  .badge-supervised { background: #fef3c7; color: #92400e; }
  .badge-autonomous { background: #dcfce7; color: #166534; }
</style>
</head>
<body>
<h1>Apex Orchestrator Dashboard</h1>

<div class="grid">
  <div class="card">
    <div class="label">Daemon Status</div>
    <div id="daemon-status" class="metric">—</div>
  </div>
  <div class="card">
    <div class="label">Total Runs</div>
    <div id="total-runs" class="metric">0</div>
  </div>
  <div class="card">
    <div class="label">Success Rate</div>
    <div id="success-rate" class="metric">0%</div>
  </div>
  <div class="card">
    <div class="label">Avg Duration</div>
    <div id="avg-duration" class="metric">0s</div>
  </div>
</div>

<div class="card">
  <div class="label">Recent Reports</div>
  <table>
    <thead>
      <tr><th>Time</th><th>Goal</th><th>Plan</th><th>Mode</th><th>Steps</th><th>Failed</th><th>Duration</th></tr>
    </thead>
    <tbody id="reports-body">
      <tr><td colspan="7" style="text-align:center;color:#999">Loading…</td></tr>
    </tbody>
  </table>
</div>

<script>
async function load() {
  const [statusRes, trendsRes, reportsRes] = await Promise.all([
    fetch('/api/status'), fetch('/api/trends'), fetch('/api/reports')
  ]);
  const status = await statusRes.json();
  const trends = await trendsRes.json();
  const reports = await reportsRes.json();

  document.getElementById('daemon-status').textContent = status.running ? 'Running' : 'Stopped';
  document.getElementById('daemon-status').className = 'metric ' + (status.running ? 'status-running' : 'status-stopped');
  document.getElementById('total-runs').textContent = trends.total_runs;
  document.getElementById('success-rate').textContent = Math.round(trends.success_rate * 100) + '%';
  document.getElementById('avg-duration').textContent = trends.avg_duration + 's';

  const tbody = document.getElementById('reports-body');
  if (reports.reports.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#999">No reports yet</td></tr>';
  } else {
    tbody.innerHTML = reports.reports.map(r => {
      const date = new Date(r.timestamp * 1000).toLocaleString();
      const badgeClass = r.mode === 'report' ? 'badge-report' : r.mode === 'supervised' ? 'badge-supervised' : 'badge-autonomous';
      return `<tr>
        <td>${date}</td>
        <td>${r.goal}</td>
        <td>${r.plan}</td>
        <td><span class="badge ${badgeClass}">${r.mode}</span></td>
        <td>${r.passed_steps}/${r.total_steps}</td>
        <td>${r.failed_steps}</td>
        <td>${r.duration_sec.toFixed(1)}s</td>
      </tr>`;
    }).join('');
  }
}
load();
setInterval(load, 10000);
</script>
</body>
</html>
"""


class ApexDashboardServer:
    """HTTP dashboard server for Apex Orchestrator."""

    def __init__(self, project_root: str | Path, host: str = "127.0.0.1", port: int = 8766) -> None:
        self.project_root = Path(project_root)
        self.host = host
        self.port = port
        self.store = DashboardStore(project_root)
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        handler = type("Handler", (_DashboardHandler,), {
            "store": self.store,
            "project_root": self.project_root,
        })
        self._server = HTTPServer((self.host, self.port), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[dashboard] Server running at http://{self.host}:{self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    def add_report(self, report: DashboardReport) -> None:
        self.store.add_report(report)

    @classmethod
    def run_standalone(cls, project_root: str | Path, host: str = "127.0.0.1", port: int = 8766) -> None:
        server = cls(project_root, host, port)
        server.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
            print("[dashboard] Shut down.")
