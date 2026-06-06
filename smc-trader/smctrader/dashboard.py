"""Self-contained HTML dashboard for the SMC bot.

Renders the candle series with the Smart Money Concepts the bot found overlaid —
order blocks, fair value gaps, liquidity sweeps, market-structure (BOS/CHoCH)
events, and the trade setups — plus a backtest stats panel. Pure canvas 2D, no
external libraries, so the file works fully offline.
"""

from __future__ import annotations

import json

from .backtest import backtest
from .candles import Candle
from .fvg import find_fvgs
from .liquidity import find_sweeps
from .order_blocks import find_order_blocks
from .signals import generate_setups
from .structure import current_trend, market_structure


def build_model(candles: list[Candle], risk_pct: float = 1.0, min_rr: float = 1.5) -> dict:
    """Gather everything the dashboard draws from one candle series."""
    report = backtest(candles, risk_pct=risk_pct, min_rr=min_rr)
    return {
        "candles": [{"t": c.time, "o": c.open, "h": c.high, "l": c.low, "c": c.close} for c in candles],
        "order_blocks": [
            {"index": o.index, "direction": o.direction, "low": o.low, "high": o.high}
            for o in find_order_blocks(candles)
        ],
        "fvgs": [
            {"index": f.index, "direction": f.direction, "low": f.low, "high": f.high}
            for f in find_fvgs(candles)
        ],
        "sweeps": [{"index": s.index, "side": s.side, "level": s.level} for s in find_sweeps(candles)],
        "structure": [
            {"index": e.index, "event": e.event, "direction": e.direction, "price": e.price}
            for e in market_structure(candles)
        ],
        "setups": [
            {"index": s.index, "direction": s.direction, "entry": s.entry,
             "stop": s.stop, "target": s.target, "rr": s.rr}
            for s in generate_setups(candles, min_rr=min_rr)
        ],
        "stats": {
            "trend": current_trend(candles) or "—",
            "candles": len(candles),
            "trades": len(report.trades),
            "wins": report.wins,
            "losses": report.losses,
            "win_rate": report.win_rate,
            "total_r": report.total_r,
            "end_balance": report.end_balance,
        },
    }


