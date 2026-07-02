"""The Apex agenda — "what should this project do next", in three honest lanes.

V2 of the living-assistant program (``docs/rnd/apex-vizyon-yasayan-asistan.md``):
the vault (V1) made Apex's memory visible in one place; the agenda makes its
JUDGEMENT visible in one place. It is a pure deterministic SYNTHESIS of engines
that already exist — :func:`app.engine.develop_readiness.develop_readiness`
(what is fixable now vs flag-only), :func:`app.engine.move_value.
scored_move_value` (buyer value, memory- and realization-demoted), ``IdeaMemory``
and ``value_reliability`` (what this project has TAUGHT Apex) — with no new
detector, no writes, no clock, and no LLM.

Three lanes:

* **landable** — findings Apex can prove-land NOW (readiness's ``fixable_now``
  bucket), ranked by ``scored_move_value`` (static buyer value × the project's
  own feasibility/realization track record — demote-only, neutral on a fresh
  repo) with a stable file/line tiebreak.
* **human** — findings that genuinely need a person (``flag_only``: design
  tasks, security judgement calls), carried with their rationale. The agenda
  never promises these; it hands them over honestly.
* **watched** — operators this project's memory has LEARNED to distrust
  (feasibility or realization factor below neutral): surfaced so a demotion is
  a visible, explained state instead of silent ranking gravity.

The agenda RECOMMENDS only — nothing here writes to the project. Landing stays
behind the existing preview-first ``develop``/``assist``/``dream`` gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.engine.develop_readiness import develop_readiness
from app.engine.idea_memory import IdeaMemory
from app.engine.move_value import scored_move_value
from app.engine.value_reliability import operator_realization_factors

SCHEMA_VERSION = 1
AGENDA_REL = ".apex/agenda.json"

# One screen per lane: entries beyond the cap are COUNTED, never silently cut.
_LANE_CAP = 10


def _landable_lane(buckets: dict[str, list[dict[str, Any]]],
                   memory: IdeaMemory | None,
                   realization: dict[str, float]) -> list[dict[str, Any]]:
    entries = []
    for rec in buckets.get("fixable_now", []):
        operator = rec.get("fix_kind", "")
        value = scored_move_value(operator, memory, realization)
        entries.append({
            "fix_kind": operator,
            "file": rec.get("file", ""),
            "line": rec.get("line", 0),
            "category": rec.get("category", ""),
            "value": value,
        })
    entries.sort(key=lambda e: (-e["value"], e["file"], e["line"], e["fix_kind"]))
    for i, e in enumerate(entries, 1):
        e["rank"] = i
    return entries


def _human_lane(buckets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{
        "fix_kind": rec.get("fix_kind", ""),
        "file": rec.get("file", ""),
        "line": rec.get("line", 0),
        "category": rec.get("category", ""),
        "rationale": rec.get("message", ""),
    } for rec in buckets.get("flag_only", [])]


def _watched_lane(operators: set[str], memory: IdeaMemory | None,
                  realization: dict[str, float]) -> list[dict[str, Any]]:
    """Operators whose learned factors sit BELOW neutral — visible caution.

    Only operators the agenda actually considered (this run's findings) are
    reported, so the lane reads as "of today's work, these carry learned
    caution" rather than a global memory dump."""
    watched = []
    for op in sorted(operators):
        feasibility = memory.feasibility_factor(op) if memory is not None else 1.0
        realized = realization.get(op, 1.0)
        if feasibility >= 1.0 and realized >= 1.0:
            continue
        notes = []
        if feasibility < 1.0:
            notes.append(f"feasibility {feasibility:.2f} (rollbacks on this project)")
        if realized < 1.0:
            notes.append(f"realization {realized:.2f} (verified value under-delivered)")
        watched.append({"operator": op,
                        "feasibility": round(feasibility, 4),
                        "realization": round(realized, 4),
                        "note": "; ".join(notes)})
    return watched


def build_agenda(project_root: str | Path) -> dict[str, Any]:
    """The three-lane agenda for ``project_root`` (pure read, deterministic)."""
    root = str(Path(project_root))
    readiness = develop_readiness(root=root, weight_by_reliability=True)
    buckets = readiness.get("buckets", {})
    try:
        memory: IdeaMemory | None = IdeaMemory.load(root)
    except (OSError, ValueError):
        memory = None
    realization = operator_realization_factors(root)
    considered = {rec.get("fix_kind", "")
                  for lane in buckets.values() for rec in lane if rec.get("fix_kind")}
    return {
        "schema_version": SCHEMA_VERSION,
        "readiness_score": readiness.get("score", 0.0),
        "total_findings": readiness.get("total", 0),
        "lanes": {
            "landable": _landable_lane(buckets, memory, realization),
            "human": _human_lane(buckets),
            "watched": _watched_lane(considered, memory, realization),
        },
    }


def write_agenda(project_root: str | Path) -> Path:
    """Refresh ``.apex/agenda.json`` from the live signals and return its path.

    The agenda module is the file's ONLY writer (the vault's single-writer
    contract, mirrored), and the dump is byte-deterministic — an unchanged
    repo rewrites identical bytes, so the artifact diff IS the agenda change.
    The living loop (``apex daemon``) calls this once per cycle; the file is
    fully rebuildable and deleting it loses nothing."""
    root = Path(project_root)
    agenda = build_agenda(root)
    path = root / AGENDA_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(agenda, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _lane_header(title: str, entries: list[dict[str, Any]]) -> str:
    shown = min(len(entries), _LANE_CAP)
    suffix = f" (showing {shown} of {len(entries)})" if len(entries) > _LANE_CAP else ""
    return f"## {title} — {len(entries)}{suffix}"


def render_agenda_markdown(agenda: dict[str, Any]) -> str:
    """A one-screen, three-lane view; overflow is counted, never hidden."""
    lanes = agenda["lanes"]
    lines = ["# Apex agenda", ""]
    lines.append(
        f"{agenda['total_findings']} finding(s); "
        f"{len(lanes['landable'])} provable-landable now "
        f"(readiness {agenda['readiness_score']:.0%}). "
        "Recommendations only — landing stays behind the preview-first gates.")
    lines += ["", _lane_header("Landable (prove-and-land now)", lanes["landable"])]
    for e in lanes["landable"][:_LANE_CAP]:
        lines.append(f"{e['rank']}. `{e['fix_kind']}` — {e['file']}:{e['line']}"
                     f" (value {e['value']:.2f})")
    if not lanes["landable"]:
        lines.append("_Nothing provable-landable right now._")
    lines += ["", _lane_header("Human decision (handed over honestly)", lanes["human"])]
    for e in lanes["human"][:_LANE_CAP]:
        rationale = e["rationale"] or e["category"] or "needs a person"
        lines.append(f"- `{e['fix_kind'] or e['category']}` — {e['file']}:{e['line']}"
                     f" — {rationale}")
    if not lanes["human"]:
        lines.append("_No human-decision items._")
    lines += ["", _lane_header("Watched (learned caution)", lanes["watched"])]
    for e in lanes["watched"][:_LANE_CAP]:
        lines.append(f"- `{e['operator']}` — {e['note']}")
    if not lanes["watched"]:
        lines.append("_No learned demotions among today's operators._")
    return "\n".join(lines) + "\n"
