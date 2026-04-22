from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from app.engine.dashboard_data import DashboardDataCollector


class DashboardHandler(BaseHTTPRequestHandler):
    """Serve the Real 3D Three.js Apex Office Dashboard."""

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

    def _render_dashboard(self) -> str:
        return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Apex Corp. — Real 3D Office</title>
<style>
:root {
  --ok: #22c55e; --warn: #f59e0b; --err: #ef4444; --accent: #0ea5e9;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  overflow: hidden;
  background: #0f172a;
  color: #e2e8f0;
}

/* ── Header ───────────────────────────────────────── */
header {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 100;
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
header h1 { font-size: 1.1rem; font-weight: 700; }
header .subtitle { font-size: 0.7rem; color: #94a3b8; }
.clock {
  font-family: "SF Mono", monospace;
  font-size: 0.9rem;
  color: #38bdf8;
  background: rgba(0,0,0,0.3);
  padding: 0.3rem 0.75rem;
  border-radius: 0.375rem;
}

/* ── Canvas Container ─────────────────────────────── */
#canvas-container {
  width: 100vw;
  height: 100vh;
  position: fixed;
  top: 0; left: 0;
}
canvas { display: block; }

/* ── Tooltip ──────────────────────────────────────── */
.tooltip {
  position: fixed;
  background: rgba(15,23,42,0.95);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  pointer-events: none;
  z-index: 50;
  display: none;
  font-size: 0.85rem;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
  backdrop-filter: blur(8px);
}
.tooltip .dept-name { font-weight: 700; color: var(--accent); font-size: 0.95rem; }
.tooltip .worker-name { color: #94a3b8; font-size: 0.75rem; margin-top: 0.15rem; }
.tooltip .metric { margin-top: 0.35rem; font-family: "SF Mono", monospace; font-size: 0.7rem; color: #cbd5e1; }

/* ── Detail Panel ─────────────────────────────────── */
.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(6px);
  z-index: 200;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.3s;
}
.detail-overlay.open { opacity: 1; pointer-events: auto; }
.detail-panel {
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
}
.detail-panel.open { opacity: 1; pointer-events: auto; transform: translate(-50%, -50%) scale(1); }
.detail-header {
  padding: 1.25rem;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.detail-header h2 { font-size: 1.1rem; color: #e2e8f0; font-weight: 700; }
.detail-close {
  background: none; border: none; font-size: 1.5rem;
  cursor: pointer; color: #64748b; line-height: 1;
}
.detail-close:hover { color: #e2e8f0; }
.detail-body { flex: 1; padding: 1.25rem; overflow-y: auto; color: #cbd5e1; }
.detail-section { margin-bottom: 1.25rem; }
.detail-section h3 {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: #64748b; margin-bottom: 0.5rem;
}
.detail-metric {
  display: flex; justify-content: space-between;
  padding: 0.5rem 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  font-size: 0.9rem;
}
.detail-actions {
  padding: 1rem 1.25rem;
  border-top: 1px solid rgba(255,255,255,0.08);
  display: flex; gap: 0.75rem;
}
.btn {
  flex: 1; padding: 0.6rem; border-radius: 0.5rem;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.05);
  color: #e2e8f0; font-weight: 600; font-size: 0.85rem;
  cursor: pointer; transition: all 0.15s;
}
.btn:hover { background: rgba(255,255,255,0.1); border-color: var(--accent); }
.btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }

/* ── Ticker ───────────────────────────────────────── */
.ticker-wrap {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  background: rgba(15,23,42,0.9);
  backdrop-filter: blur(8px);
  padding: 0.5rem 0;
  overflow: hidden;
  white-space: nowrap;
  z-index: 90;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.ticker-track { display: inline-block; animation: ticker-scroll 25s linear infinite; }
.ticker-item {
  display: inline-block;
  padding: 0 1.5rem;
  font-size: 0.75rem;
  font-family: "SF Mono", monospace;
  color: #94a3b8;
}
.ticker-item .dot {
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; margin-right: 0.4rem; vertical-align: middle;
}
.dot.ok { background: var(--ok); }
.dot.warn { background: var(--warn); }
.dot.alert { background: var(--err); }
.dot.info { background: var(--accent); }
@keyframes ticker-scroll { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }

/* ── Controls hint ────────────────────────────────── */
.controls-hint {
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
}

/* ── Loading ──────────────────────────────────────── */
#loading {
  position: fixed;
  inset: 0;
  background: #0f172a;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 300;
  transition: opacity 0.5s;
}
#loading.hidden { opacity: 0; pointer-events: none; }
#loading h2 { color: #38bdf8; font-size: 1.5rem; margin-bottom: 1rem; }
#loading p { color: #64748b; font-size: 0.9rem; }
.spinner {
  width: 40px; height: 40px;
  border: 3px solid rgba(56,189,248,0.2);
  border-top-color: #38bdf8;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }
}
</script>
<!-- Fallback: force hide loading screen after 5s no matter what -->
<script>
  window._apexForceHideLoading = setTimeout(function() {
    var el = document.getElementById("loading");
    if (el) { el.classList.add("hidden"); setTimeout(function(){el.remove();}, 500); }
    var err = document.getElementById("error-msg");
    if (err && !window._apex3DLoaded) err.style.display = "block";
  }, 5000);
  window.addEventListener("error", function(e) {
    console.error("Apex 3D Error:", e.message);
    var err = document.getElementById("error-msg");
    if (err) { err.style.display = "block"; err.textContent = "3D Load Error: " + e.message; }
  });
</script>
</head>
<body>

<div id="loading">
  <div class="spinner"></div>
  <h2>🏢 Apex Corp. HQ</h2>
  <p>Loading 3D Office...</p>
  <p id="error-msg" style="display:none;color:#ef4444;margin-top:1rem;font-size:0.85rem;">Failed to load Three.js. Check internet connection.</p>
</div>

<header>
  <div>
    <h1>🏢 Apex Corp. HQ</h1>
    <div class="subtitle">Real 3D Office — Three.js WebGL</div>
  </div>
  <div class="clock" id="clock">00:00:00</div>
</header>

<div id="canvas-container"></div>

<div class="tooltip" id="tooltip">
  <div class="dept-name" id="tooltip-dept"></div>
  <div class="worker-name" id="tooltip-worker"></div>
  <div class="metric" id="tooltip-metric"></div>
</div>

<div class="ticker-wrap">
  <div class="ticker-track" id="ticker-track">
    <span class="ticker-item"><span class="dot info"></span>Apex Corp. 3D Office online — Three.js WebGL</span>
    <span class="ticker-item"><span class="dot ok"></span>Drag to rotate • Scroll to zoom • Click room for details</span>
  </div>
</div>

<div class="controls-hint">🖱️ Drag = rotate • Scroll = zoom • Click = details</div>

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

<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/* ── Clock ─────────────────────────────────────────── */
function updateClock() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("en-GB");
}
setInterval(updateClock, 1000);
updateClock();

/* ── Scene Setup ───────────────────────────────────── */
const container = document.getElementById("canvas-container");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0f172a);
scene.fog = new THREE.Fog(0x0f172a, 15, 40);

const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(12, 10, 12);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.maxPolarAngle = Math.PI / 2.2;
controls.minDistance = 5;
controls.maxDistance = 30;
controls.target.set(0, 0, 0);

/* ── Lighting ──────────────────────────────────────── */
const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
scene.add(ambientLight);

const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
dirLight.position.set(10, 15, 10);
dirLight.castShadow = true;
dirLight.shadow.mapSize.width = 2048;
dirLight.shadow.mapSize.height = 2048;
dirLight.shadow.camera.near = 0.1;
dirLight.shadow.camera.far = 50;
dirLight.shadow.camera.left = -15;
dirLight.shadow.camera.right = 15;
dirLight.shadow.camera.top = 15;
dirLight.shadow.camera.bottom = -15;
scene.add(dirLight);

const pointLight = new THREE.PointLight(0x38bdf8, 0.5, 20);
pointLight.position.set(0, 8, 0);
scene.add(pointLight);

/* ── Floor ─────────────────────────────────────────── */
const floorGeo = new THREE.PlaneGeometry(30, 30);
const floorMat = new THREE.MeshStandardMaterial({
  color: 0x1e293b,
  roughness: 0.8,
  metalness: 0.1,
});
const floor = new THREE.Mesh(floorGeo, floorMat);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

// Grid
const gridHelper = new THREE.GridHelper(30, 30, 0x334155, 0x1e293b);
gridHelper.position.y = 0.01;
scene.add(gridHelper);

/* ── Character Builder ─────────────────────────────── */
function createCharacter(colors, animType) {
  const group = new THREE.Group();

  const headGeo = new THREE.BoxGeometry(0.28, 0.32, 0.28);
  const headMat = new THREE.MeshStandardMaterial({ color: colors.skin });
  const head = new THREE.Mesh(headGeo, headMat);
  head.position.y = 1.45;
  head.castShadow = true;
  group.add(head);

  // Hair
  const hairGeo = new THREE.BoxGeometry(0.3, 0.12, 0.3);
  const hairMat = new THREE.MeshStandardMaterial({ color: colors.hair });
  const hair = new THREE.Mesh(hairGeo, hairMat);
  hair.position.y = 1.62;
  group.add(hair);

  // Body
  const bodyGeo = new THREE.BoxGeometry(0.38, 0.5, 0.22);
  const bodyMat = new THREE.MeshStandardMaterial({ color: colors.shirt });
  const body = new THREE.Mesh(bodyGeo, bodyMat);
  body.position.y = 1.0;
  body.castShadow = true;
  group.add(body);

  // Arms
  const armGeo = new THREE.BoxGeometry(0.1, 0.42, 0.1);
  const armMat = new THREE.MeshStandardMaterial({ color: colors.shirt });
  const leftArm = new THREE.Mesh(armGeo, armMat);
  leftArm.position.set(-0.28, 1.05, 0);
  leftArm.castShadow = true;
  group.add(leftArm);

  const rightArm = new THREE.Mesh(armGeo, armMat);
  rightArm.position.set(0.28, 1.05, 0);
  rightArm.castShadow = true;
  group.add(rightArm);

  // Hands
  const handGeo = new THREE.BoxGeometry(0.08, 0.08, 0.08);
  const handMat = new THREE.MeshStandardMaterial({ color: colors.skin });
  const leftHand = new THREE.Mesh(handGeo, handMat);
  leftHand.position.set(-0.28, 0.78, 0);
  group.add(leftHand);
  const rightHand = new THREE.Mesh(handGeo, handMat);
  rightHand.position.set(0.28, 0.78, 0);
  group.add(rightHand);

  // Legs
  const legGeo = new THREE.BoxGeometry(0.13, 0.5, 0.14);
  const legMat = new THREE.MeshStandardMaterial({ color: colors.pants });
  const leftLeg = new THREE.Mesh(legGeo, legMat);
  leftLeg.position.set(-0.1, 0.45, 0);
  leftLeg.castShadow = true;
  group.add(leftLeg);

  const rightLeg = new THREE.Mesh(legGeo, legMat);
  rightLeg.position.set(0.1, 0.45, 0);
  rightLeg.castShadow = true;
  group.add(rightLeg);

  // Shoes
  const shoeGeo = new THREE.BoxGeometry(0.14, 0.06, 0.18);
  const shoeMat = new THREE.MeshStandardMaterial({ color: 0x1e1e1e });
  const leftShoe = new THREE.Mesh(shoeGeo, shoeMat);
  leftShoe.position.set(-0.1, 0.17, 0.02);
  group.add(leftShoe);
  const rightShoe = new THREE.Mesh(shoeGeo, shoeMat);
  rightShoe.position.set(0.1, 0.17, 0.02);
  group.add(rightShoe);

  // Status light above head
  const lightGeo = new THREE.SphereGeometry(0.06, 8, 8);
  const lightMat = new THREE.MeshBasicMaterial({ color: 0x22c55e });
  const statusLight = new THREE.Mesh(lightGeo, lightMat);
  statusLight.position.y = 1.8;
  group.add(statusLight);

  group.userData = { animType, parts: { leftArm, rightArm, leftHand, rightHand, head, statusLight } };
  return { group, statusLight };
}

/* ── Room Builder ──────────────────────────────────── */
function createRoom(width, depth, wallColor, x, z) {
  const group = new THREE.Group();
  group.position.set(x, 0, z);

  // Floor
  const floorGeo = new THREE.BoxGeometry(width, 0.08, depth);
  const floorMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.7 });
  const roomFloor = new THREE.Mesh(floorGeo, floorMat);
  roomFloor.position.y = 0.04;
  roomFloor.receiveShadow = true;
  group.add(roomFloor);

  // Walls (only 2 visible walls for isometric feel)
  const wallH = 0.6;
  const wallThick = 0.05;

  // Back wall
  const backWallGeo = new THREE.BoxGeometry(width, wallH, wallThick);
  const wallMat = new THREE.MeshStandardMaterial({ color: wallColor, transparent: true, opacity: 0.3 });
  const backWall = new THREE.Mesh(backWallGeo, wallMat);
  backWall.position.set(0, wallH / 2, -depth / 2 + wallThick / 2);
  group.add(backWall);

  // Side wall
  const sideWallGeo = new THREE.BoxGeometry(wallThick, wallH, depth);
  const sideWall = new THREE.Mesh(sideWallGeo, wallMat);
  sideWall.position.set(-width / 2 + wallThick / 2, wallH / 2, 0);
  group.add(sideWall);

  // Outline
  const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(width, 0.02, depth));
  const lineMat = new THREE.LineBasicMaterial({ color: 0x475569 });
  const outline = new THREE.LineSegments(edges, lineMat);
  outline.position.y = 0.05;
  group.add(outline);

  return group;
}

