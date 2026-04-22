from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from app.engine.dashboard_data import DashboardDataCollector


class DashboardHandler(BaseHTTPRequestHandler):
    """Serve the 3D Isometric Apex Office Dashboard with SVG characters."""

    project_root: str = "."
    collector: DashboardDataCollector | None = None

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._send_html(200, self._render_dashboard())
        elif self.path == "/api/status":
            self._send_json(200, self._get_status())
        elif self.path == "/api/telemetry":
            self._send_json(200, self._get_telemetry())
        elif self.path == "/api/departments":
            self._send_json(200, self._get_departments())
        elif self.path == "/api/ticker":
            self._send_json(200, self._get_ticker())
        else:
            self._send_json(404, {"error": "Not found"})

    def _get_collector(self) -> DashboardDataCollector:
        if self.collector is None:
            self.collector = DashboardDataCollector(self.project_root)
        return self.collector

    def _get_status(self) -> dict[str, Any]:
        root = Path(self.project_root).resolve()
        profile_file = root / ".epistemic" / "memory.json"
        status = {
            "project_root": str(root),
            "total_files": 0,
            "untested_count": 0,
            "hub_count": 0,
            "last_run": None,
        }
        if profile_file.exists():
            try:
                data = json.loads(profile_file.read_text(encoding="utf-8"))
                runs = data.get("runs", [])
                if runs:
                    last = runs[-1]
                    status["last_run"] = last.get("timestamp")
                    report = last.get("report", {})
                    status["untested_count"] = len(report.get("critical_untested_modules", []))
                    status["hub_count"] = len(report.get("dependency_hubs", []))
            except Exception:
                pass
        try:
            status["total_files"] = sum(1 for _ in root.rglob("*.py"))
        except Exception:
            pass
        return status

    def _get_telemetry(self) -> dict[str, Any]:
        root = Path(self.project_root).resolve()
        telem_dir = root / ".apex" / "telemetry"
        result = {
            "session_cost_usd": 0.0,
            "session_tokens_in": 0,
            "session_tokens_out": 0,
            "budget_remaining_usd": 0.0,
        }
        if telem_dir.exists():
            files = sorted(telem_dir.glob("run-*.json"))
            if files:
                try:
                    data = json.loads(files[-1].read_text(encoding="utf-8"))
                    telem = data.get("telemetry", {})
                    result["session_tokens_in"] = telem.get("total_input_chars", 0) // 4
                    result["session_tokens_out"] = telem.get("total_output_chars", 0) // 4
                except Exception:
                    pass
        return result

    def _get_departments(self) -> dict[str, Any]:
        return self._get_collector().get_all_departments()

    def _get_ticker(self) -> dict[str, Any]:
        return {"events": self._get_collector().get_ticker_events()}

    def _svg_maria(self) -> str:
        """Receptionist - professional woman with black hair, red blazer."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="30" fill="#1e293b"/>
  <rect x="42" y="70" width="10" height="30" fill="#1e293b"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="100" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="100" rx="8" ry="3" fill="#0f172a"/>
  <!-- Skirt -->
  <path d="M25 60 L55 60 L52 75 L28 75 Z" fill="#334155"/>
  <!-- Torso / Blazer -->
  <rect x="24" y="38" width="32" height="26" rx="4" fill="#dc2626"/>
  <rect x="38" y="38" width="4" height="26" fill="#b91c1c"/>
  <!-- Arms -->
  <rect x="18" y="40" width="8" height="22" rx="3" fill="#fcd34d"/>
  <rect x="54" y="40" width="8" height="22" rx="3" fill="#fcd34d"/>
  <!-- Hands -->
  <circle cx="22" cy="64" r="4" fill="#fcd34d"/>
  <circle cx="58" cy="64" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="32" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="24" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Hair -->
  <path d="M24 20 Q24 2 40 2 Q56 2 56 20 Q56 12 40 12 Q24 12 24 20" fill="#1e1e1e"/>
  <circle cx="26" cy="24" r="5" fill="#1e1e1e"/>
  <circle cx="54" cy="24" r="5" fill="#1e1e1e"/>
  <!-- Eyes -->
  <ellipse cx="35" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <ellipse cx="45" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <circle cx="35.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <circle cx="45.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <!-- Smile -->
  <path d="M34 30 Q40 35 46 30" fill="none" stroke="#be123c" stroke-width="1.5" stroke-linecap="round"/>
  <!-- Blush -->
  <circle cx="32" cy="28" r="3" fill="#fda4af" opacity="0.4"/>
  <circle cx="48" cy="28" r="3" fill="#fda4af" opacity="0.4"/>
</svg>'''

    def _svg_boss(self) -> str:
        """CEO - man in navy suit, gold tie, confident stance."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#1e3a8a"/>
  <rect x="42" y="70" width="10" height="28" fill="#1e3a8a"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Torso / Suit -->
  <rect x="24" y="36" width="32" height="28" rx="3" fill="#1e3a8a"/>
  <!-- White shirt V -->
  <path d="M36 36 L40 52 L44 36" fill="#fff"/>
  <!-- Gold tie -->
  <path d="M38 36 L42 36 L41 55 L39 55 Z" fill="#fbbf24"/>
  <!-- Arms crossed -->
  <rect x="18" y="38" width="8" height="18" rx="3" fill="#1e3a8a"/>
  <rect x="54" y="38" width="8" height="18" rx="3" fill="#1e3a8a"/>
  <rect x="24" y="44" width="32" height="6" rx="2" fill="#1e3a8a"/>
  <!-- Hands -->
  <circle cx="32" cy="48" r="4" fill="#fcd34d"/>
  <circle cx="48" cy="48" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Hair -->
  <path d="M24 18 Q24 2 40 2 Q56 2 56 18 L56 14 Q56 6 40 6 Q24 6 24 14 Z" fill="#475569"/>
  <!-- Eyes (confident narrow) -->
  <path d="M32 22 L38 22" stroke="#1e1e1e" stroke-width="2" stroke-linecap="round"/>
  <path d="M42 22 L48 22" stroke="#1e1e1e" stroke-width="2" stroke-linecap="round"/>
  <!-- Serious mouth -->
  <path d="M36 30 L44 30" stroke="#be123c" stroke-width="1.5" stroke-linecap="round"/>
