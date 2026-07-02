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
    "develop_brief", "render_brief_develop_markdown", "_loci_from_report",
    "develop_readiness_section",
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
    # Signal convergence (opt-in narrative): modules named by >= 3 distinct
    # signal families at once, most-converged first. Each entry mirrors the
    # profile's confluence record: {"module", "family_count", "families"}.
    # Empty unless the engine surfaced a confluence, so the brief is unchanged
    # for projects with no convergence.
    confluences: list[dict] = field(default_factory=list)
    # Function-level locus (opt-in narrative, complementary to confluence): the
    # top recommendation's concrete starting point — the riskiest function(s)
    # the idea names, each shaped {"module","symbol","line","metric"}, plus the
    # idea's optional rationale string. Empty unless a top idea carried anchors,
    # so the brief is byte-identical for idea sets with no function-grain data.
    loci: list[dict] = field(default_factory=list)

    @property
    def total_moves(self) -> int:
        return sum(len(r.steps) for r in self.results)

    @property
    def verification_unavailable(self) -> str:
        """The loud "pytest is not importable" decline message a scoped campaign
        carried, or ``""`` when every campaign could be verified. A decline lands
        NOTHING (zero steps) — this exists so the renderer surfaces the honest
        "could not verify => did not touch" message instead of a false
        "0 verified move(s)" line (never-fake-green disclosure parity)."""
        for r in self.results:
            if r.verification_unavailable:
                return r.verification_unavailable
        return ""

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
            "applied": self.applied, "confluences": self.confluences,
            "loci": self.loci,
        }


def _subject_module(brief: Any) -> str:
    """The brief's subject as a bare module path (drop any ``:: symbol`` tail)."""
    return brief.subject.split(" :: ", 1)[0].split("::", 1)[0]


def _confluences_from_profile(profile: Any) -> list[dict]:
    """The profile's confluence records (signal convergence), most-converged
    first. Empty for a missing profile or one with no convergence, so the brief
    narrative stays byte-identical when nothing converges. Reads only the scan
    the engine already ran — no second pass.
    """
    convs = list(getattr(profile, "confluence_modules", None) or [])
    return [c for c in convs if c.get("module") and c.get("families")]


def _anchor_record(anchor: Any, idea_subject: str) -> dict | None:
    """One well-formed anchor as ``{"module","symbol","line","metric"}`` — or
    ``None`` when it names no concrete symbol. The module falls back to the
    idea's own subject so the locus always carries a file even when the anchor
    omits one. Read every field defensively (a parallel-agent shape)."""
    if not isinstance(anchor, dict):
        return None
    symbol = str(anchor.get("symbol") or "").strip()
    if not symbol:
        return None
    module = str(anchor.get("module") or "").strip() or idea_subject
    return {
        "module": module,
        "symbol": symbol,
        "line": anchor.get("line"),
        "metric": str(anchor.get("metric") or "").strip(),
    }