/* ── Department Data ───────────────────────────────── */
const departments = [
  { id: "reception", name: "Reception", worker: "Maria", role: "Project Profiler", x: -4, z: -3, w: 2.2, d: 1.6, color: 0x0ea5e9, charColors: { skin: 0xfcd34d, hair: 0x1e1e1e, shirt: 0xdc2626, pants: 0x1e293b } },
  { id: "board",     name: "Board Room", worker: "Boss", role: "Smart Planner", x: -1, z: -3, w: 2.2, d: 1.6, color: 0x1e3a8a, charColors: { skin: 0xfcd34d, hair: 0x475569, shirt: 0x1e3a8a, pants: 0x1e3a8a } },
  { id: "dev",       name: "Dev Office", worker: "Coder", role: "Patch Generator", x: 2, z: -3, w: 2.2, d: 1.6, color: 0x22c55e, charColors: { skin: 0xfcd34d, hair: 0x64748b, shirt: 0x22c55e, pants: 0x334155 } },
  { id: "qa",        name: "QA Lab", worker: "Tester", role: "Abductive Reasoner", x: 5, z: -3, w: 2.2, d: 1.6, color: 0xf59e0b, charColors: { skin: 0xfcd34d, hair: 0xa16207, shirt: 0xffffff, pants: 0x64748b } },
  { id: "security",  name: "Security", worker: "Guard", role: "Safety Governor", x: -4, z: 0, w: 2.2, d: 1.6, color: 0x1e40af, charColors: { skin: 0xfcd34d, hair: 0x1e3a8a, shirt: 0x1e40af, pants: 0x1e40af } },
  { id: "rnd",       name: "R&D Lab", worker: "Prof", role: "Recursive Reflection", x: -1, z: 0, w: 2.2, d: 1.6, color: 0xf97316, charColors: { skin: 0xfcd34d, hair: 0xe2e8f0, shirt: 0xffffff, pants: 0x475569 } },
  { id: "archive",   name: "Archive", worker: "Archie", role: "Cross-Run Tracker", x: 2, z: 0, w: 2.2, d: 1.6, color: 0x78716c, charColors: { skin: 0xfcd34d, hair: 0x78716c, shirt: 0x92400e, pants: 0x78716c } },
  { id: "swarm",     name: "HR / Swarm", worker: "Team", role: "Swarm Coordinator", x: 5, z: 0, w: 2.2, d: 1.6, color: 0x64748b, charColors: { skin: 0xfcd34d, hair: 0x1e293b, shirt: 0x64748b, pants: 0x334155 } },
  { id: "break",     name: "☕ Break Room", worker: "Barista", role: "Telemetry", x: -1.5, z: 3, w: 3.2, d: 1.6, color: 0xef4444, charColors: { skin: 0xfcd34d, hair: 0x475569, shirt: 0xffffff, pants: 0x334155 } },
  { id: "gym",       name: "🏋️ Gym", worker: "Coach", role: "System Health", x: 2.5, z: 3, w: 3.2, d: 1.6, color: 0xf97316, charColors: { skin: 0xfcd34d, hair: 0xc2410c, shirt: 0xf97316, pants: 0xf97316 } },
];