</svg>'''

    def _svg_coder(self) -> str:
        """Developer - hoodie, glasses, typing pose."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="72" width="10" height="26" fill="#334155"/>
  <rect x="42" y="72" width="10" height="26" fill="#334155"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Torso / Hoodie -->
  <rect x="23" y="38" width="34" height="28" rx="5" fill="#22c55e"/>
  <!-- Hoodie pocket -->
  <path d="M30 60 L50 60 L48 68 L32 68 Z" fill="#16a34a"/>
  <!-- Arms typing -->
  <rect x="17" y="42" width="8" height="18" rx="3" fill="#22c55e" class="typing-arm-left"/>
  <rect x="55" y="42" width="8" height="18" rx="3" fill="#22c55e" class="typing-arm-right"/>
  <!-- Hands typing -->
  <circle cx="28" cy="60" r="4" fill="#fcd34d" class="typing-hand-left"/>
  <circle cx="52" cy="60" r="4" fill="#fcd34d" class="typing-hand-right"/>
  <!-- Keyboard glow -->
  <rect x="30" y="64" width="20" height="3" rx="1" fill="#86efac" opacity="0.6"/>
  <!-- Neck -->
  <rect x="36" y="32" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="24" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Hair (messy) -->
  <path d="M24 20 Q24 2 40 2 Q56 2 56 20 Q54 10 40 10 Q26 10 24 20" fill="#64748b"/>
  <path d="M24 16 L28 8 L32 14" fill="#64748b"/>
  <path d="M56 16 L52 8 L48 14" fill="#64748b"/>
  <!-- Glasses -->
  <rect x="30" y="21" width="8" height="5" rx="1" fill="none" stroke="#1e1e1e" stroke-width="1.5"/>
  <rect x="42" y="21" width="8" height="5" rx="1" fill="none" stroke="#1e1e1e" stroke-width="1.5"/>
  <line x1="38" y1="23" x2="42" y2="23" stroke="#1e1e1e" stroke-width="1.5"/>
  <!-- Eyes behind glasses -->
  <circle cx="34" cy="23.5" r="1.5" fill="#1e1e1e"/>
  <circle cx="46" cy="23.5" r="1.5" fill="#1e1e1e"/>
  <!-- Focused mouth -->
  <path d="M37 31 L43 31" stroke="#be123c" stroke-width="1" stroke-linecap="round"/>
</svg>'''

    def _svg_tester(self) -> str:
        """QA Engineer - lab coat, goggles, clipboard."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#334155"/>
  <rect x="42" y="70" width="10" height="28" fill="#334155"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Torso / Lab coat -->
  <rect x="23" y="36" width="34" height="28" rx="3" fill="#fff"/>
  <rect x="23" y="36" width="34" height="28" rx="3" fill="none" stroke="#e2e8f0" stroke-width="1"/>
  <!-- Coat buttons -->
  <circle cx="40" cy="44" r="1.5" fill="#cbd5e1"/>
  <circle cx="40" cy="52" r="1.5" fill="#cbd5e1"/>
  <!-- Arms -->
  <rect x="17" y="38" width="8" height="20" rx="3" fill="#fff" stroke="#e2e8f0" stroke-width="1"/>
  <rect x="55" y="38" width="8" height="20" rx="3" fill="#fff" stroke="#e2e8f0" stroke-width="1"/>
  <!-- Clipboard hand -->
  <rect x="50" y="55" width="14" height="18" rx="2" fill="#92400e"/>
  <rect x="52" y="57" width="10" height="12" fill="#fff"/>
  <line x1="54" y1="60" x2="60" y2="60" stroke="#94a3b8" stroke-width="1"/>
  <line x1="54" y1="64" x2="58" y2="64" stroke="#94a3b8" stroke-width="1"/>
  <!-- Other hand -->
  <circle cx="22" cy="62" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Hair (bun) -->
  <circle cx="40" cy="6" r="7" fill="#a16207"/>
  <path d="M26 16 Q26 4 40 4 Q54 4 54 16" fill="#a16207"/>
  <!-- Goggles on head -->
  <rect x="30" y="8" width="8" height="5" rx="1" fill="#fcd34d" stroke="#94a3b8" stroke-width="1"/>
  <rect x="42" y="8" width="8" height="5" rx="1" fill="#fcd34d" stroke="#94a3b8" stroke-width="1"/>
  <line x1="38" y1="10" x2="42" y2="10" stroke="#94a3b8" stroke-width="1"/>
  <!-- Eyes -->
  <ellipse cx="35" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <ellipse cx="45" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <circle cx="35.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <circle cx="45.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <!-- Curious smile -->
  <path d="M35 30 Q40 34 45 30" fill="none" stroke="#be123c" stroke-width="1.5" stroke-linecap="round"/>
</svg>'''

    def _svg_guard(self) -> str:
        """Security guard - blue uniform, cap, badge, alert pose."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#1e40af"/>
  <rect x="42" y="70" width="10" height="28" fill="#1e40af"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Belt -->
  <rect x="26" y="68" width="28" height="4" fill="#1e1e1e"/>
  <!-- Torso / Uniform -->
  <rect x="24" y="36" width="32" height="26" rx="3" fill="#1e40af"/>
  <!-- Badge -->
  <rect x="46" y="40" width="6" height="8" rx="1" fill="#fbbf24" stroke="#f59e0b" stroke-width="1"/>
  <rect x="47" y="42" width="4" height="1" fill="#f59e0b"/>
  <rect x="47" y="44" width="4" height="1" fill="#f59e0b"/>
  <!-- Arms at sides alert -->
  <rect x="17" y="38" width="8" height="22" rx="3" fill="#1e40af"/>
  <rect x="55" y="38" width="8" height="22" rx="3" fill="#1e40af"/>
  <!-- Hands -->
  <circle cx="21" cy="62" r="4" fill="#fcd34d"/>
  <circle cx="59" cy="62" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Cap -->
  <path d="M24 14 Q24 4 40 4 Q56 4 56 14 L58 16 L22 16 Z" fill="#1e3a8a"/>
  <rect x="38" y="2" width="4" height="6" rx="1" fill="#1e3a8a"/>
  <!-- Eyes (alert wide) -->
  <ellipse cx="35" cy="24" rx="3" ry="3.5" fill="#fff"/>
  <ellipse cx="45" cy="24" rx="3" ry="3.5" fill="#fff"/>
  <circle cx="35" cy="24" r="2" fill="#1e1e1e"/>
  <circle cx="45" cy="24" r="2" fill="#1e1e1e"/>
  <!-- Serious mouth -->
  <path d="M37 32 L43 32" stroke="#be123c" stroke-width="1.5" stroke-linecap="round"/>
  <!-- Flashlight beam -->
  <polygon points="60,50 75,45 75,55" fill="#fef08a" opacity="0.3" class="flashlight-beam"/>
