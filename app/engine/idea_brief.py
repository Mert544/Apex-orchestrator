"""Work briefs — a design-level idea becomes an actionable engineering brief.

Executable ideas flow into `--actions`; design-level ideas (evolve this hub,
integrate these modules, parameterize for reuse) used to dead-end as
"surfaced for a human". A brief turns one into a concrete work order, with
nothing invented:

  - **why** — the idea's grounding fact and rationale, verbatim;
  - **measured context** — fan-in, LOC, complexity the engine already
    attached to the tree;
  - **work plan** — the fractal facet vocabulary doubles as the checklist:
    the idea's lens supplies the aspects, each aspect its sub-concerns;
  - **definition of done** — checks the engine itself will verify on the
    next run (the idea stops surfacing in `--roadmap --diff`, the grade
    holds, the suite stays green).

Deterministic, stdlib-only: the same tree always yields the same brief.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.idea_permutation import _FACET_SUBASPECTS, _FACETS, convergence_labels, convergence_plan
from app.models.idea import IdeaNode, IdeaTreeReport


@dataclass
class Brief:
    branch_path: str
    title: str
    subject: str
    operator: str
    why: list[str] = field(default_factory=list)
    measured: dict[str, Any] = field(default_factory=dict)
    plan: list[tuple[str, list[str]]] = field(default_factory=list)  # aspect -> sub-concerns
    phased_steps: list[dict] = field(default_factory=list)           # convergence mini-roadmap
    done_when: list[str] = field(default_factory=list)
    # Evidence binding (the burndown): concern phrase -> [(line, detail), …]
    # found in the subject's ACTUAL code. An evidenced item is "done" when a
    # later scan no longer finds its evidence — measured, not self-reported.
    evidence: dict[str, list] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_path": self.branch_path, "title": self.title,
            "subject": self.subject, "operator": self.operator,
            "why": self.why, "measured": self.measured,
            "plan": [{"aspect": a, "concerns": c} for a, c in self.plan],
            "phased_steps": self.phased_steps, "done_when": self.done_when,
            "evidence": {k: [list(e) for e in v] for k, v in self.evidence.items()},
        }


# A design root's fact label hints which lens vocabulary fits its work best.
_LABEL_LENS = {
    "dependency-hub": "generalize",
    "symbol-hub": "generalize",
    "entrypoint": "extend",
    "top-directory": "integrate",
    "config": "generalize",
    "churn-hotspot": "simplify",
    "debt-markers": "simplify",
    "security-finding": "harden",
    "sensitive-path": "harden",
    "correctness-bug": "harden",
    "fragile": "test",
    "untested": "test",
    "critical-untested": "test",
    "shallow-coverage": "test",
    "complexity-hotspot": "simplify",
    "hotspot-function": "test",
    "knowledge-risk": "document",
    "doc-drift": "document",
    "dead-parameter": "simplify",
}


def _lens_for(node: IdeaNode) -> str:
    if node.operator in _FACETS:
        return node.operator
    label = node.source_facts[0].split(":")[0].strip() if node.source_facts else ""
    return _LABEL_LENS.get(label, "extend")


def build_brief(report: IdeaTreeReport, branch_path: str = "",
                subject: str = "") -> Brief | None:
    """The brief for ``branch_path``/``subject`` — or for the most valuable
    design-level idea when neither is given. None when nothing matches.

    Prefer ``subject`` (a module path) when saving for a later ``--check``:
    branch paths drift run to run as the tree reseeds, but a subject names
    the same work tomorrow.
    """
    from app.engine.idea_action_bridge import IdeaActionBridge

    bridge = IdeaActionBridge()
    candidates: list[IdeaNode] = []
    for node in report.ideas:
        if branch_path and node.branch_path == branch_path:
            candidates = [node]
            break
        if subject and not branch_path:
            base = node.subject.split(" :: ", 1)[0].split("::", 1)[0]
            if base == subject:
                candidates.append(node)
        elif not branch_path and not bridge.plan_idea(node).executable:
            candidates.append(node)
    if not candidates:
        return None
    node = (candidates[0] if branch_path
            else max(candidates, key=lambda n: (n.value, n.branch_path)))

    subject_module = node.subject.split(" :: ", 1)[0].split("::", 1)[0]
    fan_in = (report.stats.get("fan_in") or {}).get(subject_module)
    metrics = (report.stats.get("metrics") or {}).get(subject_module) or {}
    measured = {k: v for k, v in {
        "fan_in": fan_in,
        "loc": metrics.get("loc"),
        "complexity": metrics.get("complexity"),
        "symbols": metrics.get("symbols"),
    }.items() if v is not None}

    lens = _lens_for(node)
    plan = [(aspect, list(_FACET_SUBASPECTS.get(aspect, []))) for aspect in _FACETS[lens]]

    conv = convergence_labels(node)
    phased = convergence_plan(conv) if len(conv) >= 2 else []

    # Bind each checklist phrase to evidence in the subject's actual code,
    # so the work order starts life knowing which items are VERIFIED concerns
    # and which are hypotheses — the burndown baseline.
    evidence = _bind_evidence(report, subject_module, plan)

    done = [
        "`pytest -q` stays green (every change test-verified).",
        f"`apex ideate --roadmap --diff` no longer surfaces “{node.title}” "
        "— the engine itself confirms the work landed.",
        "`apex grade` does not drop.",
    ]
    if fan_in:
        done.insert(1, f"The {fan_in} importing module(s) still pass their tests "
                       "(blast radius re-verified).")

    return Brief(
        branch_path=node.branch_path, title=node.title, subject=node.subject,
        operator=lens,
        why=[*node.source_facts[:2], node.rationale] if node.rationale else list(node.source_facts[:2]),
        measured=measured, plan=plan, phased_steps=phased, done_when=done,
        evidence=evidence,
    )


def _subject_source(report: IdeaTreeReport, subject_module: str) -> str | None:
    if not subject_module.endswith(".py"):
        return None
    root = Path(getattr(report, "project_root", "") or ".")
    try:
        return (root / subject_module).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _bind_evidence(report: IdeaTreeReport, subject_module: str,
                   plan: list[tuple[str, list[str]]]) -> dict[str, list]:
    """Evidence for every aspect/concern phrase, from the subject's code."""
    from app.engine.facet_evidence import evidence_for_facet

    source = _subject_source(report, subject_module)
    if not source:
        return {}
    out: dict[str, list] = {}
    for aspect, concerns in plan:
        for phrase in (aspect, *concerns):
            found = evidence_for_facet(source, phrase)
            if found:
                out[phrase] = [list(e) for e in found]
    return out