/* ── Build Scene ───────────────────────────────────── */
const roomMeshes = [];
const characterMeshes = [];

const deptData = {};

for (const dept of departments) {
  const room = createRoom(dept.w, dept.d, dept.color, dept.x, dept.z);
  scene.add(room);

  const charResult = createCharacter(dept.charColors);
  const charGroup = charResult.group;
  charGroup.position.set(dept.x, 0, dept.z + 0.2);
  scene.add(charGroup);

  roomMeshes.push({ mesh: room, id: dept.id, name: dept.name, worker: dept.worker });
  characterMeshes.push({ mesh: charGroup, id: dept.id, name: dept.name, worker: dept.worker, statusLight: charResult.statusLight });

  deptData[dept.id] = dept;
}

/* ── Raycasting ────────────────────────────────────── */
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
const tooltip = document.getElementById("tooltip");

function onMouseMove(event) {
  mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
  mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);

  let hovered = null;
  for (const rm of roomMeshes) {
    const intersects = raycaster.intersectObjects(rm.mesh.children, true);
    if (intersects.length > 0) {
      hovered = rm;
      break;
    }
  }

  if (hovered) {
    tooltip.style.display = "block";
    tooltip.style.left = (event.clientX + 15) + "px";
    tooltip.style.top = (event.clientY + 15) + "px";
    document.getElementById("tooltip-dept").textContent = hovered.name;
    document.getElementById("tooltip-worker").textContent = hovered.worker;
    const metric = (deptMetrics[hovered.id] || "Loading...");
    document.getElementById("tooltip-metric").textContent = metric;
    document.body.style.cursor = "pointer";
  } else {
    tooltip.style.display = "none";
    document.body.style.cursor = "default";
  }
}