</svg>'''

    def _svg_prof(self) -> str:
        """Researcher - white coat, messy hair, thinking pose."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#475569"/>
  <rect x="42" y="70" width="10" height="28" fill="#475569"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Torso / White coat -->
  <rect x="23" y="36" width="34" height="28" rx="3" fill="#fff"/>
  <!-- Orange tie -->
  <path d="M38 36 L42 36 L41 56 L39 56 Z" fill="#f97316"/>
  <!-- Arms thinking (hand on chin) -->
  <rect x="17" y="38" width="8" height="20" rx="3" fill="#fff"/>
  <rect x="55" y="38" width="8" height="16" rx="3" fill="#fff"/>
  <!-- Hand on chin -->
  <circle cx="42" cy="30" r="5" fill="#fcd34d" class="thinking-hand"/>
  <!-- Other hand -->
  <circle cx="21" cy="60" r="4" fill="#fcd34d"/>
  <!-- Thought bubble -->
  <g class="thought-bubble" opacity="0">
    <circle cx="62" cy="16" r="8" fill="#fff" stroke="#e2e8f0" stroke-width="1"/>
    <circle cx="56" cy="24" r="3" fill="#fff" stroke="#e2e8f0" stroke-width="1"/>
    <circle cx="52" cy="28" r="1.5" fill="#fff" stroke="#e2e8f0" stroke-width="1"/>
    <text x="62" y="19" text-anchor="middle" font-size="10">💡</text>
  </g>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Messy hair -->
  <path d="M24 18 Q24 2 40 2 Q56 2 56 18" fill="#e2e8f0"/>
  <path d="M24 12 L28 6 L32 12 L36 4 L40 10 L44 4 L48 12 L52 6 L56 12" fill="#e2e8f0"/>
  <!-- Glasses -->
  <rect x="30" y="20" width="8" height="5" rx="1" fill="none" stroke="#1e1e1e" stroke-width="1"/>
  <rect x="42" y="20" width="8" height="5" rx="1" fill="none" stroke="#1e1e1e" stroke-width="1"/>
  <line x1="38" y1="22" x2="42" y2="22" stroke="#1e1e1e" stroke-width="1"/>
  <!-- Thinking eyes (looking up) -->
  <circle cx="34" cy="21" r="1.5" fill="#1e1e1e"/>
  <circle cx="46" cy="21" r="1.5" fill="#1e1e1e"/>
  <!-- Hmm mouth -->
  <circle cx="40" cy="30" r="2" fill="#be123c"/>
</svg>'''

    def _svg_archie(self) -> str:
        """Archivist - brown vest, glasses, holding files."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#78716c"/>
  <rect x="42" y="70" width="10" height="28" fill="#78716c"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#451a03"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#451a03"/>
  <!-- Torso / Vest -->
  <rect x="24" y="36" width="32" height="28" rx="3" fill="#92400e"/>
  <!-- White shirt underneath -->
  <path d="M36 36 L44 36 L40 50 Z" fill="#fff"/>
  <!-- Arms holding files -->
  <rect x="17" y="40" width="8" height="18" rx="3" fill="#92400e"/>
  <rect x="55" y="40" width="8" height="18" rx="3" fill="#92400e"/>
  <!-- Stack of files -->
  <rect x="28" y="52" width="24" height="6" rx="1" fill="#fcd34d" stroke="#d97706" stroke-width="1"/>
  <rect x="29" y="46" width="22" height="6" rx="1" fill="#fde68a" stroke="#d97706" stroke-width="1"/>
  <rect x="30" y="40" width="20" height="6" rx="1" fill="#fef3c7" stroke="#d97706" stroke-width="1"/>
  <!-- Label on top file -->
  <rect x="32" y="42" width="16" height="2" fill="#fff"/>
  <!-- Hands -->
  <circle cx="28" cy="58" r="4" fill="#fcd34d"/>
  <circle cx="52" cy="58" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Gray hair -->
  <path d="M24 18 Q24 4 40 4 Q56 4 56 18 Q54 10 40 10 Q26 10 24 18" fill="#78716c"/>
  <!-- Glasses (round) -->
  <circle cx="34" cy="24" r="4" fill="none" stroke="#1e1e1e" stroke-width="1"/>
  <circle cx="46" cy="24" r="4" fill="none" stroke="#1e1e1e" stroke-width="1"/>
  <line x1="38" y1="24" x2="42" y2="24" stroke="#1e1e1e" stroke-width="1"/>
  <!-- Eyes -->
  <circle cx="34" cy="24" r="1.5" fill="#1e1e1e"/>
  <circle cx="46" cy="24" r="1.5" fill="#1e1e1e"/>
  <!-- Gentle smile -->
  <path d="M36 31 Q40 34 44 31" fill="none" stroke="#be123c" stroke-width="1.5" stroke-linecap="round"/>
</svg>'''

    def _svg_team(self) -> str:
        """HR/Swarm - business casual, headset, organizing pose."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#334155"/>
  <rect x="42" y="70" width="10" height="28" fill="#334155"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Torso -->
  <rect x="24" y="36" width="32" height="28" rx="3" fill="#64748b"/>
  <!-- White collar -->
  <path d="M36 36 L40 46 L44 36" fill="#fff"/>
  <!-- Headset -->
  <path d="M24 22 Q24 6 40 6 Q56 6 56 22" fill="none" stroke="#1e1e1e" stroke-width="2"/>
  <rect x="22" y="18" width="4" height="10" rx="2" fill="#1e1e1e"/>
  <line x1="26" y1="22" x2="30" y2="22" stroke="#1e1e1e" stroke-width="2"/>
  <!-- Mic -->
  <line x1="28" y1="24" x2="32" y2="30" stroke="#1e1e1e" stroke-width="1"/>
  <circle cx="32" cy="30" r="2" fill="#1e1e1e"/>
  <!-- Arms gesturing -->
  <rect x="16" y="38" width="8" height="16" rx="3" fill="#64748b"/>
  <rect x="56" y="38" width="8" height="16" rx="3" fill="#64748b"/>
  <!-- Hands open -->
  <circle cx="20" cy="56" r="4" fill="#fcd34d"/>
  <circle cx="60" cy="56" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Hair -->
  <path d="M24 18 Q24 4 40 4 Q56 4 56 18" fill="#1e293b"/>
  <!-- Friendly eyes -->
  <ellipse cx="35" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <ellipse cx="45" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <circle cx="35.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <circle cx="45.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <!-- Big smile -->
  <path d="M34 30 Q40 36 46 30" fill="none" stroke="#be123c" stroke-width="2" stroke-linecap="round"/>