def _loci_from_report(report: Any) -> list[dict]:
    """The function-level loci of the report's TOP anchored recommendation.

    Scans the report's ideas for the highest-value one that carries function
    anchors (``IdeaNode.anchors``), read defensively via ``getattr`` so this
    works whether or not the field is populated. Returns that idea's well-formed
    anchors, each augmented with the idea's ``rationale`` so the render can weave
    it in. Empty when no idea carries an anchor — which keeps the brief
    byte-identical to today (the feature is gated on non-empty data).

    Deterministic: ideas are ranked by descending value with a stable
    ``branch_path``/``id`` tiebreak, never by time or insertion accident.
    """
    ideas = list(getattr(report, "ideas", None) or [])
    ranked = sorted(
        ideas,
        key=lambda n: (-float(getattr(n, "value", 0.0) or 0.0),
                       str(getattr(n, "branch_path", "") or ""),
                       str(getattr(n, "id", "") or "")),
    )
    for idea in ranked:
        subject = str(getattr(idea, "subject", "") or "").split("::", 1)[0].strip()
        anchors = getattr(idea, "anchors", None) or []
        rationale = str(getattr(idea, "rationale", "") or "").strip()
        records: list[dict] = []
        for a in anchors:
            rec = _anchor_record(a, subject)
            if rec is not None:
                rec["rationale"] = rationale
                records.append(rec)
        if records:
            return records
    return []


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

    # A BUYER ENTRY POINT: opt into value-aware idea generation. ``develop_brief``
    # exists to LAND concrete work for a real project, so it surfaces the highest
    # concrete-value ideas (the graded landability bonus) and the deep cost-tier
    # signals (cover-gaps/tdd/wire-exports/the value-led ``::landable-*`` family).
    # The bare ``IdeaPermutationEngine()`` default stays OFF so the ~20k scoring
    # tests are byte-identical; only this development surface opts in (mirrors how
    # ``SESSION_OBJECTIVES`` is a SEPARATE opt-in list at the develop core).
    engine = IdeaPermutationEngine(
        {"max_total_ideas": max_ideas, "max_idea_depth": depth, "breadth": breadth,
         "landability_aware": True, "landability_deep": True},
        project_root=str(project_root),
    )
    report = engine.run(objective=objective_focus or None)
    brief = build_brief(report, branch_path=branch_path, subject=subject)
    if brief is None:
        return None

    subject_module = _subject_module(brief)
    objectives = objectives_for_brief(brief)
    result = BriefDevelopResult(
        branch_path=brief.branch_path, title=brief.title, subject=subject_module,
        objectives=objectives, applied=apply,
        # Reuse the engine's own profile scan — no second pass. Empty when the
        # project has no convergence, which keeps the brief byte-identical.
        confluences=_confluences_from_profile(getattr(engine, "last_profile", None)),
        # Reuse the engine's already-run ideas — no second scan. Empty when no
        # top idea carries function anchors, keeping the brief byte-identical.
        loci=_loci_from_report(report),
    )

    # Snapshot the evidence baseline so the post-campaign re-scan has something
    # to burn down against (the brief's verified concerns, frozen pre-work).
    save_brief(brief, str(project_root))

    for obj in objectives:
        campaign = compile_objective(
            project_root, objective=obj, max_steps=max_steps, verify=verify,
            apply=apply, scope_module=subject_module)
        # Retain a VERIFICATION-UNAVAILABLE decline (fitness 0, no steps) so its loud
        # "pytest can't verify here" message is surfaced rather than dropped as a
        # silent empty campaign — the brief COULD NOT verify, which is what the buyer
        # must be told (parity with compile_all / compile_goal / _develop_auto). It
        # never makes anything land.
        if (campaign.steps or campaign.fitness_start > 0
                or campaign.verification_unavailable):
            result.results.append(campaign)

    result.check = check_brief(str(project_root), brief.branch_path)
    return result


def _confluence_lines(confluences: list[dict]) -> list[str]:
    """A short grounded note on the highest-leverage convergence target, or
    ``[]`` when nothing converges (keeping the brief byte-identical). Names the
    top module and exactly which signal families pile up on it — every claim is
    a profile fact, framed as the next move to decouple/test before changing.
    """
    if not confluences:
        return []
    top = confluences[0]
    module = top["module"]
    families = list(top.get("families") or ())
    count = top.get("family_count", len(families))
    shown = ", ".join(families)
    return ["",
            f"**Convergence:** `{module}` is named by {count} independent signal "
            f"families at once ({shown}). No single lens flags it, yet a module "
            "under several pressures is the highest-leverage next move — decouple "
            "and test it before changing it."]