# --- the burndown: save a brief, check it later against the live code --------

def _brief_path(project_root: str | Path, branch_path: str) -> Path:
    safe = branch_path.replace("/", "_")
    return Path(project_root) / ".apex" / "briefs" / f"{safe}.json"


def save_brief(brief: Brief, project_root: str | Path) -> Path:
    """Persist the brief (with its evidence baseline) for a later --check."""
    path = _brief_path(project_root, brief.branch_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brief.to_dict(), indent=2), encoding="utf-8")
    return path


def check_brief(project_root: str | Path, branch_path: str) -> dict | None:
    """Re-measure a saved brief against the CURRENT code.

    Every evidenced item is re-checked: evidence gone → **resolved** (the scan
    says so, not the engineer); still present → open, with today's line.
    Returns None when no saved brief exists.
    """
    from app.engine.facet_evidence import evidence_for_facet

    path = _brief_path(project_root, branch_path)
    if not path.exists():
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    subject_module = saved.get("subject", "").split(" :: ", 1)[0].split("::", 1)[0]
    try:
        source = (Path(project_root) / subject_module).read_text(
            encoding="utf-8", errors="ignore")
    except OSError:
        source = ""
    resolved, open_items = [], []
    for phrase, was in (saved.get("evidence") or {}).items():
        now = evidence_for_facet(source, phrase) if source else []
        if now:
            open_items.append({"concern": phrase, "evidence": [list(e) for e in now]})
        else:
            resolved.append({"concern": phrase, "was": was})
    return {"branch_path": branch_path, "title": saved.get("title", ""),
            "subject": subject_module, "resolved": resolved, "open": open_items,
            "measured_total": len(resolved) + len(open_items)}


def render_check_markdown(check: dict) -> str:
    total = check["measured_total"]
    done = len(check["resolved"])
    lines = [f"# Brief burndown — `{check['branch_path']}` {check['title']}", ""]
    if total == 0:
        lines += ["_This brief had no evidence-bound items — progress here is",
                  "judged by the definition-of-done, not by the burndown._", ""]
        return "\n".join(lines)
    lines.append(f"**{done}/{total} measured item(s) resolved** — the scan decided, not a checkbox.")
    lines.append("")
    for item in check["resolved"]:
        was = item["was"][0] if item["was"] else ["?", ""]
        lines.append(f"- [x] {item['concern']} — evidence gone (was line {was[0]}: {was[1]})")
    for item in check["open"]:
        now = item["evidence"][0]
        lines.append(f"- [ ] {item['concern']} — 📌 still at line {now[0]}: {now[1]}")
    lines.append("")
    return "\n".join(lines)


def render_brief_markdown(brief: Brief) -> str:
    lines = [f"# Work brief — `{brief.branch_path}` {brief.title}", ""]
    lines.append(f"**Subject:** `{brief.subject}` · **lens:** {brief.operator}")
    if brief.measured:
        facts = " · ".join(f"{k} {v}" for k, v in brief.measured.items())
        lines.append(f"**Measured:** {facts}")
    lines.append("")
    if brief.why:
        lines.append("## Why this, why now")
        lines += [f"- {w}" for w in brief.why]
        lines.append("")
    if brief.phased_steps:
        lines.append("## Phased steps (independent analyses converge here)")
        for s in brief.phased_steps:
            mark = "⚙️ " if s.get("executable") else ""
            lines.append(f"- [{s['phase']}] {mark}{s['step']}")
        lines.append("")
    lines.append("## Work plan (the fractal vocabulary as a checklist)")
    for aspect, concerns in brief.plan:
        pin = brief.evidence.get(aspect)
        suffix = f"  📌 line {pin[0][0]}: {pin[0][1]}" if pin else ""
        lines.append(f"- **{aspect}**{suffix}")
        for c in concerns:
            cpin = brief.evidence.get(c)
            csuffix = f"  📌 line {cpin[0][0]}: {cpin[0][1]}" if cpin else ""
            lines.append(f"  - [ ] {c}{csuffix}")
    lines.append("")
    lines.append("## Definition of done — the engine verifies it")
    lines += [f"- {d}" for d in brief.done_when]
    lines.append("")
    return "\n".join(lines)