</svg>'''

    def _svg_barista(self) -> str:
        """Barista - apron, holding coffee cup."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs -->
  <rect x="28" y="70" width="10" height="28" fill="#334155"/>
  <rect x="42" y="70" width="10" height="28" fill="#334155"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#0f172a"/>
  <!-- Torso / Shirt -->
  <rect x="24" y="36" width="32" height="28" rx="3" fill="#fff"/>
  <!-- Red apron -->
  <path d="M30 36 L50 36 L52 64 L28 64 Z" fill="#ef4444"/>
  <rect x="32" y="36" width="4" height="12" fill="#ef4444"/>
  <rect x="44" y="36" width="4" height="12" fill="#ef4444"/>
  <!-- Arms -->
  <rect x="17" y="40" width="8" height="18" rx="3" fill="#fff"/>
  <rect x="55" y="40" width="8" height="18" rx="3" fill="#fff"/>
  <!-- Coffee cup -->
  <rect x="36" y="52" width="10" height="12" rx="2" fill="#fff" stroke="#cbd5e1" stroke-width="1"/>
  <path d="M46 55 Q50 55 50 58 Q50 61 46 61" fill="none" stroke="#fff" stroke-width="2"/>
  <!-- Steam -->
  <path d="M38 48 Q40 44 42 48" fill="none" stroke="#e2e8f0" stroke-width="1.5" class="steam-1"/>
  <path d="M41 46 Q43 42 45 46" fill="none" stroke="#e2e8f0" stroke-width="1.5" class="steam-2"/>
  <!-- Hand holding cup -->
  <circle cx="34" cy="58" r="4" fill="#fcd34d"/>
  <circle cx="50" cy="58" r="4" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Hair (short) -->
  <path d="M24 18 Q24 6 40 6 Q56 6 56 18 Q54 10 40 10 Q26 10 24 18" fill="#475569"/>
  <!-- Relaxed eyes -->
  <path d="M32 23 L37 23" stroke="#1e1e1e" stroke-width="1.5" stroke-linecap="round"/>
  <path d="M43 23 L48 23" stroke="#1e1e1e" stroke-width="1.5" stroke-linecap="round"/>
  <!-- Content smile -->
  <path d="M35 30 Q40 34 45 30" fill="none" stroke="#be123c" stroke-width="1.5" stroke-linecap="round"/>
</svg>'''

    def _svg_coach(self) -> str:
        """Coach - tracksuit, whistle, energetic pose."""
        return '''<svg viewBox="0 0 80 100" class="worker-svg">
  <!-- Legs / Track pants -->
  <rect x="28" y="70" width="10" height="28" fill="#f97316"/>
  <rect x="42" y="70" width="10" height="28" fill="#f97316"/>
  <!-- Stripe on pants -->
  <rect x="28" y="70" width="2" height="28" fill="#fff"/>
  <rect x="50" y="70" width="2" height="28" fill="#fff"/>
  <!-- Shoes -->
  <ellipse cx="33" cy="98" rx="8" ry="3" fill="#fff"/>
  <ellipse cx="47" cy="98" rx="8" ry="3" fill="#fff"/>
  <!-- Torso / Hoodie -->
  <rect x="23" y="36" width="34" height="28" rx="5" fill="#f97316"/>
  <!-- White drawstrings -->
  <line x1="37" y1="38" x2="37" y2="48" stroke="#fff" stroke-width="1"/>
  <line x1="43" y1="38" x2="43" y2="48" stroke="#fff" stroke-width="1"/>
  <!-- Arms energetic -->
  <rect x="15" y="36" width="8" height="20" rx="3" fill="#f97316"/>
  <rect x="57" y="36" width="8" height="20" rx="3" fill="#f97316"/>
  <!-- Thumbs up -->
  <circle cx="19" cy="32" r="4" fill="#fcd34d"/>
  <rect x="17" y="26" width="3" height="6" rx="1" fill="#fcd34d"/>
  <!-- Other hand -->
  <circle cx="61" cy="56" r="4" fill="#fcd34d"/>
  <!-- Whistle around neck -->
  <path d="M40 36 L40 48" stroke="#e2e8f0" stroke-width="1"/>
  <rect x="38" y="48" width="6" height="4" rx="1" fill="#fcd34d"/>
  <!-- Neck -->
  <rect x="36" y="30" width="8" height="8" fill="#fcd34d"/>
  <!-- Head -->
  <ellipse cx="40" cy="22" rx="14" ry="16" fill="#fcd34d"/>
  <!-- Headband -->
  <rect x="26" y="12" width="28" height="4" rx="2" fill="#c2410c"/>
  <!-- Energetic eyes -->
  <ellipse cx="35" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <ellipse cx="45" cy="24" rx="2.5" ry="3" fill="#fff"/>
  <circle cx="35.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <circle cx="45.5" cy="24" r="1.5" fill="#1e1e1e"/>
  <!-- Motivated smile -->
  <path d="M34 30 Q40 36 46 30" fill="none" stroke="#be123c" stroke-width="2" stroke-linecap="round"/>
</svg>'''

    def _render_dashboard(self) -> str:
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Apex Corp. — 3D Office</title>
<style>
:root {{
  --wall: #cbd5e1;
  --floor: #e2e8f0;
  --floor-dark: #94a3b8;
  --accent: #0ea5e9;
  --ok: #22c55e;
  --warn: #f59e0b;
  --err: #ef4444;
  --text: #1e293b;
  --text-light: #64748b;
  --card: #ffffff;
  --shadow: rgba(0,0,0,0.15);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: system-ui, -apple-system, sans-serif;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
  color: var(--text);
  overflow: hidden;
  height: 100vh;
  width: 100vw;
}}

