"""3D "company city" dashboard — the codebase rendered as a living office.

Every named module becomes a building (height ∝ lines of code, colour ∝ health),
laid out in departments by top-level package. Apex's own agents become 3D
workers who walk to the buildings they care about: the security auditor heads
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
<title>Apex — Company City</title>
<style>
  :root { --bg:#0a0e17; --panel:rgba(16,22,36,.86); --line:#23304a; --txt:#dce6ff; }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:#0a0e17; color:#dce6ff;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; overflow:hidden; }
  #scene { position:fixed; inset:0; }
  .panel { position:fixed; background:rgba(16,22,36,.86); border:1px solid #23304a;
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
  #help { bottom:16px; right:16px; padding:8px 12px; font-size:11px; color:#7e8db0; }
  .hl { color:#fff; }
</style>
</head>
<body>
<div id="scene"></div>
<div id="hud" class="panel">
  <h1>🏙️ Apex Company City</h1>
  <div class="sub" id="proj"></div>
  <div class="grade"><div class="badge" id="grade">?</div>
    <div><div style="font-size:11px;color:#7e8db0">PROJECT HEALTH</div>
    <div id="score" style="font-weight:700"></div></div></div>
  <div class="kpis" id="kpis"></div>
</div>
<div id="legend" class="panel">
  <h3>Buildings = modules</h3>
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
<div id="help" class="panel">drag to orbit · scroll to zoom · hover a building</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const DATA = /*__DATA__*/;
(function(){
  if (typeof THREE === "undefined") {
    document.getElementById("scene").innerHTML =
      "<div style='padding:40px;color:#ff8080'>Three.js failed to load (offline & uncached). Reconnect once to cache it.</div>";
    return;
  }
  // ---- seeded PRNG for reproducible placement & idle motion ----
  let _s = 1337 >>> 0;
  function rnd(){ _s ^= _s<<13; _s^=_s>>>17; _s^=_s<<5; _s>>>=0; return _s/4294967296; }

  const HEALTH_COLOR = { security:0xff4d4d, fragile:0xff9636, untested:0xffc23d, hub:0x4d9bff, ok:0x36c98f };

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e17);
  scene.fog = new THREE.Fog(0x0a0e17, 60, 220);

  const camera = new THREE.PerspectiveCamera(55, innerWidth/innerHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ antialias:true });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  document.getElementById("scene").appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0x8fa6d6, 0.55));
  const sun = new THREE.DirectionalLight(0xffffff, 0.85);
  sun.position.set(40, 80, 30); scene.add(sun);
  const rim = new THREE.DirectionalLight(0x4d7bff, 0.3);
  rim.position.set(-50, 30, -40); scene.add(rim);

  // ---- ground & grid (the office floor) ----
  const buildings = DATA.buildings;
  const N = buildings.length;
  const cols = Math.max(1, Math.ceil(Math.sqrt(N)));
  const SP = 10;                       // spacing between plots
  const span = cols * SP;
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(span+40, span+40),
    new THREE.MeshLambertMaterial({ color:0x10182a }));
  ground.rotation.x = -Math.PI/2; ground.position.y = 0; scene.add(ground);
  const grid = new THREE.GridHelper(span+40, (cols+4)*2, 0x1c2842, 0x141d30);
  grid.position.y = 0.02; scene.add(grid);

  // ---- buildings ----
  const meshes = [];
  const locs = buildings.map(b=>b.loc);
  const maxLoc = Math.max(1, ...locs);
  buildings.forEach((b, i) => {
    const cx = (i % cols) - (cols-1)/2;
    const cz = Math.floor(i/cols) - (cols-1)/2;
    const x = cx*SP, z = cz*SP;
    const h = 2 + 22 * Math.sqrt(b.loc/maxLoc);
    const w = 3 + 2.2*Math.min(3, Math.sqrt((b.complexity||1)/6));
    const geo = new THREE.BoxGeometry(w, h, w);
    const col = HEALTH_COLOR[b.health] ?? 0x36c98f;
    const mat = new THREE.MeshLambertMaterial({ color: col });
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, h/2, z);
    m.userData = { b, baseY:h/2, x, z, h };
    scene.add(m);
    meshes.push(m);
    // lit "rooftop" marker pulses for buildings with findings
    if (b.findings > 0) {
      const cap = new THREE.Mesh(new THREE.BoxGeometry(w*0.5, 0.6, w*0.5),
        new THREE.MeshBasicMaterial({ color:0xff5a5a }));
      cap.position.set(x, h+0.4, z); cap.userData.pulse = true; scene.add(cap);
    }
  });

  function plotOf(i){ const m = meshes[i]; return m ? {x:m.userData.x, z:m.userData.z, h:m.userData.h} : {x:0,z:0,h:4}; }

  // ---- workers (Apex agents walking their rounds) ----
  function makePerson(hex){
    const g = new THREE.Group();
    const cm = new THREE.MeshLambertMaterial({ color:new THREE.Color(hex) });
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.45,0.6,1.6,10), cm);
    body.position.y = 1.0; g.add(body);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.42,12,12),
      new THREE.MeshLambertMaterial({ color:0xf2d9c0 }));
    head.position.y = 2.1; g.add(head);
    const legM = new THREE.MeshLambertMaterial({ color:0x223 });
    const l1 = new THREE.Mesh(new THREE.BoxGeometry(0.28,0.9,0.28), legM); l1.position.set(-0.22,0.45,0); g.add(l1);
    const l2 = new THREE.Mesh(new THREE.BoxGeometry(0.28,0.9,0.28), legM); l2.position.set( 0.22,0.45,0); g.add(l2);
    g.userData.legs = [l1,l2];
    return g;
  }

  const workers = DATA.workers.map((w, k) => {
    const g = makePerson(w.color);
    const startI = w.route[k % w.route.length];
    const p0 = plotOf(startI);
    const ang = rnd()*Math.PI*2, r = 3.2 + rnd()*1.5;
    g.position.set(p0.x + Math.cos(ang)*r, 0, p0.z + Math.sin(ang)*r);
    scene.add(g);
    return {
      g, route:w.route, role:w.role,
      ri: k % w.route.length,
      target: new THREE.Vector3(g.position.x, 0, g.position.z),
      wait: rnd()*2, phase: rnd()*6.28,
    };
  });

  function newTarget(wk){
    wk.ri = (wk.ri + 1) % wk.route.length;
    const p = plotOf(wk.route[wk.ri]);
    const ang = rnd()*Math.PI*2, r = 3.0 + rnd()*1.8;
    wk.target.set(p.x + Math.cos(ang)*r, 0, p.z + Math.sin(ang)*r);
  }
  workers.forEach(newTarget);

  // ---- custom orbit camera ----
  let theta = 0.7, phi = 0.95, rad = Math.max(70, span*1.2);
  let drag=false, px=0, py=0;
  const target = new THREE.Vector3(0, 4, 0);
  function applyCam(){
    camera.position.set(
      target.x + rad*Math.sin(phi)*Math.cos(theta),
      target.y + rad*Math.cos(phi),
      target.z + rad*Math.sin(phi)*Math.sin(theta));
    camera.lookAt(target);
  }
  const dom = renderer.domElement;
  dom.addEventListener("mousedown", e=>{ drag=true; px=e.clientX; py=e.clientY; });
  addEventListener("mouseup", ()=> drag=false);
  addEventListener("mousemove", e=>{
    if(drag){ theta -= (e.clientX-px)*0.005; phi = Math.max(0.2, Math.min(1.45, phi - (e.clientY-py)*0.005));
      px=e.clientX; py=e.clientY; }
    moveTip(e);
  });
  dom.addEventListener("wheel", e=>{ rad = Math.max(25, Math.min(260, rad + e.deltaY*0.08)); e.preventDefault(); }, {passive:false});

  // ---- hover tooltip via raycaster ----
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  const tip = document.getElementById("tip");
  function moveTip(e){
    mouse.x = (e.clientX/innerWidth)*2-1; mouse.y = -(e.clientY/innerHeight)*2+1;
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(meshes)[0];
    if(hit){ const b = hit.object.userData.b;
      tip.style.display="block"; tip.style.left=(e.clientX+14)+"px"; tip.style.top=(e.clientY+14)+"px";
      tip.innerHTML = "<b>"+b.name+"</b><br>"+b.loc+" LOC · cx "+b.complexity+" · fan-in "+b.fan_in+
        "<br>"+(b.findings?("<span style='color:#ff7a7a'>"+b.findings+" security finding(s)</span><br>"):"")+
        "tests: "+b.tests+" · <span class='hl'>"+b.health+"</span>";
    } else tip.style.display="none";
  }

  // ---- HUD fill ----
  document.getElementById("proj").textContent = DATA.project;
  document.getElementById("grade").textContent = DATA.grade.letter;
  document.getElementById("score").textContent = DATA.grade.score + " / 100 · " + DATA.generated;
  const t = DATA.totals;
  document.getElementById("kpis").innerHTML =
    kpi(t.buildings,"modules")+kpi(t.findings,"findings")+kpi(t.untested,"untested")+kpi(t.workers,"workers");
  function kpi(v,l){ return "<div class='kpi'><b>"+v+"</b><span>"+l+"</span></div>"; }

  // ---- animation loop ----
  const clock = new THREE.Clock();
  function tick(){
    const dt = Math.min(0.05, clock.getDelta());
    const tt = clock.elapsedTime;
    // workers walk
    workers.forEach(wk=>{
      const pos = wk.g.position, tgt = wk.target;
      const dx = tgt.x-pos.x, dz = tgt.z-pos.z, d = Math.hypot(dx,dz);
      if(d < 0.6){ wk.wait -= dt; if(wk.wait<=0){ newTarget(wk); wk.wait = 1.2 + rnd()*2.5; } }
      else {
        const v = 5.5*dt/d; pos.x += dx*v; pos.z += dz*v;
        wk.g.rotation.y = Math.atan2(dx, dz);
        const sw = Math.sin(tt*9 + wk.phase)*0.5;
        wk.g.userData.legs[0].rotation.x = sw; wk.g.userData.legs[1].rotation.x = -sw;
        wk.g.position.y = Math.abs(Math.sin(tt*9 + wk.phase))*0.12;
      }
    });
    // pulse finding rooftops
    scene.children.forEach(o=>{ if(o.userData && o.userData.pulse){
      o.material.opacity = 1; o.scale.y = 1 + Math.sin(tt*4)*0.4; }});
    applyCam();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  applyCam(); tick();

  addEventListener("resize", ()=>{
    camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });
})();
</script>
</body>
</html>
"""