def build_dashboard(candles: list[Candle], risk_pct: float = 1.0, min_rr: float = 1.5) -> str:
    """Build the self-contained HTML dashboard for a candle series."""
    model = build_model(candles, risk_pct=risk_pct, min_rr=min_rr)
    return _HTML.replace("/*__DATA__*/", json.dumps(model, separators=(",", ":")))


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SMC Trader — Chart</title>
<style>
  html,body{margin:0;height:100%;background:#0b0f1a;color:#dce6ff;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;overflow:hidden}
  #chart{position:fixed;inset:0}
  .panel{position:fixed;background:rgba(15,21,36,.9);border:1px solid #23304a;border-radius:10px;backdrop-filter:blur(6px)}
  #hud{top:14px;left:14px;padding:12px 14px;min-width:200px}
  #hud h1{margin:0 0 8px;font-size:15px}
  #hud .row{display:flex;justify-content:space-between;gap:18px;font-size:12px;margin:3px 0}
  #hud .row b{color:#fff}
  .up{color:#26c281}.down{color:#ff5a5a}
  #legend{bottom:14px;left:14px;padding:10px 12px;font-size:11px}
  #legend .row{display:flex;align-items:center;gap:7px;margin:3px 0}
  #legend .sw{width:14px;height:10px;border-radius:2px}
  #tip{position:fixed;pointer-events:none;display:none;padding:6px 9px;font-size:12px;background:rgba(6,10,20,.95);border:1px solid #2c3c5c;border-radius:7px;z-index:5}
</style>
</head>
<body>
<canvas id="chart"></canvas>
<div id="hud" class="panel"><h1>📈 SMC Trader</h1><div id="stats"></div></div>
<div id="legend" class="panel">
  <div class="row"><span class="sw" style="background:#26c281"></span>bullish order block</div>
  <div class="row"><span class="sw" style="background:#ff5a5a"></span>bearish order block</div>
  <div class="row"><span class="sw" style="background:rgba(120,170,255,.5)"></span>fair value gap</div>
  <div class="row"><span class="sw" style="background:#ffcf3d"></span>liquidity sweep</div>
  <div class="row"><span class="sw" style="background:#9b7cff"></span>BOS / CHoCH</div>
  <div class="row"><span class="sw" style="background:#36d0e0"></span>trade setup (entry/stop/target)</div>
</div>
<div id="tip"></div>
<script>
const DATA = /*__DATA__*/;
(function(){
  const cv = document.getElementById("chart"), ctx = cv.getContext("2d");
  const C = DATA.candles;
  const ML = 8, MR = 70, MT = 16, MB = 28;   // margins (right margin for price axis)
  let W, H;
  const lo = Math.min(...C.map(c=>c.l)), hi = Math.max(...C.map(c=>c.h));
  const pad = (hi - lo) * 0.05 || 1;
  const minP = lo - pad, maxP = hi + pad;
  const n = C.length;

  function resize(){ W = cv.width = innerWidth; H = cv.height = innerHeight; draw(); }
  function x(i){ return ML + (i) * (W - ML - MR) / Math.max(1, n - 1); }
  function y(p){ return MT + (maxP - p) / (maxP - minP) * (H - MT - MB); }
  const cw = () => Math.max(1.5, (W - ML - MR) / n * 0.62);

  function zone(i0, i1, p0, p1, fill){
    ctx.fillStyle = fill;
    const xa = x(i0), xb = x(i1);
    ctx.fillRect(xa, y(Math.max(p0,p1)), Math.max(2, xb - xa), Math.abs(y(p0) - y(p1)));
  }

  function draw(){
    ctx.clearRect(0,0,W,H);
    // price grid + axis
    ctx.strokeStyle = "#16203a"; ctx.fillStyle = "#5b6b8c"; ctx.font = "10px sans-serif"; ctx.lineWidth = 1;
    for(let k=0;k<=5;k++){ const p = minP + (maxP-minP)*k/5, yy = y(p);
      ctx.beginPath(); ctx.moveTo(ML, yy); ctx.lineTo(W-MR, yy); ctx.stroke();
      ctx.fillText(p.toFixed(2), W-MR+4, yy+3); }

    // order blocks (extend right a few candles)
    DATA.order_blocks.forEach(o=>{
      const f = o.direction==="bullish" ? "rgba(38,194,129,.16)" : "rgba(255,90,90,.16)";
      zone(o.index, Math.min(n-1, o.index+12), o.low, o.high, f);
    });
    // fair value gaps
    DATA.fvgs.forEach(g=> zone(g.index, Math.min(n-1, g.index+4), g.low, g.high, "rgba(120,170,255,.18)"));

    // candles
    C.forEach((c,i)=>{
      const up = c.c >= c.o, col = up ? "#26c281" : "#ff5a5a";
      ctx.strokeStyle = col; ctx.fillStyle = col;
      const xi = x(i);
      ctx.beginPath(); ctx.moveTo(xi, y(c.h)); ctx.lineTo(xi, y(c.l)); ctx.stroke();
      const yo = y(c.o), yc = y(c.c), w = cw();
      ctx.fillRect(xi - w/2, Math.min(yo,yc), w, Math.max(1, Math.abs(yc-yo)));
    });

    // structure events (BOS/CHoCH)
    ctx.font = "9px sans-serif";
    DATA.structure.forEach(e=>{
      const xi = x(e.index); ctx.strokeStyle = "rgba(155,124,255,.6)";
      ctx.beginPath(); ctx.moveTo(xi, MT); ctx.lineTo(xi, H-MB); ctx.stroke();
      ctx.fillStyle = "#b9a6ff"; ctx.fillText(e.event, xi+2, y(e.price)-3);
    });
    // liquidity sweeps
    DATA.sweeps.forEach(s=>{
      const xi = x(s.index), yy = y(s.level); ctx.fillStyle = "#ffcf3d";
      ctx.beginPath();
      if(s.side==="sell"){ ctx.moveTo(xi, yy+7); ctx.lineTo(xi-4, yy); ctx.lineTo(xi+4, yy); }
      else { ctx.moveTo(xi, yy-7); ctx.lineTo(xi-4, yy); ctx.lineTo(xi+4, yy); }
      ctx.closePath(); ctx.fill();
    });
    // trade setups: entry/stop/target lines
    DATA.setups.forEach(s=>{
      const xa = x(s.index), xb = W-MR;
      const lvls = [["entry", s.entry, "#36d0e0"], ["stop", s.stop, "#ff5a5a"], ["target", s.target, "#26c281"]];
      lvls.forEach(([lab,p,col])=>{
        ctx.strokeStyle = col; ctx.setLineDash([4,3]);
        ctx.beginPath(); ctx.moveTo(xa, y(p)); ctx.lineTo(xb, y(p)); ctx.stroke(); ctx.setLineDash([]);
      });
      ctx.fillStyle = "#36d0e0"; ctx.font = "9px sans-serif";
      ctx.fillText((s.direction==="long"?"▲":"▼")+" "+s.rr+"R", xa+2, y(s.entry)-3);
    });
  }

  // stats panel
  const s = DATA.stats;
  const tdir = s.trend.includes("bull") ? "up" : (s.trend.includes("bear") ? "down" : "");
  document.getElementById("stats").innerHTML =
    row("Trend", "<span class='"+tdir+"'>"+s.trend+"</span>") +
    row("Candles", s.candles) + row("Setups", DATA.setups.length) +
    row("Order blocks", DATA.order_blocks.length) + row("FVGs", DATA.fvgs.length) +
    row("Sweeps", DATA.sweeps.length) +
    row("Trades", s.trades) +
    row("Win rate", (s.win_rate*100).toFixed(0)+"%") +
    row("Total R", "<span class='"+(s.total_r>=0?"up":"down")+"'>"+s.total_r+"</span>") +
    row("Equity", "$"+s.end_balance);
  function row(k,v){ return "<div class='row'><span>"+k+"</span><b>"+v+"</b></div>"; }

  // hover tooltip
  const tip = document.getElementById("tip");
  cv.addEventListener("mousemove", e=>{
    const i = Math.round((e.clientX - ML) / Math.max(1,(W-ML-MR)) * (n-1));
    if(i>=0 && i<n){ const c = C[i];
      tip.style.display="block"; tip.style.left=(e.clientX+12)+"px"; tip.style.top=(e.clientY+12)+"px";
      tip.innerHTML = "#"+i+" O "+c.o+" H "+c.h+" L "+c.l+" C "+c.c;
    } else tip.style.display="none";
  });
  cv.addEventListener("mouseleave", ()=> tip.style.display="none");

  addEventListener("resize", resize); resize();
})();
</script>
</body>
</html>
"""