/* ── Header ───────────────────────────────────────── */
header {{
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 100;
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}}
header h1 {{
  font-size: 1.1rem;
  color: #e2e8f0;
  font-weight: 700;
  letter-spacing: -0.01em;
}}
header .subtitle {{
  font-size: 0.7rem;
  color: #94a3b8;
}}
.clock {{
  font-family: "SF Mono", monospace;
  font-size: 0.9rem;
  color: #38bdf8;
  background: rgba(0,0,0,0.3);
  padding: 0.3rem 0.75rem;
  border-radius: 0.375rem;
}}

/* ── 3D Scene Container ───────────────────────────── */
.scene-container {{
  width: 100vw;
  height: 100vh;
  perspective: 1400px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}}

.scene {{
  position: relative;
  width: 900px;
  height: 700px;
  transform-style: preserve-3d;
  transform: rotateX(60deg) rotateZ(-35deg) translateZ(-200px);
  transition: transform 0.6s cubic-bezier(0.16,1,0.3,1);
}}

/* ── Floor Grid ───────────────────────────────────── */
.floor {{
  position: absolute;
  width: 900px;
  height: 700px;
  background:
    linear-gradient(rgba(148,163,184,0.15) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,163,184,0.15) 1px, transparent 1px),
    #1e293b;
  background-size: 40px 40px;
  transform: rotateX(90deg) translateZ(0);
  transform-origin: bottom;
  box-shadow:
    inset 0 0 80px rgba(0,0,0,0.5),
    0 0 60px rgba(14,165,233,0.08);
  border-radius: 8px;
}}

/* ── 3D Room (Cube) ───────────────────────────────── */
.room-3d {{
  position: absolute;
  width: 170px;
  height: 130px;
  transform-style: preserve-3d;
  cursor: pointer;
  transition: transform 0.4s cubic-bezier(0.16,1,0.3,1);
}}
.room-3d:hover {{
  transform: translateZ(30px) scale(1.05);
}}
.room-3d:hover .face-top {{
  background: rgba(14,165,233,0.2);
  border-color: rgba(14,165,233,0.6);
}}
.room-3d:hover .face-front,
.room-3d:hover .face-right {{
  background: rgba(14,165,233,0.12);
}}

/* Room faces */
.face {{
  position: absolute;
  border: 1px solid rgba(255,255,255,0.12);
  transition: all 0.3s;
}}
.face-top {{
  width: 170px; height: 130px;
  background: rgba(255,255,255,0.06);
  transform: rotateX(90deg) translateZ(65px);
  transform-origin: bottom;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 0.5rem;
  backdrop-filter: blur(4px);
}}
.face-front {{
  width: 170px; height: 65px;
  background: rgba(255,255,255,0.04);
  transform: translateZ(65px);
  bottom: 0;
}}
.face-right {{
  width: 130px; height: 65px;
  background: rgba(255,255,255,0.03);
  transform: rotateY(90deg) translateZ(105px);
  bottom: 0;
  right: -65px;
}}

/* ── Room Content (on top face) ───────────────────── */
.room-label {{
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #94a3b8;
  margin-bottom: 0.15rem;
  text-align: center;
}}
.room-status-led {{
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 6px var(--ok);
  margin-bottom: 0.25rem;
  animation: pulse 2s infinite;
}}
.room-status-led.warn {{ background: var(--warn); box-shadow: 0 0 6px var(--warn); }}
.room-status-led.alert {{ background: var(--err); box-shadow: 0 0 8px var(--err); animation: pulse 0.8s infinite; }}
.room-status-led.busy {{ background: var(--warn); }}
.room-status-led.thinking {{ background: var(--accent); box-shadow: 0 0 6px var(--accent); }}

@keyframes pulse {{
  0%,100% {{ opacity: 1; }}
  50% {{ opacity: 0.4; }}
}}

.worker-name {{
  font-size: 0.65rem;
  font-weight: 600;
  color: #e2e8f0;
  text-align: center;
  margin-top: -0.2rem;
}}
.worker-role {{
  font-size: 0.5rem;
  color: #64748b;
  text-align: center;
}}

/* ── SVG Worker ───────────────────────────────────── */
.worker-3d {{
  width: 50px;
  height: 62px;
  transform: rotateX(-90deg) rotateZ(35deg);
  margin: 0.1rem 0;
}}
.worker-3d svg {{
  width: 100%;
  height: 100%;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
}}

/* ── Animations on SVG parts ──────────────────────── */
@keyframes typing-left {{
  0%,100% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-3px); }}
}}
@keyframes typing-right {{
  0%,100% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-2px); }}
}}
.typing-arm-left {{ animation: typing-left 0.4s infinite alternate; }}
.typing-arm-right {{ animation: typing-right 0.5s infinite alternate; }}
.typing-hand-left {{ animation: typing-left 0.35s infinite alternate; }}
.typing-hand-right {{ animation: typing-right 0.45s infinite alternate; }}

@keyframes scan-rotate {{
  0%,100% {{ transform: rotate(0deg); }}
  25% {{ transform: rotate(-8deg); }}
  75% {{ transform: rotate(8deg); }}
}}
.flashlight-beam {{ animation: scan-rotate 2s ease-in-out infinite; transform-origin: 60px 50px; }}

