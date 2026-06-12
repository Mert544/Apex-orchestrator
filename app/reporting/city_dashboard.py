"""3D "company city" dashboard — the codebase rendered as a living office.

Every named module becomes a desk/workstation (a file-stack whose height ∝
lines of code, a monitor lit in the module's health colour), laid out in
department sections by top-level package. Apex's own agents become 3D
workers who walk the office floor to the desks they care about: the security auditor heads
for modules with findings, the test engineer for untested modules, the architect
for dependency hubs and fragile hubs. It is the same real, deterministic
ProjectProfile + scan data the flat dashboard uses — just embodied as a place.

Output is a single self-contained HTML file. Three.js is loaded from a CDN at
view time (in the user's browser); everything else — the city model and the
animation — is inlined, so the file works offline once the library is cached.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _module_set(profile: Any) -> list[str]:
    """Named modules to render, prioritising the structurally interesting ones."""
    coverage = getattr(profile, "module_to_tests", {}) or {}
    ordered = list(coverage.keys())
    # Make sure hubs / fragile / untested are present even if coverage missed them.
    for extra in (
        list(getattr(profile, "dependency_hubs", []) or [])
        + list(getattr(profile, "fragile_modules", []) or [])
        + list(getattr(profile, "untested_modules", []) or [])
    ):
        if extra not in ordered:
            ordered.append(extra)
    return [m for m in ordered if isinstance(m, str) and m.endswith(".py")]


def build_city_model(project_root: str, max_buildings: int = 60) -> dict[str, Any]:
    """Assemble the deterministic city model from real project signals."""
    from app.engine.health_score import grade
    from app.tools.code_metrics import CodeMetrics
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(project_root).profile()

    # Security findings per file (excluding fixtures is the grader's job; here we
    # show the raw picture so a worker visibly has somewhere to go).
    findings_by_file: dict[str, int] = {}
    try:
        from app.agents.skills import SecurityAgent

        sec = SecurityAgent().run(project_root=project_root)
        for f in sec.get("findings", []) or []:
            fp = str(f.get("file", ""))
            findings_by_file[fp] = findings_by_file.get(fp, 0) + 1
    except Exception:
        pass

    # Fan-in from the dependency graph (how many modules import this one).
    fan_in: dict[str, int] = {}
    for src, dst in getattr(profile, "dependency_edges", []) or []:
        fan_in[dst] = fan_in.get(dst, 0) + 1

    untested = set(getattr(profile, "untested_modules", []) or [])
    hubs = set(getattr(profile, "dependency_hubs", []) or [])
    fragile = set(getattr(profile, "fragile_modules", []) or [])
    coverage = getattr(profile, "module_to_tests", {}) or {}

    modules = _module_set(profile)
    metrics = CodeMetrics(project_root).for_modules(modules)

    # Rank so that, when we cap, the most meaningful buildings survive.
    def _rank(m: str) -> tuple:
        return (
            findings_by_file.get(m, 0),
            1 if m in fragile else 0,
            1 if m in hubs else 0,
            1 if m in untested else 0,
            fan_in.get(m, 0),
            metrics[m].loc if m in metrics else 0,
        )

    modules = sorted(modules, key=_rank, reverse=True)[:max_buildings]

    buildings: list[dict[str, Any]] = []
    for m in modules:
        mm = metrics.get(m)
        loc = mm.loc if mm else 0
        complexity = mm.complexity if mm else 0
        nfind = findings_by_file.get(m, 0)
        if nfind:
            health = "security"
        elif m in fragile:
            health = "fragile"
        elif m in untested:
            health = "untested"
        elif m in hubs:
            health = "hub"
        else:
            health = "ok"
        dept = m.split("/")[0] if "/" in m else "."
        buildings.append({
            "name": m,
            "dept": dept,
            "loc": loc,
            "complexity": complexity,
            "fan_in": fan_in.get(m, 0),
            "findings": nfind,
            "tests": len(coverage.get(m, []) or []),
            "health": health,
        })

    # Index helpers for assigning workers their rounds.
    idx = {b["name"]: i for i, b in enumerate(buildings)}

    # Dependency "roads": real import edges between rendered buildings.
    edges: list[list[int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for src, dst in getattr(profile, "dependency_edges", []) or []:
        si, di = idx.get(src), idx.get(dst)
        if si is None or di is None or si == di:
            continue
        key = (si, di)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append([si, di])
        if len(edges) >= 160:  # keep the scene readable and fast
            break

    def _targets(pred) -> list[int]:
        return [i for i, b in enumerate(buildings) if pred(b)]

    sec_targets = _targets(lambda b: b["findings"] > 0)
    test_targets = _targets(lambda b: b["health"] == "untested")
    arch_targets = _targets(lambda b: b["health"] in ("hub", "fragile") or b["fan_in"] >= 2)
    doc_targets = _targets(lambda b: b["tests"] == 0)

    all_idx = list(range(len(buildings)))
    workers: list[dict[str, Any]] = []

    def _add_worker(role: str, color: str, targets: list[int]) -> None:
        route = targets or all_idx
        if not route:
            return
        workers.append({"role": role, "color": color, "route": route})

    # One auditor per ~4 finding-sites (so a heavy file visibly draws a crowd),
    # capped; the rest are single specialists. Deterministic counts.
    n_auditors = max(1, min(4, (len(sec_targets) + 3) // 4)) if sec_targets else 1
    for _ in range(n_auditors):
        _add_worker("Security Auditor", "#ff4d4d", sec_targets)
    _add_worker("Test Engineer", "#1fc8a9", test_targets)
    _add_worker("Test Engineer", "#1fc8a9", test_targets)
    _add_worker("Architect", "#4d9bff", arch_targets)
    _add_worker("Doc Writer", "#b07cff", doc_targets)
    _add_worker("Refactorer", "#ffd24d", _targets(lambda b: b["complexity"] >= 12))

    try:
        g = grade(project_root)
        health = {"score": g.score, "letter": g.letter}
    except Exception:
        health = {"score": 0, "letter": "?"}

    return {
        "project": project_root,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "grade": health,
        "totals": {
            "buildings": len(buildings),
            "findings": sum(b["findings"] for b in buildings),
            "untested": sum(1 for b in buildings if b["health"] == "untested"),
            "workers": len(workers),
            "loc": sum(b["loc"] for b in buildings),
        },
        "buildings": buildings,
        "workers": workers,
        "edges": edges,
    }


def build_city(project_root: str) -> str:
    """Build the self-contained 3D city dashboard HTML."""
    model = build_city_model(project_root)
    data_json = json.dumps(model, separators=(",", ":"))
    return _HTML_TEMPLATE.replace("/*__DATA__*/", data_json)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Apex — Office Floor</title>
<style>
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:#0a0e17; color:#dce6ff;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; overflow:hidden; }
  #scene { position:fixed; inset:0; }
  .panel { position:fixed; background:rgba(16,22,36,.88); border:1px solid #23304a;
    border-radius:12px; backdrop-filter:blur(8px); }
  #hud { top:16px; left:16px; padding:14px 16px; max-width:300px; }
  #hud h1 { margin:0 0 2px; font-size:16px; letter-spacing:.3px; }
  #hud .sub { color:#7e8db0; font-size:11px; margin-bottom:10px; word-break:break-all; }
  #hud .grade { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
  #hud .badge { font-size:26px; font-weight:800; padding:2px 12px; border-radius:10px;
    background:linear-gradient(135deg,#1b2740,#0e1626); border:1px solid #2c3c5c; }
  .kpis { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
  .kpi { background:#0e1626; border:1px solid #1d2942; border-radius:8px; padding:6px 8px; }
  .kpi b { display:block; font-size:16px; }
  .kpi span { color:#7e8db0; font-size:10px; text-transform:uppercase; letter-spacing:.5px; }
  #legend { bottom:16px; left:16px; padding:12px 14px; font-size:12px; }
  #legend .row { display:flex; align-items:center; gap:8px; margin:4px 0; }
  #legend .dot { width:12px; height:12px; border-radius:3px; }
  #legend h3 { margin:0 0 8px; font-size:11px; color:#7e8db0; text-transform:uppercase; letter-spacing:1px; }
  #legend .sec { margin-top:10px; }
  #tip { position:fixed; pointer-events:none; padding:8px 10px; font-size:12px; display:none;
    background:rgba(8,12,22,.95); border:1px solid #2c3c5c; border-radius:8px; max-width:260px; z-index:10; }
  #tip b { color:#fff; }
  #ticker { bottom:16px; left:50%; transform:translateX(-50%); padding:8px 14px; font-size:12px;
    max-width:60vw; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  #ticker .w { margin-right:16px; }
  #ticker .w b { color:#fff; }
  #ctrls { top:16px; right:16px; padding:8px; display:flex; gap:6px; }
  #ctrls button { background:#0e1626; color:#cfe0ff; border:1px solid #2c3c5c; border-radius:8px;
    padding:7px 11px; font-size:12px; cursor:pointer; }
  #ctrls button:hover { background:#16233c; }
  #ctrls button.on { background:#1b3a5c; border-color:#3a6ea5; }
  #detail { top:70px; right:16px; width:280px; padding:14px 16px; display:none; }
  #detail h2 { margin:0 0 6px; font-size:14px; word-break:break-all; }
  #detail .meta { font-size:12px; color:#9fb0d4; line-height:1.7; }
  #detail .x { float:right; cursor:pointer; color:#7e8db0; }
  #detail .tag { display:inline-block; padding:1px 8px; border-radius:6px; font-size:11px; font-weight:700; }
  #minimap { position:fixed; right:16px; bottom:16px; width:188px; padding:8px 8px 6px; }
  #minimap .cap { font-size:10px; color:#7e8db0; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
  #minimap canvas { width:172px; height:172px; border-radius:6px; display:block; background:#0c1322; }
  .hl { color:#fff; }
</style>
</head>
<body>
<div id="scene"></div>
<div id="hud" class="panel">
  <h1>🏢 Apex Office Floor</h1>
  <div class="sub" id="proj"></div>
  <div class="grade"><div class="badge" id="grade">?</div>
    <div><div style="font-size:11px;color:#7e8db0">PROJECT HEALTH</div>
    <div id="score" style="font-weight:700"></div></div></div>
  <div class="kpis" id="kpis"></div>
</div>
<div id="ctrls" class="panel">
  <button id="btnOrbit">▶ Auto-orbit</button>
  <button id="btnRoads" class="on">Roads</button>
  <button id="btnReset">⤢ Reset</button>
</div>
<div id="detail" class="panel"><span class="x" id="detailX">✕</span>
  <h2 id="dName"></h2><div class="meta" id="dMeta"></div></div>
<div id="legend" class="panel">
  <h3>Desks = modules</h3>
  <div class="row"><span class="dot" style="background:#ff4d4d"></span>security finding</div>
  <div class="row"><span class="dot" style="background:#ff9636"></span>fragile hub</div>
  <div class="row"><span class="dot" style="background:#ffc23d"></span>untested</div>
  <div class="row"><span class="dot" style="background:#4d9bff"></span>dependency hub</div>
  <div class="row"><span class="dot" style="background:#36c98f"></span>healthy</div>
  <div class="sec"><h3>Workers = Apex agents</h3>
  <div class="row"><span class="dot" style="background:#ff4d4d;border-radius:50%"></span>Security Auditor</div>
  <div class="row"><span class="dot" style="background:#1fc8a9;border-radius:50%"></span>Test Engineer</div>
  <div class="row"><span class="dot" style="background:#4d9bff;border-radius:50%"></span>Architect</div>
  <div class="row"><span class="dot" style="background:#b07cff;border-radius:50%"></span>Doc Writer</div>
  <div class="row"><span class="dot" style="background:#ffd24d;border-radius:50%"></span>Refactorer</div>
  </div>
</div>
<div id="tip"></div>
<div id="ticker" class="panel"></div>
<div id="minimap" class="panel"><div class="cap">Floor plan · live</div><canvas id="mm" width="172" height="172"></canvas></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const DATA = /*__DATA__*/;
(function(){
  if (typeof THREE === "undefined") {
    document.getElementById("scene").innerHTML =
      "<div style='padding:40px;color:#ff8080'>Three.js failed to load (offline & uncached). Reconnect once to cache it.</div>";
    return;
  }
  let _s = 1337 >>> 0;
  function rnd(){ _s ^= _s<<13; _s^=_s>>>17; _s^=_s<<5; _s>>>=0; return _s/4294967296; }

  const HEALTH_COLOR = { security:0xff4d4d, fragile:0xff9636, untested:0xffc23d, hub:0x4d9bff, ok:0x36c98f };
  const HEALTH_CSS   = { security:"#ff4d4d", fragile:"#ff9636", untested:"#ffc23d", hub:"#4d9bff", ok:"#36c98f" };

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e17);
  scene.fog = new THREE.Fog(0x0a0e17, 90, 320);

  const camera = new THREE.PerspectiveCamera(55, innerWidth/innerHeight, 0.1, 2000);
  const renderer = new THREE.WebGLRenderer({ antialias:true });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  if (THREE.sRGBEncoding !== undefined) renderer.outputEncoding = THREE.sRGBEncoding;
  document.getElementById("scene").appendChild(renderer.domElement);

  // Soft, warm office lighting: a hemisphere fill + a key light that casts shadows.
  scene.add(new THREE.HemisphereLight(0xcfe0ff, 0x202838, 0.65));
  scene.add(new THREE.AmbientLight(0x9fb0d0, 0.28));
  const sun = new THREE.DirectionalLight(0xfff4e2, 0.7);
  sun.position.set(60, 120, 50); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  const sc0 = sun.shadow.camera;
  sc0.near = 10; sc0.far = 400; sc0.left = -160; sc0.right = 160; sc0.top = 160; sc0.bottom = -160;
  scene.add(sun);
  const rim = new THREE.DirectionalLight(0x4d7bff, 0.22); rim.position.set(-60,40,-50); scene.add(rim);

  const buildings = DATA.buildings;
  const N = buildings.length;
  const SP = 9, PAD = 11;

  // ---- group buildings into departments (top-level package) ----
  const deptOrder = [], deptMap = {};
  buildings.forEach((b,i)=>{ if(!(b.dept in deptMap)){ deptMap[b.dept]=[]; deptOrder.push(b.dept); } deptMap[b.dept].push(i); });

  // ---- shelf-pack department zones; place buildings inside ----
  const pos = new Array(N);
  const zones = [];
  const TARGET_ROW = Math.max(70, Math.sqrt(Math.max(1,N))*SP*2.6);
  let cx=0, cz=0, rowDepth=0, maxX=0;
  deptOrder.forEach(dept=>{
    const ids = deptMap[dept];
    const sc = Math.max(1, Math.ceil(Math.sqrt(ids.length)));
    const sr = Math.max(1, Math.ceil(ids.length/sc));
    const w = sc*SP, d = sr*SP;
    if(cx>0 && cx + w > TARGET_ROW){ cx=0; cz += rowDepth + PAD; rowDepth=0; }
    ids.forEach((bi,k)=>{
      pos[bi] = { x: cx + (k%sc)*SP + SP/2, z: cz + Math.floor(k/sc)*SP + SP/2 };
    });
    zones.push({ dept, x:cx, z:cz, w, d, count:ids.length });
    cx += w + PAD; rowDepth = Math.max(rowDepth, d); maxX = Math.max(maxX, cx);
  });
  const totalW = maxX, totalD = cz + rowDepth;
  const offX = -totalW/2, offZ = -totalD/2;
  pos.forEach(p=>{ p.x += offX; p.z += offZ; });
  zones.forEach(z=>{ z.cxn = z.x + z.w/2 + offX; z.czn = z.z + z.d/2 + offZ; });
  const WORLD = Math.max(totalW, totalD);

  // ---- office shell: textured carpet floor, walls with windows, ceiling lights ----
  const ROOMW = totalW + 28, ROOMD = totalD + 28, WALLH = 12;
  // Procedural carpet texture (subtle tiled noise) — no external assets.
  function carpetTexture(){
    const c = document.createElement("canvas"); c.width = c.height = 256; const x = c.getContext("2d");
    x.fillStyle = "#1b2740"; x.fillRect(0,0,256,256);
    for(let i=0;i<2600;i++){ const g = 22 + Math.floor(rnd()*26);
      x.fillStyle = "rgba("+(g)+","+(g+12)+","+(g+30)+",0.5)";
      x.fillRect(rnd()*256, rnd()*256, 2, 2); }
    x.strokeStyle = "rgba(40,56,90,0.5)"; x.lineWidth = 1;
    for(let i=0;i<=256;i+=32){ x.beginPath(); x.moveTo(i,0); x.lineTo(i,256); x.stroke();
      x.beginPath(); x.moveTo(0,i); x.lineTo(256,i); x.stroke(); }
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(Math.round(ROOMW/8), Math.round(ROOMD/8)); return t;
  }
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(ROOMW, ROOMD),
    new THREE.MeshLambertMaterial({ map: carpetTexture() }));
  floor.rotation.x = -Math.PI/2; floor.receiveShadow = true; scene.add(floor);

  // Walls with a row of windows (lighter panels) for a real office feel.
  const wallMat = new THREE.MeshLambertMaterial({ color:0x33456c, transparent:true, opacity:0.22, side:THREE.DoubleSide });
  const winMat  = new THREE.MeshBasicMaterial({ color:0x9fc4ff, transparent:true, opacity:0.16, side:THREE.DoubleSide });
  function wall(w,h,d,x,y,z,horiz){
    const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d), wallMat); m.position.set(x,y,z); scene.add(m);
    const len = horiz ? w : d; const n = Math.max(2, Math.round(len/12));
    for(let i=0;i<n;i++){ const f = (i+0.5)/n - 0.5;
      const win = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(6,len/n*0.7), h*0.5), winMat);
      if(horiz){ win.position.set(x + f*w, y+0.6, z + (d>0?0:0)); }
      else { win.position.set(x, y+0.6, z + f*d); win.rotation.y = Math.PI/2; }
      scene.add(win);
    }
  }
  wall(ROOMW, WALLH, 0.4, 0, WALLH/2, -ROOMD/2, true);
  wall(ROOMW, WALLH, 0.4, 0, WALLH/2,  ROOMD/2, true);
  wall(0.4, WALLH, ROOMD, -ROOMW/2, WALLH/2, 0, false);
  wall(0.4, WALLH, ROOMD,  ROOMW/2, WALLH/2, 0, false);

  // Recessed ceiling light panels.
  const stripMat = new THREE.MeshBasicMaterial({ color:0xdfe9ff });
  const strips = Math.max(2, Math.round(ROOMD/15));
  for(let s=0;s<strips;s++){ const z=-ROOMD/2 + (s+0.5)*(ROOMD/strips);
    const strip = new THREE.Mesh(new THREE.BoxGeometry(ROOMW*0.66, 0.22, 1.0), stripMat);
    strip.position.set(0, WALLH-0.4, z); scene.add(strip);
    const pl = new THREE.PointLight(0xeef4ff, 0.14, 110); pl.position.set(0, WALLH-1.2, z); scene.add(pl);
  }

  // ---- text-sprite labels (self-contained, canvas texture) ----
  function makeLabel(text, color, scale){
    const cv = document.createElement("canvas"); const ctx = cv.getContext("2d");
    const f = 48; ctx.font = "bold "+f+"px sans-serif";
    cv.width = Math.ceil(ctx.measureText(text).width)+24; cv.height = f+22;
    ctx.font = "bold "+f+"px sans-serif"; ctx.fillStyle = "rgba(8,12,22,.72)";
    ctx.fillRect(0,0,cv.width,cv.height);
    ctx.fillStyle = color; ctx.textBaseline = "middle"; ctx.fillText(text, 12, cv.height/2);
    const tex = new THREE.CanvasTexture(cv); tex.minFilter = THREE.LinearFilter;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map:tex, transparent:true, depthTest:false }));
    const s = (scale||1); sp.scale.set(cv.width/cv.height*s, s, 1);
    return sp;
  }

  // ---- department sections: a carpet rug + a glass-partition outline + label ----
  zones.forEach(z=>{
    const rug = new THREE.Mesh(new THREE.BoxGeometry(z.w-1.0, 0.08, z.d-1.0),
      new THREE.MeshLambertMaterial({ color:0x1d2c4a }));
    rug.position.set(z.cxn, 0.06, z.czn); scene.add(rug);
    const part = new THREE.Mesh(new THREE.BoxGeometry(z.w-1.0, 1.4, z.d-1.0),
      new THREE.MeshBasicMaterial({ color:0x3a5fa0, transparent:true, opacity:0.05 }));
    part.position.set(z.cxn, 0.7, z.czn); scene.add(part);
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(part.geometry),
      new THREE.LineBasicMaterial({ color:0x33507e, transparent:true, opacity:0.5 }));
    outline.position.copy(part.position); scene.add(outline);
    const lbl = makeLabel("🏢 "+z.dept, "#bcd2ff", 2.8);
    lbl.position.set(z.cxn, 4.2, z.czn - z.d/2 - 0.5); scene.add(lbl);
  });

  // ---- reception desk + big health-grade sign at the front of the floor ----
  (function reception(){
    const fz = -ROOMD/2 + 5;   // near the front wall
    const counter = new THREE.Mesh(new THREE.BoxGeometry(9, 1.1, 1.6),
      new THREE.MeshLambertMaterial({ color:0x2b3650 }));
    counter.position.set(0, 0.55, fz); counter.castShadow = true; counter.receiveShadow = true; scene.add(counter);
    const top = new THREE.Mesh(new THREE.BoxGeometry(9.4, 0.12, 2.0),
      new THREE.MeshLambertMaterial({ color:0x6b5640 })); top.position.set(0, 1.16, fz); scene.add(top);
    const sign = makeLabel("APEX  ·  "+DATA.grade.letter+"  "+DATA.grade.score+"/100", "#bcd2ff", 4.4);
    sign.position.set(0, 6.4, -ROOMD/2 + 0.6); scene.add(sign);
    const logo = makeLabel("🏢  THE OFFICE", "#7e8db0", 2.0);
    logo.position.set(0, 4.2, -ROOMD/2 + 0.6); scene.add(logo);
  })();

  // ---- glass meeting room in the back-right corner ----
  (function meetingRoom(){
    const rw = 11, rd = 8, rh = 3.4;
    const rx = ROOMW/2 - rw/2 - 2, rz = ROOMD/2 - rd/2 - 2;
    const glass = new THREE.MeshBasicMaterial({ color:0x6fa8d8, transparent:true, opacity:0.10, side:THREE.DoubleSide });
    const pane=(w,h,d,x,y,z)=>{ const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d), glass); m.position.set(x,y,z); scene.add(m);
      const e=new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({color:0x4f7bb0,transparent:true,opacity:0.55})); e.position.copy(m.position); scene.add(e); };
    pane(rw,rh,0.12, rx, rh/2, rz-rd/2);
    pane(0.12,rh,rd, rx-rw/2, rh/2, rz);
    pane(0.12,rh,rd, rx+rw/2, rh/2, rz);            // open side faces the floor (entrance)
    // conference table + chairs
    const table = new THREE.Mesh(new THREE.BoxGeometry(5.2,0.16,2.4), new THREE.MeshLambertMaterial({ color:0x5a4636 }));
    table.position.set(rx, 1.05, rz); table.castShadow = true; table.receiveShadow = true; scene.add(table);
    const tleg=(dx,dz)=>{ const l=new THREE.Mesh(new THREE.BoxGeometry(0.18,1.0,0.18), new THREE.MeshLambertMaterial({color:0x20283a}));
      l.position.set(rx+dx,0.5,rz+dz); scene.add(l); };
    tleg(-2.2,-0.9); tleg(2.2,-0.9); tleg(-2.2,0.9); tleg(2.2,0.9);
    const chairMatM = new THREE.MeshLambertMaterial({ color:0x2b3650 });
    for(let s=-1;s<=1;s++){ [-1,1].forEach(side=>{
      const seat=new THREE.Mesh(new THREE.BoxGeometry(0.7,0.12,0.7), chairMatM);
      seat.position.set(rx + s*1.7, 0.66, rz + side*1.7); seat.castShadow=true; scene.add(seat);
      const back=new THREE.Mesh(new THREE.BoxGeometry(0.7,0.7,0.12), chairMatM);
      back.position.set(rx + s*1.7, 1.0, rz + side*1.95*0.62*1.0 + side*0.0); back.position.z = rz + side*2.0; scene.add(back);
    }); }
    const lbl = makeLabel("📊 Meeting Room", "#bcd2ff", 2.2); lbl.position.set(rx, rh+1.0, rz-rd/2); scene.add(lbl);
  })();

  // ---- monitor screen content: a faux code/terminal UI tinted by health ----
  function screenTexture(b, hexcss){
    const c = document.createElement("canvas"); c.width = 256; c.height = 160; const x = c.getContext("2d");
    x.fillStyle = "#0c1322"; x.fillRect(0,0,256,160);
    x.fillStyle = hexcss; x.globalAlpha = 0.14; x.fillRect(0,0,256,160); x.globalAlpha = 1;
    x.fillStyle = "#16213a"; x.fillRect(0,0,256,18);            // title bar
    x.fillStyle = hexcss; x.beginPath(); x.arc(10,9,4,0,7); x.fill();
    x.fillStyle = "#7e8db0"; x.font = "10px monospace";
    x.fillText((b.name.split("/").pop()||"").slice(0,30), 22, 12);
    // faux code lines, length varied; a couple highlighted in the health colour
    for(let r=0;r<11;r++){ const y = 30 + r*11; const w = 30 + rnd()*180;
      x.fillStyle = (b.findings>0 && r%4===1) ? hexcss : "#33507e";
      x.globalAlpha = (b.findings>0 && r%4===1) ? 0.9 : 0.55;
      x.fillRect(12 + (rnd()*16|0), y, w, 4); }
    x.globalAlpha = 1;
    const t = new THREE.CanvasTexture(c); t.minFilter = THREE.LinearFilter; return t;
  }

  // ---- desks: one workstation per module ----
  const meshes = [];
  const maxLoc = Math.max(1, ...buildings.map(b=>b.loc));
  const deskMat  = new THREE.MeshLambertMaterial({ color:0x6b5640 });   // wood-toned desktop
  const frameMat = new THREE.MeshLambertMaterial({ color:0x2b3650 });
  const legMat   = new THREE.MeshLambertMaterial({ color:0x20283a });
  const chairMat = new THREE.MeshLambertMaterial({ color:0x1f2940 });
  const keyMat   = new THREE.MeshLambertMaterial({ color:0x12171f });
  const stackMat = new THREE.MeshLambertMaterial({ color:0xe8edf6 });
  buildings.forEach((b, i) => {
    const p = pos[i];
    const col = HEALTH_COLOR[b.health] ?? 0x36c98f;
    const cssCol = HEALTH_CSS[b.health] || "#36c98f";
    // desk surface on four legs (casts/receives shadow)
    const desk = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.16, 1.7), deskMat);
    desk.position.set(p.x, 1.05, p.z); desk.castShadow = true; desk.receiveShadow = true; scene.add(desk);
    const leg=(dx,dz)=>{ const l=new THREE.Mesh(new THREE.BoxGeometry(0.16,1.05,0.16), legMat);
      l.position.set(p.x+dx,0.52,p.z+dz); l.castShadow = true; scene.add(l); };
    leg(-1.3,-0.7); leg(1.3,-0.7); leg(-1.3,0.7); leg(1.3,0.7);
    // monitor: dark bezel + a lit screen showing a faux UI (the clickable proxy)
    const bezel = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.95, 0.08), frameMat);
    bezel.position.set(p.x, 1.78, p.z-0.5); bezel.castShadow = true; scene.add(bezel);
    const screen = new THREE.Mesh(new THREE.BoxGeometry(1.34, 0.8, 0.04),
      new THREE.MeshBasicMaterial({ map: screenTexture(b, cssCol) }));
    screen.position.set(p.x, 1.78, p.z-0.45);
    screen.userData = { b, i, x:p.x, z:p.z, h:3, baseColor: col };
    scene.add(screen); meshes.push(screen);
    // the screen casts a soft coloured glow onto the desk
    const glow = new THREE.PointLight(col, 0.5, 6); glow.position.set(p.x, 1.7, p.z-0.1); scene.add(glow);
    const stand = new THREE.Mesh(new THREE.BoxGeometry(0.12,0.42,0.12), frameMat);
    stand.position.set(p.x, 1.36, p.z-0.5); scene.add(stand);
    // keyboard + mouse
    const kb = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.06, 0.4), keyMat);
    kb.position.set(p.x, 1.16, p.z+0.15); kb.castShadow = true; scene.add(kb);
    const mouse = new THREE.Mesh(new THREE.BoxGeometry(0.18,0.06,0.28), keyMat);
    mouse.position.set(p.x+0.75, 1.16, p.z+0.15); scene.add(mouse);
    // coffee mug
    const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.13,0.13,0.26,10),
      new THREE.MeshLambertMaterial({ color:0xcf6a4a })); mug.position.set(p.x-0.95, 1.26, p.z+0.2); mug.castShadow=true; scene.add(mug);
    // a stack of files whose height ∝ LOC keeps the size signal at desk scale
    const sh = 0.12 + 1.2*Math.sqrt(b.loc/maxLoc);
    const stack = new THREE.Mesh(new THREE.BoxGeometry(0.5, sh, 0.7), stackMat);
    stack.position.set(p.x+1.05, 1.13+sh/2, p.z+0.25); stack.castShadow = true; scene.add(stack);
    // office chair behind the desk (swivel base + seat + back)
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.82,0.14,0.82), chairMat); seat.position.set(p.x,0.7,p.z+1.05); seat.castShadow=true; scene.add(seat);
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.82,0.9,0.14), chairMat); back.position.set(p.x,1.16,p.z+1.45); back.castShadow=true; scene.add(back);
    const cbase = new THREE.Mesh(new THREE.CylinderGeometry(0.06,0.06,0.55,8), legMat); cbase.position.set(p.x,0.42,p.z+1.05); scene.add(cbase);
    // a pulsing alert lamp above the monitor for modules with findings
    if (b.findings > 0) {
      const cap = new THREE.Mesh(new THREE.SphereGeometry(0.2,12,12),
        new THREE.MeshBasicMaterial({ color:0xff5a5a }));
      cap.position.set(p.x, 2.6, p.z-0.5); cap.userData.pulse = true; scene.add(cap);
    }
  });
  function plotOf(i){ const m = meshes[i]; return m ? {x:m.userData.x, z:m.userData.z, h:m.userData.h} : {x:0,z:0,h:4}; }

  // ---- dependency "roads" (real import edges) ----
  let roads = null;
  if (DATA.edges && DATA.edges.length){
    const verts = [];
    DATA.edges.forEach(([a,bi])=>{
      const pa = pos[a], pb = pos[bi]; if(!pa||!pb) return;
      verts.push(pa.x, 0.5, pa.z, pb.x, 0.5, pb.z);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    roads = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color:0x3a5fa0, transparent:true, opacity:0.28 }));
    scene.add(roads);
  }

  // ---- potted plants for ambiance (department corners) ----
  const potMat = new THREE.MeshLambertMaterial({ color:0x4a3528 });
  const leafMat = new THREE.MeshLambertMaterial({ color:0x2f7d4f });
  function makePlant(x, z){
    const grp = new THREE.Group();
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.32,0.24,0.5,10), potMat);
    pot.position.y = 0.25; pot.castShadow = true; grp.add(pot);
    for(let i=0;i<5;i++){ const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.18,0.9,7), leafMat);
      leaf.position.set((rnd()-0.5)*0.3, 0.85 + rnd()*0.3, (rnd()-0.5)*0.3);
      leaf.rotation.set((rnd()-0.5)*0.6, rnd()*6.28, (rnd()-0.5)*0.6); leaf.castShadow = true; grp.add(leaf); }
    grp.position.set(x, 0, z); scene.add(grp);
  }
  zones.forEach(z=>{ makePlant(z.cxn - z.w/2 + 1.2, z.czn - z.d/2 + 1.2);
                     makePlant(z.cxn + z.w/2 - 1.2, z.czn + z.d/2 - 1.2); });

  // ---- workers: jointed humanoids that walk, then sit & type at a desk ----
  const HIP = 1.05, SEG = 0.52;
  function limb(len, w, mat){               // a pivot group with a box hanging down
    const grp = new THREE.Group();
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, len, w), mat);
    m.position.y = -len/2; m.castShadow = true; grp.add(m);
    return grp;
  }
  function makePerson(hex){
    const g = new THREE.Group();
    const skin = new THREE.MeshLambertMaterial({ color:0xf2d9c0 });
    const shirt = new THREE.MeshLambertMaterial({ color:new THREE.Color(hex) });
    const pants = new THREE.MeshLambertMaterial({ color:0x2a3142 });
    const torso = new THREE.Mesh(new THREE.BoxGeometry(0.62,0.7,0.34), shirt);
    torso.position.y = HIP + 0.35; torso.castShadow = true; g.add(torso);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.27,14,14), skin);
    head.position.y = HIP + 0.95; head.castShadow = true; g.add(head);
    const thighL = limb(SEG,0.2,pants), thighR = limb(SEG,0.2,pants);
    thighL.position.set(-0.16,HIP,0); thighR.position.set(0.16,HIP,0); g.add(thighL,thighR);
    const shinL = limb(SEG,0.18,pants), shinR = limb(SEG,0.18,pants);
    shinL.position.y = -SEG; thighL.add(shinL); shinR.position.y = -SEG; thighR.add(shinR);
    const armL = limb(0.62,0.16,shirt), armR = limb(0.62,0.16,shirt);
    armL.position.set(-0.4,HIP+0.66,0); armR.position.set(0.4,HIP+0.66,0); g.add(armL,armR);
    const foreL = limb(0.5,0.15,skin), foreR = limb(0.5,0.15,skin);
    foreL.position.y = -0.62; armL.add(foreL); foreR.position.y = -0.62; armR.add(foreR);
    g.userData = { thighL,thighR,shinL,shinR,armL,armR,foreL,foreR };
    return g;
  }
  function setPose(g, sit){
    const u = g.userData;
    if(sit){
      u.thighL.rotation.x = -1.55; u.thighR.rotation.x = -1.55;   // thighs forward
      u.shinL.rotation.x = 1.55;  u.shinR.rotation.x = 1.55;      // shins down
      u.armL.rotation.x = -1.2;   u.armR.rotation.x = -1.2;       // arms to keyboard
      u.foreL.rotation.x = -0.5;  u.foreR.rotation.x = -0.5;
      g.position.y = 0.62;
    } else {
      u.shinL.rotation.x = u.shinR.rotation.x = 0;
      u.armL.rotation.z = 0; u.armR.rotation.z = 0;
      g.position.y = 0;
    }
  }
  const workers = DATA.workers.map((w, k) => {
    const g = makePerson(w.color);
    const p0 = plotOf(w.route[k % w.route.length]);
    g.position.set(p0.x + (rnd()*4-2), 0, p0.z + 3 + rnd()*2); scene.add(g);
    return { g, route:w.route, role:w.role, ri:k % w.route.length,
      target:new THREE.Vector3(g.position.x,0,g.position.z), face:0,
      wait:rnd()*2, phase:rnd()*6.28, curName:"", sitting:false };
  });
  workers.forEach(w=>{ w.g.userData.wk = w; });
  const workerGroups = workers.map(w=>w.g);
  let follow = null;   // a worker the camera is currently tracking
  function newTarget(wk){
    wk.ri = (wk.ri + 1) % wk.route.length;
    const bi = wk.route[wk.ri]; const p = plotOf(bi);
    // walk to the chair (behind the desk), then sit facing the monitor (−z)
    wk.target.set(p.x + (rnd()*0.5-0.25), 0, p.z + 1.05);
    wk.face = Math.PI;                 // face toward −z (the screen)
    wk.curName = buildings[bi] ? buildings[bi].name.split("/").pop() : "";
    renderTicker();
  }

  // ---- HUD + ticker ----
  document.getElementById("proj").textContent = DATA.project;
  document.getElementById("grade").textContent = DATA.grade.letter;
  document.getElementById("score").textContent = DATA.grade.score + " / 100 · " + DATA.generated;
  const t = DATA.totals;
  document.getElementById("kpis").innerHTML =
    kpi(t.buildings,"modules")+kpi(t.findings,"findings")+kpi(t.untested,"untested")+kpi(t.workers,"workers");
  function kpi(v,l){ return "<div class='kpi'><b>"+v+"</b><span>"+l+"</span></div>"; }
  const tickerEl = document.getElementById("ticker");
  function renderTicker(){
    tickerEl.innerHTML = workers.map(w=>"<span class='w' style='color:"+colorOf(w.role)+"'>●</span>"+
      "<span class='w'><b>"+w.role+"</b> → "+(w.curName||"…")+"</span>").join("");
  }
  function colorOf(role){ const m = DATA.workers.find(w=>w.role===role); return m?m.color:"#fff"; }
  workers.forEach(newTarget);

  // ---- live minimap (top-down floor plan with moving worker dots) ----
  const mm = document.getElementById("mm"), mx = mm.getContext("2d");
  const mmHalfW = ROOMW/2, mmHalfD = ROOMD/2;
  function mmX(x){ return (x + mmHalfW)/(2*mmHalfW) * mm.width; }
  function mmY(z){ return (z + mmHalfD)/(2*mmHalfD) * mm.height; }
  function drawMinimap(){
    mx.clearRect(0,0,mm.width,mm.height);
    mx.fillStyle = "#0c1322"; mx.fillRect(0,0,mm.width,mm.height);
    // desks
    for(let i=0;i<buildings.length;i++){ const p = pos[i]; if(!p) continue;
      mx.fillStyle = HEALTH_CSS[buildings[i].health] || "#36c98f";
      mx.fillRect(mmX(p.x)-1.5, mmY(p.z)-1.5, 3, 3); }
    // workers (live)
    workers.forEach(wk=>{ mx.beginPath(); mx.fillStyle = colorOf(wk.role);
      mx.arc(mmX(wk.g.position.x), mmY(wk.g.position.z), 2.4, 0, 7); mx.fill(); });
    // camera footprint
    mx.strokeStyle = "rgba(220,230,255,.5)"; mx.lineWidth = 1;
    mx.strokeRect(mmX(target.x)-3, mmY(target.z)-3, 6, 6);
  }

  // ---- camera (custom orbit) ----
  let theta = 0.7, phi = 0.82, rad = Math.max(55, WORLD*0.92), autoOrbit=false;
  let drag=false, moved=false, px=0, py=0;
  const target = new THREE.Vector3(0, 4, 0);
  const homeTarget = new THREE.Vector3(0,4,0), homeRad = rad;
  function applyCam(){
    camera.position.set(
      target.x + rad*Math.sin(phi)*Math.cos(theta),
      target.y + rad*Math.cos(phi),
      target.z + rad*Math.sin(phi)*Math.sin(theta));
    camera.lookAt(target);
  }
  const dom = renderer.domElement;
  dom.addEventListener("mousedown", e=>{ drag=true; moved=false; px=e.clientX; py=e.clientY; });
  addEventListener("mouseup", ()=> drag=false);
  addEventListener("mousemove", e=>{
    if(drag){ moved=true; theta -= (e.clientX-px)*0.005; phi = Math.max(0.18, Math.min(1.45, phi - (e.clientY-py)*0.005));
      px=e.clientX; py=e.clientY; }
    moveTip(e);
  });
  dom.addEventListener("wheel", e=>{ rad = Math.max(25, Math.min(420, rad + e.deltaY*0.09)); e.preventDefault(); }, {passive:false});

  // ---- hover tooltip + click-to-focus ----
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  const tip = document.getElementById("tip");
  function pick(e){ mouse.x=(e.clientX/innerWidth)*2-1; mouse.y=-(e.clientY/innerHeight)*2+1;
    ray.setFromCamera(mouse, camera); return ray.intersectObjects(meshes)[0]; }
  function moveTip(e){
    const hit = pick(e);
    if(hit){ const b = hit.object.userData.b;
      tip.style.display="block"; tip.style.left=(e.clientX+14)+"px"; tip.style.top=(e.clientY+14)+"px";
      tip.innerHTML = "<b>"+b.name+"</b><br>"+b.loc+" LOC · cx "+b.complexity+" · fan-in "+b.fan_in+
        (b.findings?("<br><span style='color:#ff7a7a'>"+b.findings+" security finding(s)</span>"):"")+
        "<br>tests: "+b.tests+" · <span class='hl'>"+b.health+"</span>";
    } else tip.style.display="none";
  }
  dom.addEventListener("click", e=>{
    if(moved) return;            // a drag, not a click
    const hit = pick(e);
    if(!hit){
      // maybe a worker was clicked -> follow them; empty space -> release follow
      mouse.x=(e.clientX/innerWidth)*2-1; mouse.y=-(e.clientY/innerHeight)*2+1; ray.setFromCamera(mouse, camera);
      const wh = ray.intersectObjects(workerGroups, true)[0];
      if(wh){ let o = wh.object; while(o && !(o.userData && o.userData.wk)) o = o.parent;
        if(o){ follow = o.userData.wk; rad = 22;
          document.getElementById("detail").style.display="block";
          document.getElementById("dName").textContent = "👤 "+follow.role;
          document.getElementById("dMeta").innerHTML =
            "<span class='tag' style='background:"+follow.g.children[0].material.color.getStyle()+";color:#0a0e17'>following</span><br><br>"+
            "Now servicing: <span class='hl'>"+(follow.curName||"…")+"</span><br>"+
            "Route length: <span class='hl'>"+follow.route.length+"</span> desk(s)<br><br>"+
            "<span style='color:#7e8db0'>Click empty floor or Reset to release.</span>";
          return; } }
      follow = null; return;
    }
    follow = null;
    const u = hit.object.userData, b = u.b;
    target.set(u.x, u.h/2, u.z); rad = Math.max(24, u.h*1.6 + 22);
    const visitors = DATA.workers.filter(w=> w.route.includes(u.i)).map(w=>w.role);
    document.getElementById("detail").style.display="block";
    document.getElementById("dName").textContent = b.name;
    document.getElementById("dMeta").innerHTML =
      "<span class='tag' style='background:"+HEALTH_CSS[b.health]+";color:#0a0e17'>"+b.health+"</span><br><br>"+
      "Lines of code: <span class='hl'>"+b.loc+"</span><br>"+
      "Complexity: <span class='hl'>"+b.complexity+"</span><br>"+
      "Fan-in (importers): <span class='hl'>"+b.fan_in+"</span><br>"+
      "Linked tests: <span class='hl'>"+b.tests+"</span><br>"+
      "Security findings: <span class='hl' style='color:"+(b.findings?'#ff7a7a':'#36c98f')+"'>"+b.findings+"</span><br><br>"+
      "Visiting agents: <span class='hl'>"+(visitors.length?[...new Set(visitors)].join(", "):"none")+"</span>";
  });
  document.getElementById("detailX").onclick = ()=> document.getElementById("detail").style.display="none";

  // ---- controls ----
  const bOrbit=document.getElementById("btnOrbit"), bRoads=document.getElementById("btnRoads"), bReset=document.getElementById("btnReset");
  bOrbit.onclick = ()=>{ autoOrbit=!autoOrbit; bOrbit.classList.toggle("on",autoOrbit); bOrbit.textContent=(autoOrbit?"⏸":"▶")+" Auto-orbit"; };
  bRoads.onclick = ()=>{ if(roads){ roads.visible=!roads.visible; bRoads.classList.toggle("on",roads.visible); } };
  bReset.onclick = ()=>{ follow=null; target.copy(homeTarget); rad=homeRad; theta=0.7; phi=0.82;
    document.getElementById("detail").style.display="none"; };

  // ---- loop ----
  const clock = new THREE.Clock();
  function tick(){
    const dt = Math.min(0.05, clock.getDelta()), tt = clock.elapsedTime;
    if(autoOrbit && !follow) theta += dt*0.12;
    if(follow){ target.lerp(new THREE.Vector3(follow.g.position.x, 1.4, follow.g.position.z), 0.12); }
    workers.forEach(wk=>{
      const pp = wk.g.position, tg = wk.target, u = wk.g.userData;
      const dx = tg.x-pp.x, dz = tg.z-pp.z, d = Math.hypot(dx,dz);
      if(d < 0.5){
        // arrived: sit and type while the work "happens"
        if(!wk.sitting){ wk.sitting = true; setPose(wk.g, true); wk.g.rotation.y = wk.face; }
        const ty = Math.sin(tt*11 + wk.phase)*0.18;           // typing forearm bob
        u.foreL.rotation.x = -0.5 + ty; u.foreR.rotation.x = -0.5 - ty;
        wk.wait -= dt;
        if(wk.wait<=0){ wk.sitting = false; setPose(wk.g, false); newTarget(wk); wk.wait = 2.2 + rnd()*3.0; }
      } else {
        if(wk.sitting){ wk.sitting = false; setPose(wk.g, false); }
        const v = 4.6*dt/d; pp.x += dx*v; pp.z += dz*v; wk.g.rotation.y = Math.atan2(dx, dz);
        const sw = Math.sin(tt*8 + wk.phase)*0.6;             // walk cycle
        u.thighL.rotation.x = sw; u.thighR.rotation.x = -sw;
        u.armL.rotation.x = -sw; u.armR.rotation.x = sw;
        u.foreL.rotation.x = u.foreR.rotation.x = -0.1;
        pp.y = Math.abs(Math.sin(tt*8 + wk.phase))*0.06;
      }
    });
    scene.children.forEach(o=>{ if(o.userData && o.userData.pulse){ o.scale.y = 1 + Math.sin(tt*4)*0.4; } });
    if((tt*60|0) % 3 === 0) drawMinimap();   // ~20fps minimap, cheap
    applyCam(); renderer.render(scene, camera); requestAnimationFrame(tick);
  }
  applyCam(); tick();
  addEventListener("resize", ()=>{ camera.aspect=innerWidth/innerHeight; camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight); });
})();
</script>
</body>
</html>
"""
