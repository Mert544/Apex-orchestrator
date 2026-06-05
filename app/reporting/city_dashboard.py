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


def build_city_model(project_root: str, objective: str | None = None, max_buildings: int = 60) -> dict[str, Any]:
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


def build_city(project_root: str, objective: str | None = None) -> str:
    """Build the self-contained 3D city dashboard HTML."""
    model = build_city_model(project_root, objective)
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
  document.getElementById("scene").appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0x8fa6d6, 0.55));
  const sun = new THREE.DirectionalLight(0xffffff, 0.85); sun.position.set(60,110,40); scene.add(sun);
  const rim = new THREE.DirectionalLight(0x4d7bff, 0.3); rim.position.set(-60,40,-50); scene.add(rim);

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

  // ---- office shell: carpet floor, perimeter walls, ceiling light strips ----
  const ROOMW = totalW + 26, ROOMD = totalD + 26, WALLH = 11;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(ROOMW, ROOMD),
    new THREE.MeshLambertMaterial({ color:0x18223a }));
  floor.rotation.x = -Math.PI/2; scene.add(floor);
  const carpet = new THREE.GridHelper(Math.max(ROOMW,ROOMD),
    Math.max(8, Math.round(Math.max(ROOMW,ROOMD)/6)), 0x243355, 0x1b2740);
  carpet.position.y = 0.02; scene.add(carpet);
  const wallMat = new THREE.MeshLambertMaterial({ color:0x2a3a5e, transparent:true, opacity:0.16, side:THREE.DoubleSide });
  function wall(w,h,d,x,y,z){ const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d), wallMat); m.position.set(x,y,z); scene.add(m); }
  wall(ROOMW, WALLH, 0.4, 0, WALLH/2, -ROOMD/2);
  wall(ROOMW, WALLH, 0.4, 0, WALLH/2,  ROOMD/2);
  wall(0.4, WALLH, ROOMD, -ROOMW/2, WALLH/2, 0);
  wall(0.4, WALLH, ROOMD,  ROOMW/2, WALLH/2, 0);
  const stripMat = new THREE.MeshBasicMaterial({ color:0xbcd2ff });
  const strips = Math.max(2, Math.round(ROOMD/15));
  for(let s=0;s<strips;s++){ const z=-ROOMD/2 + (s+0.5)*(ROOMD/strips);
    const strip = new THREE.Mesh(new THREE.BoxGeometry(ROOMW*0.66, 0.22, 1.0), stripMat);
    strip.position.set(0, WALLH-0.4, z); scene.add(strip);
    const pl = new THREE.PointLight(0xbcd2ff, 0.16, 90); pl.position.set(0, WALLH-1.2, z); scene.add(pl);
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

  // ---- desks: one workstation per module (monitor screen = health colour) ----
  const meshes = [];
  const maxLoc = Math.max(1, ...buildings.map(b=>b.loc));
  const deskMat  = new THREE.MeshLambertMaterial({ color:0x3b4a63 });
  const legMat   = new THREE.MeshLambertMaterial({ color:0x222b3d });
  const chairMat = new THREE.MeshLambertMaterial({ color:0x2b3650 });
  const stackMat = new THREE.MeshLambertMaterial({ color:0xccd5ea });
  buildings.forEach((b, i) => {
    const p = pos[i];
    const col = HEALTH_COLOR[b.health] ?? 0x36c98f;
    // desk surface on four legs
    const desk = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.16, 1.7), deskMat);
    desk.position.set(p.x, 1.05, p.z); scene.add(desk);
    const leg=(dx,dz)=>{ const l=new THREE.Mesh(new THREE.BoxGeometry(0.16,1.05,0.16), legMat);
      l.position.set(p.x+dx,0.52,p.z+dz); scene.add(l); };
    leg(-1.3,-0.7); leg(1.3,-0.7); leg(-1.3,0.7); leg(1.3,0.7);
    // monitor — the screen is the clickable proxy, lit in the module's health colour
    const screen = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.8, 0.08),
      new THREE.MeshBasicMaterial({ color: col }));
    screen.position.set(p.x, 1.72, p.z-0.45);
    screen.userData = { b, i, x:p.x, z:p.z, h:3, baseColor: col };
    scene.add(screen); meshes.push(screen);
    const stand = new THREE.Mesh(new THREE.BoxGeometry(0.12,0.35,0.12), legMat);
    stand.position.set(p.x, 1.33, p.z-0.45); scene.add(stand);
    // a stack of files whose height ∝ LOC keeps the size signal at desk scale
    const sh = 0.12 + 1.2*Math.sqrt(b.loc/maxLoc);
    const stack = new THREE.Mesh(new THREE.BoxGeometry(0.5, sh, 0.7), stackMat);
    stack.position.set(p.x+1.05, 1.13+sh/2, p.z+0.25); scene.add(stack);
    // office chair behind the desk
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.8,0.12,0.8), chairMat); seat.position.set(p.x,0.66,p.z+1.05); scene.add(seat);
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.8,0.85,0.12), chairMat); back.position.set(p.x,1.08,p.z+1.45); scene.add(back);
    // a pulsing alert lamp above the monitor for modules with findings
    if (b.findings > 0) {
      const cap = new THREE.Mesh(new THREE.SphereGeometry(0.22,10,10),
        new THREE.MeshBasicMaterial({ color:0xff5a5a }));
      cap.position.set(p.x, 2.55, p.z-0.45); cap.userData.pulse = true; scene.add(cap);
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

  // ---- workers ----
  function makePerson(hex){
    const g = new THREE.Group();
    const cm = new THREE.MeshLambertMaterial({ color:new THREE.Color(hex) });
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.45,0.6,1.6,10), cm); body.position.y=1.0; g.add(body);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.42,12,12),
      new THREE.MeshLambertMaterial({ color:0xf2d9c0 })); head.position.y=2.1; g.add(head);
    const legM = new THREE.MeshLambertMaterial({ color:0x223 });
    const l1 = new THREE.Mesh(new THREE.BoxGeometry(0.28,0.9,0.28), legM); l1.position.set(-0.22,0.45,0); g.add(l1);
    const l2 = new THREE.Mesh(new THREE.BoxGeometry(0.28,0.9,0.28), legM); l2.position.set( 0.22,0.45,0); g.add(l2);
    g.userData.legs = [l1,l2];
    return g;
  }
  const workers = DATA.workers.map((w, k) => {
    const g = makePerson(w.color);
    const p0 = plotOf(w.route[k % w.route.length]);
    const ang = rnd()*6.28, r = 1.7 + rnd()*0.9;
    g.position.set(p0.x + Math.cos(ang)*r, 0, p0.z + Math.sin(ang)*r); scene.add(g);
    return { g, route:w.route, role:w.role, ri:k % w.route.length,
      target:new THREE.Vector3(g.position.x,0,g.position.z), wait:rnd()*2, phase:rnd()*6.28, curName:"" };
  });
  function newTarget(wk){
    wk.ri = (wk.ri + 1) % wk.route.length;
    const bi = wk.route[wk.ri]; const p = plotOf(bi);
    const ang = rnd()*6.28, r = 1.7 + rnd()*0.9;
    wk.target.set(p.x + Math.cos(ang)*r, 0, p.z + Math.sin(ang)*r);
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
    const hit = pick(e); if(!hit) return;
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
  bReset.onclick = ()=>{ target.copy(homeTarget); rad=homeRad; theta=0.7; phi=0.82;
    document.getElementById("detail").style.display="none"; };

  // ---- loop ----
  const clock = new THREE.Clock();
  function tick(){
    const dt = Math.min(0.05, clock.getDelta()), tt = clock.elapsedTime;
    if(autoOrbit) theta += dt*0.12;
    workers.forEach(wk=>{
      const pp = wk.g.position, tg = wk.target;
      const dx = tg.x-pp.x, dz = tg.z-pp.z, d = Math.hypot(dx,dz);
      if(d < 0.6){ wk.wait -= dt; if(wk.wait<=0){ newTarget(wk); wk.wait = 1.2 + rnd()*2.5; } }
      else { const v = 5.5*dt/d; pp.x += dx*v; pp.z += dz*v; wk.g.rotation.y = Math.atan2(dx, dz);
        const sw = Math.sin(tt*9 + wk.phase)*0.5; wk.g.userData.legs[0].rotation.x=sw; wk.g.userData.legs[1].rotation.x=-sw;
        wk.g.position.y = Math.abs(Math.sin(tt*9 + wk.phase))*0.12; }
    });
    scene.children.forEach(o=>{ if(o.userData && o.userData.pulse){ o.scale.y = 1 + Math.sin(tt*4)*0.4; } });
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