@keyframes steam-rise {{
  0% {{ opacity: 0; transform: translateY(0); }}
  50% {{ opacity: 0.7; }}
  100% {{ opacity: 0; transform: translateY(-8px); }}
}}
.steam-1 {{ animation: steam-rise 2s infinite; }}
.steam-2 {{ animation: steam-rise 2s 0.7s infinite; }}

@keyframes think-pop {{
  0%,80%,100% {{ opacity: 0; transform: translateY(4px) scale(0.8); }}
  40% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}
.thought-bubble {{ animation: think-pop 3s infinite; }}
.thinking-hand {{ animation: typing-left 2s ease-in-out infinite; }}

/* ── Room Positions on Floor ──────────────────────── */
/* Row 1 */
#room-reception {{ top: 60px; left: 60px; }}
#room-board     {{ top: 60px; left: 280px; }}
#room-dev       {{ top: 60px; left: 500px; }}
#room-qa        {{ top: 60px; left: 720px; }}

/* Row 2 */
#room-security  {{ top: 230px; left: 60px; }}
#room-rnd       {{ top: 230px; left: 280px; }}
#room-archive   {{ top: 230px; left: 500px; }}
#room-swarm     {{ top: 230px; left: 720px; }}

/* Row 3 (wide) */
#room-break     {{ top: 400px; left: 220px; width: 240px; }}
#room-break .face-top {{ width: 240px; }}
#room-break .face-front {{ width: 240px; }}
#room-break .face-right {{ width: 130px; transform: rotateY(90deg) translateZ(185px); }}

#room-gym       {{ top: 400px; left: 500px; width: 240px; }}
#room-gym .face-top {{ width: 240px; }}
#room-gym .face-front {{ width: 240px; }}
#room-gym .face-right {{ width: 130px; transform: rotateY(90deg) translateZ(185px); }}

/* ── Metrics floating above rooms ─────────────────── */
.metric-float {{
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%) rotateX(-90deg) rotateZ(35deg);
  background: rgba(15,23,42,0.9);
  color: #e2e8f0;
  padding: 0.2rem 0.5rem;
  border-radius: 0.25rem;
  font-size: 0.55rem;
  font-family: "SF Mono", monospace;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s;
}}
.room-3d:hover .metric-float {{
  opacity: 1;
}}

/* ── Ticker (bottom) ──────────────────────────────── */
.ticker-wrap {{
  position: fixed;
  bottom: 0; left: 0; right: 0;
  background: rgba(15,23,42,0.9);
  backdrop-filter: blur(8px);
  padding: 0.5rem 0;
  overflow: hidden;
  white-space: nowrap;
  z-index: 90;
  border-top: 1px solid rgba(255,255,255,0.06);
}}
.ticker-track {{
  display: inline-block;
  animation: ticker-scroll 25s linear infinite;
}}
.ticker-item {{
  display: inline-block;
  padding: 0 1.5rem;
  font-size: 0.75rem;
  font-family: "SF Mono", monospace;
  color: #94a3b8;
}}
.ticker-item .dot {{
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  margin-right: 0.4rem;
  vertical-align: middle;
}}
.dot.ok {{ background: var(--ok); }}
.dot.warn {{ background: var(--warn); }}
.dot.alert {{ background: var(--err); }}
.dot.info {{ background: var(--accent); }}
@keyframes ticker-scroll {{
  0% {{ transform: translateX(0); }}
  100% {{ transform: translateX(-50%); }}
}}