function onClick(event) {
  mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
  mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);

  for (const rm of roomMeshes) {
    const intersects = raycaster.intersectObjects(rm.mesh.children, true);
    if (intersects.length > 0) {
      openDetail(rm.id);
      break;
    }
  }
}

window.addEventListener("mousemove", onMouseMove);
window.addEventListener("click", onClick);
window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

/* ── Animations ────────────────────────────────────── */
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();

  // Animate characters
  for (const cm of characterMeshes) {
    const parts = cm.mesh.userData.parts;
    if (!parts) continue;

    const deptId = cm.id;
    if (deptId === "dev") {
      // Typing
      parts.leftArm.rotation.x = Math.sin(t * 8) * 0.3;
      parts.rightArm.rotation.x = Math.sin(t * 8 + 1) * 0.3;
      parts.leftHand.position.y = 0.78 + Math.sin(t * 8) * 0.02;
      parts.rightHand.position.y = 0.78 + Math.sin(t * 8 + 1) * 0.02;
    } else if (deptId === "security") {
      // Scanning
      cm.mesh.rotation.y = Math.sin(t * 1.5) * 0.5;
    } else if (deptId === "barista" || deptId === "break") {
      // Coffee sip
      parts.rightArm.rotation.x = -0.5 + Math.sin(t * 2) * 0.2;
    } else if (deptId === "gym") {
      // Walking in place
      parts.leftLeg.rotation.x = Math.sin(t * 5) * 0.3;
      parts.rightLeg.rotation.x = Math.sin(t * 5 + Math.PI) * 0.3;
      cm.mesh.position.y = Math.abs(Math.sin(t * 5)) * 0.03;
    } else if (deptId === "rnd") {
      // Thinking
      parts.leftArm.rotation.z = 0.3 + Math.sin(t * 2) * 0.1;
      parts.head.rotation.y = Math.sin(t * 0.8) * 0.15;
    }
  }

  controls.update();
  renderer.render(scene, camera);
}

