"""Brief → develop — turn a work brief's evidence into a verified campaign.

A brief (``idea_brief.build_brief``) names a subject module and a checklist of
concern phrases; each evidenced phrase is bound to a real line in the subject's
ACTUAL code — the burndown baseline. Until now a brief stopped there: a work
order a human had to carry out. This module closes the last loop.

It bridges the brief's evidenced concern phrases through ``facet_develop`` into
develop OBJECTIVES, runs each objective as its own suite-gated campaign SCOPED
to the subject module, then re-checks the brief so the burndown PROVES which
evidenced items the campaign actually resolved — measured by a re-scan, not
self-reported.

  the brief says WHAT to do · develop DOES it · the burndown PROVES it.

Deterministic, stdlib-only: it invents nothing, it only acts on phrases the
brief already evidenced and objectives the compiler already owns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.facet_develop import facets_to_objectives
from app.engine.objective_compiler import CompileResult, compile_objective

__all__ = [
    "BriefDevelopResult", "concern_phrases", "objectives_for_brief",
    "develop_brief", "render_brief_develop_markdown",
]


@dataclass
class BriefDevelopResult:
    branch_path: str
    title: str
    subject: str
    objectives: list[str]                       # the develop objectives, in order
    results: list[CompileResult] = field(default_factory=list)
    check: dict | None = None                   # the burndown re-measure (or None)
    applied: bool = False

    @property
    def total_moves(self) -> int:
        return sum(len(r.steps) for r in self.results)

    @property
    def resolved(self) -> int:
        return len(self.check["resolved"]) if self.check else 0

    @property
    def measured_total(self) -> int:
        return self.check["measured_total"] if self.check else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_path": self.branch_path, "title": self.title,
            "subject": self.subject, "objectives": self.objectives,
            "results": [r.to_dict() for r in self.results],
            "total_moves": self.total_moves, "check": self.check,
            "resolved": self.resolved, "measured_total": self.measured_total,
            "applied": self.applied,
        }


def _subject_module(brief: Any) -> str:
    """The brief's subject as a bare module path (drop any ``:: symbol`` tail)."""
    return brief.subject.split(" :: ", 1)[0].split("::", 1)[0]


def concern_phrases(brief: Any) -> list[str]:
    """The concern phrases a develop campaign should act on, most-grounded first.

    Prefer the EVIDENCED phrases — the ones the brief bound to a real line in
    the subject's code (verified concerns, not hypotheses). Only when a brief
    evidenced nothing do we fall back to its full plan vocabulary, so there is
    still something concrete to attempt. Order is preserved and de-duplicated.
    """
    evidenced = list(brief.evidence.keys())
    if evidenced:
        return evidenced
    phrases: list[str] = []
    for aspect, concerns in brief.plan:
        for phrase in (aspect, *concerns):
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases


def objectives_for_brief(brief: Any) -> list[str]:
    """The develop objectives the brief's concerns map to (deduped, in order)."""
    return facets_to_objectives(concern_phrases(brief))


def develop_brief(project_root: str | Path, branch_path: str = "",
                  subject: str = "", max_steps: int = 25, verify: bool = True,
                  apply: bool = True, depth: int = 2, breadth: int = 4,
                  max_ideas: int = 40, objective_focus: str = "") -> BriefDevelopResult | None:
    """Build the brief, run each mapped objective scoped to its subject, then
    re-measure the burndown. ``None`` when no design-level idea yields a brief.

    With ``apply=False`` this is a dry run: campaigns plan but write nothing, so
    the burndown shows the baseline unchanged — a preview of the work order.
    """
    from app.engine.idea_brief import build_brief, check_brief, save_brief
    from app.engine.idea_permutation import IdeaPermutationEngine

    report = IdeaPermutationEngine(
        {"max_total_ideas": max_ideas, "max_idea_depth": depth, "breadth": breadth},
        project_root=str(project_root),
    ).run(objective=objective_focus or None)
    brief = build_brief(report, branch_path=branch_path, subject=subject)
    if brief is None:
        return None

    subject_module = _subject_module(brief)
    objectives = objectives_for_brief(brief)
    result = BriefDevelopResult(
        branch_path=brief.branch_path, title=brief.title, subject=subject_module,
        objectives=objectives, applied=apply,
    )

    # Snapshot the evidence baseline so the post-campaign re-scan has something
    # to burn down against (the brief's verified concerns, frozen pre-work).
    save_brief(brief, str(project_root))

    for obj in objectives:
        campaign = compile_objective(
            project_root, objective=obj, max_steps=max_steps, verify=verify,
            apply=apply, scope_module=subject_module)
        if campaign.steps or campaign.fitness_start > 0:
            result.results.append(campaign)

    result.check = check_brief(str(project_root), brief.branch_path)
    return result


def render_brief_develop_markdown(result: BriefDevelopResult) -> str:
    """Render the brief→develop campaign: what it mapped to, did, and resolved."""
    from app.engine.idea_brief import render_check_markdown

    lines = [f"# Brief → develop — `{result.branch_path}` {result.title}", "",
             f"**Subject:** `{result.subject}`"]
    if not result.objectives:
        lines += ["",
                  "_No evidenced concern in this brief maps to a develop objective —",
                  "nothing to attempt automatically. Carry it out by hand from the",
                  "work plan above._", ""]
        return "\n".join(lines)

    verb = "Applied" if result.applied else "Would apply"
    lines += [f"**Maps to:** {' → '.join(f'`{o}`' for o in result.objectives)}", "",
              f"{verb} **{result.total_moves} verified move(s)** across "
              f"{len(result.results)} scoped campaign(s)."]
    if result.applied and result.measured_total:
        lines.append(f"\n**Burndown: {result.resolved}/{result.measured_total} "
                     "evidenced concern(s) resolved** — the re-scan decided, not a checkbox.")
    lines.append("")
    if result.check is not None:
        lines.append(render_check_markdown(result.check))
    return "\n".join(lines)
