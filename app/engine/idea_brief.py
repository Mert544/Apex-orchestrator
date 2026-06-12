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

from dataclasses import dataclass, field
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_path": self.branch_path, "title": self.title,
            "subject": self.subject, "operator": self.operator,
            "why": self.why, "measured": self.measured,
            "plan": [{"aspect": a, "concerns": c} for a, c in self.plan],
            "phased_steps": self.phased_steps, "done_when": self.done_when,
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
}


def _lens_for(node: IdeaNode) -> str:
    if node.operator in _FACETS:
        return node.operator
    label = node.source_facts[0].split(":")[0].strip() if node.source_facts else ""
    return _LABEL_LENS.get(label, "extend")


def build_brief(report: IdeaTreeReport, branch_path: str = "") -> Brief | None:
    """The brief for ``branch_path`` — or for the most valuable design-level
    idea when no branch is given. None when the tree has no such idea."""
    from app.engine.idea_action_bridge import IdeaActionBridge

    bridge = IdeaActionBridge()
    candidates: list[IdeaNode] = []
    for node in report.ideas:
        if branch_path and node.branch_path == branch_path:
            candidates = [node]
            break
        if not branch_path and not bridge.plan_idea(node).executable:
            candidates.append(node)
    if not candidates:
        return None
    node = max(candidates, key=lambda n: (n.value, n.branch_path)) if not branch_path else candidates[0]

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
    )


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
        lines.append(f"- **{aspect}**")
        lines += [f"  - [ ] {c}" for c in concerns]
    lines.append("")
    lines.append("## Definition of done — the engine verifies it")
    lines += [f"- {d}" for d in brief.done_when]
    lines.append("")
    return "\n".join(lines)