/* ── Data Loading ──────────────────────────────────── */
let deptMetrics = {};

async function loadDepartments() {
  try {
    const data = await fetch("/api/departments").then(r => r.json());
    for (const [id, info] of Object.entries(data)) {
      let metric = "";
      if (info.total_files !== undefined) metric = info.total_files + " files";
      else if (info.open_claims !== undefined) metric = info.open_claims + " claims";
      else if (info.transforms_available !== undefined) metric = info.transforms_available + " transforms";
      else if (info.issues_found !== undefined) metric = info.issues_found + " issues";
      else if (info.risky_functions !== undefined) metric = info.risky_functions + " risks";
      else if (info.reflection_depth !== undefined) metric = "depth " + info.reflection_depth;
      else if (info.total_runs !== undefined) metric = info.total_runs + " runs";
      else if (info.active_workers !== undefined) metric = info.active_workers + "/" + info.max_workers;
      else if (info.session_cost_usd !== undefined) metric = "$" + info.session_cost_usd.toFixed(4);
      else if (info.system_health !== undefined) metric = info.system_health + "% health";
      deptMetrics[id] = metric;

      // Update status light color
      const cm = characterMeshes.find(c => c.id === id);
      if (cm && cm.statusLight) {
        const status = info.status || "idle";
        const color = status === "alert" ? 0xef4444 : status === "warn" || status === "busy" ? 0xf59e0b : status === "thinking" ? 0x0ea5e9 : 0x22c55e;
        cm.statusLight.material.color.setHex(color);
      }
    }
  } catch(e) { console.error("Failed to load departments", e); }
}

