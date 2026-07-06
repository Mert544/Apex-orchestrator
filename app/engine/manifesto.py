"""The project's LIVING MANIFESTO — the architectural laws Apex has LEARNED here.

Apex accumulates a lot of experience — which fixes land, which roll back, which
idioms finish real code — but that wisdom is scattered across four learners.
This module synthesises them into ONE durable, human-readable "constitution": the
stated principles a maintainer (and Apex's own planner) should follow ON THIS
project, each backed by counted evidence and recency-weighted so a lesson from a
retired design fades.

Four kinds of law, each read from an EXISTING learner (this module invents no new
signal — it states what the evidence already implies):

* **AVOID** — from ``counterfactual_learning.near_miss_insights``: an
  ``(action | trait)`` whose failure rate cleared the avoid threshold ("we tried
  this and it rolled back N/M times"). The founder's "we tried X 10 times, rolled
  back 8, ban X".
* **TRUST** — from ``proof_history.learned_reliability_decayed``: an action whose
  recent landings are reliably clean (score ≥ :data:`_TRUST_MIN`).
* **FRAGILE** — from ``proof_history.summarise_fix_track_record`` by-module: a
  module that keeps rolling changes back (reliability < :data:`_FRAGILE_MAX` over
  ≥ :data:`_MIN_MODULE_ATTEMPTS` decided outcomes).
* **PROVEN IDIOM** — from ``native_proof_memory.decayed_reliability``: a native
  code-shape the lane has repeatedly, recently landed here.

Pure and deterministic: same ``.apex`` artifacts → same manifesto (no clock/
random; all recency comes from the loaders' rank-based decay). A fresh project
with no history yields an empty manifesto (Apex has learned nothing to legislate
yet); never raises — every underlying loader tolerates missing/malformed state.
Zero-token, offline. READ-ONLY: it states laws, it does not enforce them (the
planner's ``fix_risk_model`` already consults the same avoid/reliability signals).
"""

from __future__ import annotations

from pathlib import Path

# An action is TRUSTED once its recency-weighted landing score clears this, and a
# module is FRAGILE below this landing ratio over at least this many decided
# outcomes — fixed so the manifesto is a deterministic function of the evidence.
_TRUST_MIN = 0.8
_FRAGILE_MAX = 0.5
_MIN_MODULE_ATTEMPTS = 3

__all__ = [
    "derive_manifesto",
    "render_manifesto_markdown",
]


def _trust_laws(history: list[dict]) -> list[dict]:
    """Actions whose recent landings are reliably clean — ``{action, score}``,
    most-trusted first."""
    from app.engine.proof_history import learned_reliability_decayed

    decayed = learned_reliability_decayed(history)
    trusted = [(a, s) for a, s in decayed.items() if s >= _TRUST_MIN]
    trusted.sort(key=lambda kv: (-kv[1], kv[0]))
    return [{"action": a, "score": s} for a, s in trusted]


def _fragile_laws(history: list[dict]) -> list[dict]:
    """Modules that keep rolling changes back — ``{module, reliability, rollbacks,
    total}``, least-reliable first."""
    from app.engine.proof_history import summarise_fix_track_record

    by_module = summarise_fix_track_record(history).get("by_module", {})
    out = []
    for module, stats in by_module.items():
        total = stats.get("total", 0)
        if total >= _MIN_MODULE_ATTEMPTS and stats.get("reliability", 1.0) < _FRAGILE_MAX:
            out.append({"module": module, "reliability": stats["reliability"],
                        "rollbacks": stats.get("rolled_back", 0), "total": total})
    out.sort(key=lambda r: (r["reliability"], -r["total"], r["module"]))
    return out


def _proven_idioms(root: str | Path) -> list[dict]:
    """Native code-shapes the lane has repeatedly, recently landed — ``{shape,
    score}``, most-proven first."""
    from app.engine.native_proof_memory import decayed_reliability

    scored = decayed_reliability(root)
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"shape": shape, "score": score} for shape, score in ranked]


def derive_manifesto(root: str | Path) -> dict:
    """The project's learned architectural laws, synthesised from every learner.

    Returns ``{avoid, trust, fragile, proven_idioms}`` — deterministic and
    evidence-backed; an empty project (no ``.apex`` history) yields all-empty
    lists. Never raises."""
    from app.engine.counterfactual_learning import near_miss_insights
    from app.engine.proof_history import load_proof_history

    history = load_proof_history(root)
    return {
        "avoid": list(near_miss_insights(history)),
        "trust": _trust_laws(history),
        "fragile": _fragile_laws(history),
        "proven_idioms": _proven_idioms(root),
    }


def _shape_label(key: str) -> str:
    """Render an arity-qualified idiom key (``2:p0 + p1``) as ``p0 + p1 (2-arg)``."""
    arity, _, body = key.partition(":")
    return f"{body} ({arity}-arg)" if arity.isdigit() else key


def _law_section(title: str, items: list, fmt) -> list[str]:
    """One law section — a heading then one bullet per item via ``fmt`` — or an
    empty list when there are no items (so the section vanishes cleanly)."""
    if not items:
        return []
    return [title, "", *[f"- {fmt(item)}" for item in items], ""]


def render_manifesto_markdown(manifesto: dict) -> str:
    """Render the manifesto as markdown for the CLI — the project's living
    constitution. An empty manifesto renders an honest "legislated no laws yet"."""
    avoid = manifesto.get("avoid") or []
    trust = manifesto.get("trust") or []
    fragile = manifesto.get("fragile") or []
    idioms = manifesto.get("proven_idioms") or []
    lines = ["# Apex manifesto — architectural laws learned on this project", ""]
    if not (avoid or trust or fragile or idioms):
        lines.append(
            "Apex has landed nothing here yet, so it has legislated no laws — the "
            "manifesto fills in as it accumulates proof-carrying experience.")
        return "\n".join(lines) + "\n"
    lines += _law_section("## ⛔ AVOID (proven to roll back here)", avoid, lambda x: x)
    lines += _law_section(
        "## ⚠ FRAGILE modules (changes keep rolling back)", fragile,
        lambda r: f"`{r['module']}` — {r['rollbacks']}/{r['total']} rolled back "
                  f"(reliability {r['reliability']:g})")
    lines += _law_section(
        "## ✅ TRUST (lands reliably here)", trust,
        lambda r: f"`{r['action']}` — reliability {r['score']:g}")
    lines += _law_section(
        "## 🧠 PROVEN idioms (native lane lands these)", idioms,
        lambda r: f"`{_shape_label(r['shape'])}` — score {r['score']:g}")
    return "\n".join(lines).rstrip() + "\n"