def _locus_phrase(locus: dict) -> str:
    """``\\`_scan_churn\\` (app/tools/project_profile.py:550, cyclomatic 18)`` —
    the file:line and metric are each optional, dropped cleanly when absent."""
    symbol = str(locus.get("symbol") or "").strip()
    module = str(locus.get("module") or "").strip()
    line = locus.get("line")
    loc = f"{module}:{line}" if module and line else (module or (str(line) if line else ""))
    metric = str(locus.get("metric") or "").strip()
    detail = ", ".join(p for p in (loc, metric) if p)
    return f"`{symbol}` ({detail})" if detail else f"`{symbol}`"


def _locus_lines(loci: list[dict]) -> list[str]:
    """A concrete "Start here:" line naming the riskiest function(s) of the top
    recommendation, or ``[]`` when no idea carried anchors (keeping the brief
    byte-identical). Complements the module-level Convergence note above with a
    function-grain starting point; when the idea named a rationale, weave it in.
    """
    if not loci:
        return []
    phrases = ", ".join(_locus_phrase(loc) for loc in loci)
    line = f"**Start here:** {phrases}"
    rationale = next((str(loc.get("rationale") or "").strip() for loc in loci
                      if str(loc.get("rationale") or "").strip()), "")
    if rationale:
        line += f" — {rationale}"
    return ["", line]


def develop_readiness_section(project_root: str | Path,
                              weight_by_reliability: bool = False) -> str:
    """An ADDITIVE develop-readiness section for a brief — what Apex can land here.

    Opt-in companion to :func:`render_brief_develop_markdown`: a brief that wants
    to lead with honesty about its landing share calls this and appends the result
    itself. The base brief render is left byte-identical (this is never folded into
    it), so existing callers and their pinned output are unaffected.

    Best-effort and READ-ONLY: delegates to :mod:`app.engine.develop_readiness`,
    which scans without writing and never raises. Any failure yields ``""`` so the
    caller appends nothing.
    """
    try:
        from app.engine.develop_readiness import (
            develop_readiness, render_develop_readiness_markdown,
        )
        result = develop_readiness(
            root=str(project_root), weight_by_reliability=weight_by_reliability)
        return render_develop_readiness_markdown(result)
    except Exception:
        return ""


def render_brief_develop_markdown(result: BriefDevelopResult) -> str:
    """Render the brief→develop campaign: what it mapped to, did, and resolved."""
    from app.engine.idea_brief import render_check_markdown

    lines = [f"# Brief → develop — `{result.branch_path}` {result.title}", "",
             f"**Subject:** `{result.subject}`"]
    lines += _confluence_lines(result.confluences)
    lines += _locus_lines(result.loci)
    if not result.objectives:
        lines += ["",
                  "_No evidenced concern in this brief maps to a develop objective —",
                  "nothing to attempt automatically. Carry it out by hand from the",
                  "work plan above._", ""]
        return "\n".join(lines)

    lines += [f"**Maps to:** {' → '.join(f'`{o}`' for o in result.objectives)}", ""]
    if result.verification_unavailable:
        # A scoped campaign DECLINED up front: pytest is not importable, so NOTHING
        # was verified or landed. Surface ONLY the loud, actionable message (the SAME
        # wording the develop session / compile campaign use) — not the misleading
        # "0 verified move(s)" line, which would read like a clean no-op rather than
        # an honest "could not verify => did not touch".
        lines += [f"⚠️ {result.verification_unavailable}", ""]
        if result.check is not None:
            lines.append(render_check_markdown(result.check))
        return "\n".join(lines)

    verb = "Applied" if result.applied else "Would apply"
    lines += [f"{verb} **{result.total_moves} verified move(s)** across "
              f"{len(result.results)} scoped campaign(s)."]
    if result.applied and result.measured_total:
        lines.append(f"\n**Burndown: {result.resolved}/{result.measured_total} "
                     "evidenced concern(s) resolved** — the re-scan decided, not a checkbox.")
    lines.append("")
    if result.check is not None:
        lines.append(render_check_markdown(result.check))
    return "\n".join(lines)