async function loadTicker() {
  try {
    const data = await fetch("/api/ticker").then(r => r.json());
    const track = document.getElementById("ticker-track");
    const items = data.events.map(ev => {
      const cls = ev.severity === "alert" ? "alert" : ev.severity === "warn" ? "warn" : ev.severity === "ok" ? "ok" : "info";
      return `<span class="ticker-item"><span class="dot ${cls}"></span>${ev.time} — ${ev.msg}</span>`;
    }).join("");
    track.innerHTML = items + items;
  } catch(e) { console.error("Ticker load failed", e); }
}

/* ── Detail Panel ──────────────────────────────────── */
const deptNames = {
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
};

async function openDetail(dept) {
  document.getElementById("detail-title").textContent = deptNames[dept] || dept;
  const body = document.getElementById("detail-body");
  body.innerHTML = `<div style="text-align:center;padding:2rem 0;color:#64748b;">Loading...</div>`;
  document.getElementById("detail-overlay").classList.add("open");
  document.getElementById("detail-panel").classList.add("open");

  try {
    const all = await fetch("/api/departments").then(r => r.json());
    const info = all[dept];
    if (!info) throw new Error("No data");
    let html = `<div class="detail-section"><h3>Status</h3>`;
    html += `<div class="detail-metric"><span>Current State</span><span style="text-transform:uppercase;font-weight:700;color:var(--accent);">${info.status}</span></div>`;
    html += `<div class="detail-metric"><span>Last Action</span><span>${info.last_action}</span></div>`;
    html += `</div><div class="detail-section"><h3>Metrics</h3>`;
    Object.entries(info).forEach(([k, v]) => {
      if (k === "status" || k === "last_action" || k === "transforms_list") return;
      let display = v;
      if (Array.isArray(v)) display = v.length + " items";
      else if (typeof v === "number" && k.includes("confidence")) display = v.toFixed(2);
      else if (typeof v === "number" && k.includes("cost")) display = "$" + v.toFixed(4);
      else if (v === null || v === undefined) display = "—";
      html += `<div class="detail-metric"><span>${k.replace(/_/g, " ")}</span><span>${display}</span></div>`;
    });
    if (info.transforms_list) {
      html += `</div><div class="detail-section"><h3>Available Transforms</h3>`;
      html += `<div style="display:flex;flex-wrap:wrap;gap:0.35rem;">`;
      info.transforms_list.forEach(t => {
        html += `<span style="background:rgba(255,255,255,0.06);padding:0.25rem 0.5rem;border-radius:0.25rem;font-size:0.75rem;border:1px solid rgba(255,255,255,0.08);">${t}</span>`;
      });
      html += `</div>`;
    }
    html += `</div>`;
    body.innerHTML = html;
  } catch(e) {
    body.innerHTML = `<div style="color:var(--err);text-align:center;padding:2rem 0;">Failed to load details</div>`;
  }
}

function closeDetail() {
  document.getElementById("detail-overlay").classList.remove("open");
  document.getElementById("detail-panel").classList.remove("open");
}

window.openDetail = openDetail;
window.closeDetail = closeDetail;

/* ── Init ──────────────────────────────────────────── */
window._apex3DLoaded = true;
if (window._apexForceHideLoading) clearTimeout(window._apexForceHideLoading);

loadDepartments();
loadTicker();
setInterval(loadDepartments, 10000);
setInterval(loadTicker, 30000);

// Hide loading screen after a moment
setTimeout(() => {
  var el = document.getElementById("loading");
  if (el) { el.classList.add("hidden"); setTimeout(function(){el.remove();}, 500); }
}, 1500);

animate();
</script>

</body>
</html>'''


class DashboardServer:
    """Run the Apex Real 3D Office Dashboard HTTP server."""

    def __init__(self, project_root: str = ".", host: str = "127.0.0.1", port: int = 8686) -> None:
        self.project_root = project_root
        self.host = host
        self.port = port
        DashboardHandler.project_root = project_root
        self.server = HTTPServer((host, port), DashboardHandler)

    def run(self) -> None:
        print(f"Apex Real 3D Office Dashboard: http://{self.host}:{self.port}")
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apex Orchestrator Real 3D Office Dashboard")
    parser.add_argument("--port", type=int, default=8686, help="Port to run the dashboard on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the dashboard to")
    args = parser.parse_args()

    server = DashboardServer(host=args.host, port=args.port)
    server.run()