/* ── Detail Panel ─────────────────────────────────── */
.detail-overlay {{
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(6px);
  z-index: 200;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.3s;
}}
.detail-overlay.open {{
  opacity: 1;
  pointer-events: auto;
}}
.detail-panel {{
  position: fixed;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) scale(0.95);
  width: 420px;
  max-width: 90vw;
  max-height: 80vh;
  background: linear-gradient(145deg, #1e293b, #0f172a);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 1rem;
  box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
  z-index: 210;
  display: flex;
  flex-direction: column;
  opacity: 0;
  pointer-events: none;
  transition: all 0.35s cubic-bezier(0.16,1,0.3,1);
}}
.detail-panel.open {{
  opacity: 1;
  pointer-events: auto;
  transform: translate(-50%, -50%) scale(1);
}}
.detail-header {{
  padding: 1.25rem;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.detail-header h2 {{
  font-size: 1.1rem;
  color: #e2e8f0;
  font-weight: 700;
}}
.detail-close {{
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #64748b;
  line-height: 1;
  transition: color 0.15s;
}}
.detail-close:hover {{ color: #e2e8f0; }}
.detail-body {{
  flex: 1;
  padding: 1.25rem;
  overflow-y: auto;
  color: #cbd5e1;
}}
.detail-section {{
  margin-bottom: 1.25rem;
}}
.detail-section h3 {{
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #64748b;
  margin-bottom: 0.5rem;
}}
.detail-metric {{
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  font-size: 0.9rem;
}}
.detail-actions {{
  padding: 1rem 1.25rem;
  border-top: 1px solid rgba(255,255,255,0.08);
  display: flex;
  gap: 0.75rem;
}}
.btn {{
  flex: 1;
  padding: 0.6rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.05);
  color: #e2e8f0;
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.15s;
}}
.btn:hover {{ background: rgba(255,255,255,0.1); border-color: var(--accent); }}
.btn.primary {{
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}}
.btn.primary:hover {{ background: #0284c7; }}

/* ── Controls hint ────────────────────────────────── */
.controls-hint {{
  position: fixed;
  bottom: 48px;
  right: 1rem;
  z-index: 80;
  background: rgba(15,23,42,0.8);
  backdrop-filter: blur(8px);
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  font-size: 0.7rem;
  color: #64748b;
  border: 1px solid rgba(255,255,255,0.06);
}}

/* ── Responsive ───────────────────────────────────── */
@media (max-width: 900px) {{
  .scene {{ transform: rotateX(60deg) rotateZ(-35deg) translateZ(-200px) scale(0.7); }}
}}
@media (max-width: 640px) {{
  .scene {{ transform: rotateX(60deg) rotateZ(-35deg) translateZ(-200px) scale(0.5); }}
  .detail-panel {{ width: 95vw; }}
}}
</style>
</head>
<body>

<header>
  <div>
    <h1>🏢 Apex Corp. HQ</h1>
    <div class="subtitle">3D Isometric Office Dashboard</div>
  </div>
  <div class="clock" id="clock">00:00:00</div>
</header>

<div class="scene-container">
  <div class="scene" id="scene">

    <!-- Floor -->
    <div class="floor"></div>

    <!-- Row 1 -->
    <div class="room-3d" id="room-reception" onclick="openDetail(\'reception\')">
      <div class="face face-top">
        <div class="room-label">Reception</div>
        <div class="room-status-led" id="led-reception"></div>
        <div class="worker-3d">{self._svg_maria()}</div>
        <div class="worker-name">Maria</div>
        <div class="worker-role">Project Profiler</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-reception">—</div>
    </div>

    <div class="room-3d" id="room-board" onclick="openDetail(\'board\')">
      <div class="face face-top">
        <div class="room-label">Board Room</div>
        <div class="room-status-led" id="led-board"></div>
        <div class="worker-3d">{self._svg_boss()}</div>
        <div class="worker-name">Boss</div>
        <div class="worker-role">Smart Planner</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-board">—</div>
    </div>

    <div class="room-3d" id="room-dev" onclick="openDetail(\'dev\')">
      <div class="face face-top">
        <div class="room-label">Dev Office</div>
        <div class="room-status-led" id="led-dev"></div>
        <div class="worker-3d">{self._svg_coder()}</div>
        <div class="worker-name">Coder</div>
        <div class="worker-role">Patch Generator</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-dev">—</div>
    </div>

    <div class="room-3d" id="room-qa" onclick="openDetail(\'qa\')">
      <div class="face face-top">
        <div class="room-label">QA Lab</div>
        <div class="room-status-led" id="led-qa"></div>
        <div class="worker-3d">{self._svg_tester()}</div>
        <div class="worker-name">Tester</div>
        <div class="worker-role">Abductive Reasoner</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-qa">—</div>
    </div>

    <!-- Row 2 -->
    <div class="room-3d" id="room-security" onclick="openDetail(\'security\')">
      <div class="face face-top">
        <div class="room-label">Security</div>
        <div class="room-status-led" id="led-security"></div>
        <div class="worker-3d">{self._svg_guard()}</div>
        <div class="worker-name">Guard</div>
        <div class="worker-role">Safety Governor</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-security">—</div>
    </div>

    <div class="room-3d" id="room-rnd" onclick="openDetail(\'rnd\')">
      <div class="face face-top">
        <div class="room-label">R&D Lab</div>
        <div class="room-status-led" id="led-rnd"></div>
        <div class="worker-3d">{self._svg_prof()}</div>
        <div class="worker-name">Prof</div>
        <div class="worker-role">Recursive Reflection</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-rnd">—</div>
    </div>

    <div class="room-3d" id="room-archive" onclick="openDetail(\'archive\')">
      <div class="face face-top">
        <div class="room-label">Archive</div>
        <div class="room-status-led" id="led-archive"></div>
        <div class="worker-3d">{self._svg_archie()}</div>
        <div class="worker-name">Archie</div>
        <div class="worker-role">Cross-Run Tracker</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-archive">—</div>
    </div>

    <div class="room-3d" id="room-swarm" onclick="openDetail(\'swarm\')">
      <div class="face face-top">
        <div class="room-label">HR / Swarm</div>
        <div class="room-status-led" id="led-swarm"></div>
        <div class="worker-3d">{self._svg_team()}</div>
        <div class="worker-name">Team</div>
        <div class="worker-role">Swarm Coordinator</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-swarm">—</div>
    </div>

    <!-- Row 3 -->
    <div class="room-3d" id="room-break" onclick="openDetail(\'break\')">
      <div class="face face-top">
        <div class="room-label">☕ Break Room</div>
        <div class="room-status-led" id="led-break"></div>
        <div class="worker-3d">{self._svg_barista()}</div>
        <div class="worker-name">Barista</div>
        <div class="worker-role">Telemetry</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-break">—</div>
    </div>

    <div class="room-3d" id="room-gym" onclick="openDetail(\'gym\')">
      <div class="face face-top">
        <div class="room-label">🏋️ Gym</div>
        <div class="room-status-led" id="led-gym"></div>
        <div class="worker-3d">{self._svg_coach()}</div>
        <div class="worker-name">Coach</div>
        <div class="worker-role">System Health</div>
      </div>
      <div class="face face-front"></div>
      <div class="face face-right"></div>
      <div class="metric-float" id="float-gym">—</div>
    </div>

  </div>
</div>

<!-- Ticker -->
<div class="ticker-wrap">
  <div class="ticker-track" id="ticker-track">
    <span class="ticker-item"><span class="dot info"></span>Apex Corp. 3D Office online — All departments operational</span>
    <span class="ticker-item"><span class="dot ok"></span>Zero dependencies — Pure CSS 3D + SVG vector art</span>
  </div>
</div>

<!-- Controls hint -->
<div class="controls-hint">🖱️ Click any room for details • Hover for live metrics</div>

<!-- Detail Panel -->
<div class="detail-overlay" id="detail-overlay" onclick="closeDetail()"></div>
<div class="detail-panel" id="detail-panel">
  <div class="detail-header">
    <h2 id="detail-title">Department</h2>
    <button class="detail-close" onclick="closeDetail()">&times;</button>
  </div>
  <div class="detail-body" id="detail-body"></div>
  <div class="detail-actions">
    <button class="btn" onclick="closeDetail()">Close</button>
    <button class="btn primary" onclick="alert(\'Report feature coming soon!\')">Generate Report</button>
  </div>
</div>

<script>
/* ── Clock ─────────────────────────────────────────── */
function updateClock() {{
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("en-GB");
}}
setInterval(updateClock, 1000);
updateClock();

/* ── Load Data ─────────────────────────────────────── */
async function loadDepartments() {{
  try {{
    const data = await fetch("/api/departments").then(r => r.json());

    function setLed(dept, status) {{
      const el = document.getElementById("led-" + dept);
      if (!el) return;
      el.className = "room-status-led " + (status || "idle");
    }}
    function setFloat(dept, text) {{
      const el = document.getElementById("float-" + dept);
      if (el) el.textContent = text;
    }}

    setLed("reception", data.reception.status);
    setFloat("reception", data.reception.total_files + " files");

    setLed("board", data.board.status);
    setFloat("board", data.board.open_claims + " claims");

    setLed("dev", data.dev.status);
    setFloat("dev", data.dev.transforms_available + " transforms");

    setLed("qa", data.qa.status);
    setFloat("qa", data.qa.issues_found + " issues");

    setLed("security", data.security.status);
    setFloat("security", data.security.risky_functions + " risks");

    setLed("rnd", data.rnd.status);
    setFloat("rnd", "depth " + data.rnd.reflection_depth);

    setLed("archive", data.archive.status);
    setFloat("archive", data.archive.total_runs + " runs");

    setLed("swarm", data.swarm.status);
    setFloat("swarm", data.swarm.active_workers + "/" + data.swarm.max_workers);

    setLed("break", data.break.status);
    setFloat("break", "$" + data.break.session_cost_usd.toFixed(4));

    setLed("gym", data.gym.status);
    setFloat("gym", data.gym.system_health + "% health");
  }} catch(e) {{
    console.error("Failed to load departments", e);
  }}
}}

/* ── Ticker ────────────────────────────────────────── */
async function loadTicker() {{
  try {{
    const data = await fetch("/api/ticker").then(r => r.json());
    const track = document.getElementById("ticker-track");
    const items = data.events.map(ev => {{
      const cls = ev.severity === "alert" ? "alert" : ev.severity === "warn" ? "warn" : ev.severity === "ok" ? "ok" : "info";
      return `<span class="ticker-item"><span class="dot ${{cls}}"></span>${{ev.time}} — ${{ev.msg}}</span>`;
    }}).join("");
    track.innerHTML = items + items;
  }} catch(e) {{
    console.error("Ticker load failed", e);
  }}
}}

/* ── Detail Panel ──────────────────────────────────── */
const deptNames = {{
  reception: "Reception — Maria",
  board: "Board Room — Boss",
  dev: "Dev Office — Coder",
  qa: "QA Lab — Tester",
  security: "Security Office — Guard",
  rnd: "R&D Lab — Prof",
  archive: "Archive Room — Archie",
  swarm: "HR / Swarm — Team",
  break: "Break Room — Barista",
  gym: "Gym / Recovery — Coach",
}};

async function openDetail(dept) {{
  document.getElementById("detail-title").textContent = deptNames[dept] || dept;
  const body = document.getElementById("detail-body");
  body.innerHTML = `<div style="text-align:center;padding:2rem 0;color:#64748b;">Loading...</div>`;
  document.getElementById("detail-overlay").classList.add("open");
  document.getElementById("detail-panel").classList.add("open");

  try {{
    const all = await fetch("/api/departments").then(r => r.json());
    const info = all[dept];
    if (!info) throw new Error("No data");
    let html = `<div class="detail-section"><h3>Status</h3>`;
    html += `<div class="detail-metric"><span>Current State</span><span style="text-transform:uppercase;font-weight:700;color:var(--accent);">${{info.status}}</span></div>`;
    html += `<div class="detail-metric"><span>Last Action</span><span>${{info.last_action}}</span></div>`;
    html += `</div><div class="detail-section"><h3>Metrics</h3>`;
    Object.entries(info).forEach(([k, v]) => {{
      if (k === "status" || k === "last_action" || k === "transforms_list") return;
      let display = v;
      if (Array.isArray(v)) display = v.length + " items";
      else if (typeof v === "number" && k.includes("confidence")) display = v.toFixed(2);
      else if (typeof v === "number" && k.includes("cost")) display = "$" + v.toFixed(4);
      else if (v === null || v === undefined) display = "—";
      html += `<div class="detail-metric"><span>${{k.replace(/_/g, " ")}}</span><span>${{display}}</span></div>`;
    }});
    if (info.transforms_list) {{
      html += `</div><div class="detail-section"><h3>Available Transforms</h3>`;
      html += `<div style="display:flex;flex-wrap:wrap;gap:0.35rem;">`;
      info.transforms_list.forEach(t => {{
        html += `<span style="background:rgba(255,255,255,0.06);padding:0.25rem 0.5rem;border-radius:0.25rem;font-size:0.75rem;border:1px solid rgba(255,255,255,0.08);">${{t}}</span>`;
      }});
      html += `</div>`;
    }}
    html += `</div>`;
    body.innerHTML = html;
  }} catch(e) {{
    body.innerHTML = `<div style="color:var(--err);text-align:center;padding:2rem 0;">Failed to load details</div>`;
  }}
}}

function closeDetail() {{
  document.getElementById("detail-overlay").classList.remove("open");
  document.getElementById("detail-panel").classList.remove("open");
}}

/* ── Init ──────────────────────────────────────────── */
loadDepartments();
loadTicker();
setInterval(loadDepartments, 10000);
setInterval(loadTicker, 30000);
</script>

</body>
</html>'''


class DashboardServer:
    """Run the Apex 3D Office Dashboard HTTP server."""

    def __init__(self, project_root: str = ".", host: str = "127.0.0.1", port: int = 8686) -> None:
        self.project_root = project_root
        self.host = host
        self.port = port
        DashboardHandler.project_root = project_root
        self.server = HTTPServer((host, port), DashboardHandler)

    def run(self) -> None:
        print(f"Apex 3D Office Dashboard: http://{self.host}:{self.port}")
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apex Orchestrator 3D Office Dashboard")
    parser.add_argument("--port", type=int, default=8686, help="Port to run the dashboard on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the dashboard to")
    args = parser.parse_args()

    server = DashboardServer(host=args.host, port=args.port)
    server.run()
