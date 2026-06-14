"""Explain *why* an idea scored what it did — the engine's reasoning, made legible.

The Idea Permutation Engine is deterministic, so every number it produces has a
derivable cause. This module reconstructs that derivation for a single idea: the
concrete code fact it sprang from, the lens chain that shaped it, the exact value
formula (with the weights actually used), the roadmap impact/effort/ROI grounded
in measured fan-in and LOC, the counterfactual caveats, and what acting on it
would concretely mean. It turns a score into an auditable argument.

Pure and deterministic — it reads a report (and derives the roadmap), no I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.idea import IdeaNode, IdeaTreeReport


@dataclass
class IdeaExplanation:
    branch_path: str
    title: str
    subject: str
    kind: str
    operator: str
    operator_chain: list[str]
    depth: int
    source_facts: list[str]
    relevance: float
    novelty: float
    feasibility: float
    value: float
    value_formula: str
    phase: str
    impact: float
    effort: float
    roi: float
    fan_in: int
    loc: int
    caveats: list[str]
    executable: bool
    action_type: str
    action_description: str
    novelty_explanation: str = ""
    feasibility_explanation: str = ""
    impact_explanation: str = ""
    effort_explanation: str = ""
    rationale: str = ""
    anchors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _find(report: IdeaTreeReport, branch_path: str) -> IdeaNode | None:
    return next((i for i in report.ideas if i.branch_path == branch_path), None)


def explain_idea(report: IdeaTreeReport, branch_path: str) -> IdeaExplanation | None:
    """Reconstruct the full reasoning behind one idea, by its branch path."""
    node = _find(report, branch_path)
    if node is None:
        return None

    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_roadmap import RoadmapSynthesizer

    roadmap = RoadmapSynthesizer().build(report)
    item = next(
        (i for ph in roadmap.phases for i in ph.items if i.branch_path == branch_path), None
    )
    step = IdeaActionBridge().plan_idea(node)

    has_objective = bool((report.objective or "").strip())
    if has_objective:
        formula = (
            f"value = 0.4·relevance + 0.3·novelty + 0.3·feasibility "
            f"= 0.4·{node.relevance} + 0.3·{node.novelty} + 0.3·{node.feasibility} = {node.value}"
        )
    else:
        formula = (
            f"value = 0.2·relevance + 0.4·novelty + 0.4·feasibility "
            f"(no objective → weight shifts to the signals that vary) "
            f"= 0.2·{node.relevance} + 0.4·{node.novelty} + 0.4·{node.feasibility} = {node.value}"
        )
    # The bounded bonuses are part of the score's story — name them when present.
    from app.engine.idea_permutation import _magnitude_bonus

    magnitude = _magnitude_bonus(node) if node.operator == "root" else 0.0
    if magnitude:
        formula += (f" (includes +{magnitude} magnitude bonus: the measured quantity "
                    f"in the seeding fact — months exposed / commits / complexity)")

    # Reconstruct the deterministic derivations the engine used.
    if node.operator == "root":
        novelty_exp = "roots are maximally novel by definition (novelty = 1.0)"
    else:
        novelty_exp = (
            f"novelty = 1.0 − 0.15·depth − 0.10·(repeats of this lens chain) − "
            f"0.04·(ideas on this subject), floored at 0.2 → {node.novelty} "
            f"(depth {node.depth})"
        )
    feasibility_exp = (
        f"feasibility {node.feasibility}: cheaper lenses score higher, decayed by depth "
        f"(×0.9^{node.depth}) and re-weighted for security-relevant subjects"
    )

    impact = item.impact if item else 0.0
    effort = item.effort if item else 0.0
    roi = item.roi if item else 0.0
    fan_in = item.fan_in if item else 0
    loc = item.loc if item else 0
    phase = item.phase if item else ""
    impact_exp = (
        f"impact {impact}: idea value plus structural-risk boosts and measured fan-in "
        f"(imported by {fan_in} module(s) → blast radius)"
    )
    effort_exp = (
        f"effort {effort}: inverse feasibility + depth, raised by measured size "
        f"({loc} LOC) and branch complexity of `{node.subject.split(' :: ')[0]}`"
    )

    return IdeaExplanation(
        branch_path=node.branch_path,
        title=node.title,
        subject=node.subject,
        kind=node.kind,
        operator=node.operator,
        operator_chain=list(node.operator_chain),
        depth=node.depth,
        source_facts=list(node.source_facts),
        relevance=node.relevance,
        novelty=node.novelty,
        feasibility=node.feasibility,
        value=node.value,
        value_formula=formula,
        phase=phase,
        impact=impact,
        effort=effort,
        roi=roi,
        fan_in=fan_in,
        loc=loc,
        caveats=list(node.caveats),
        executable=step.executable,
        action_type=step.action_type,
        action_description=step.description,
        novelty_explanation=novelty_exp,
        feasibility_explanation=feasibility_exp,
        impact_explanation=impact_exp,
        effort_explanation=effort_exp,
        rationale=(getattr(node, "rationale", "") or "").strip(),
        anchors=_normalize_anchors(getattr(node, "anchors", []) or []),
    )


def _normalize_anchors(raw: Any) -> list[dict[str, Any]]:
    """Coerce an idea's ``anchors`` into a stable list of clean dicts.

    Anchors are ``[{"module","symbol","line","metric"}]``. We read defensively
    (the field may not exist yet) and keep only entries that name *something*
    concrete, preserving the producer's order for determinism.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        module = str(entry.get("module", "") or "").strip()
        symbol = str(entry.get("symbol", "") or "").strip()
        line = entry.get("line")
        metric = str(entry.get("metric", "") or "").strip()
        if not (module or symbol or metric):
            continue
        out.append({"module": module, "symbol": symbol, "line": line, "metric": metric})
    return out


def _render_anchor(anchor: dict[str, Any]) -> str:
    """Render one anchor as ``symbol (module:line, metric)`` — omitting blanks."""
    symbol = anchor.get("symbol") or ""
    module = anchor.get("module") or ""
    line = anchor.get("line")
    metric = anchor.get("metric") or ""

    locus_bits: list[str] = []
    if module:
        loc = module
        if line is not None and str(line).strip() != "":
            loc = f"{module}:{line}"
        locus_bits.append(loc)
    elif line is not None and str(line).strip() != "":
        locus_bits.append(f"line {line}")
    if metric:
        locus_bits.append(metric)

    head = f"`{symbol}`" if symbol else ""
    paren = f"({', '.join(locus_bits)})" if locus_bits else ""
    if head and paren:
        return f"{head} {paren}"
    return head or paren


def render_explanation_markdown(exp: IdeaExplanation) -> str:
    """Render an idea's reasoning as a legible 'show your work' card."""
    lines = [f"# Why `{exp.branch_path}` — {exp.title}", ""]
    lines.append(f"**Subject:** `{exp.subject}`  ·  **kind:** {exp.kind}  ·  **depth:** {exp.depth}")
    if exp.operator_chain:
        lines.append(f"**Lens chain:** {' → '.join(exp.operator_chain)}")
    lines.append("")

    lines.append("## Provenance (what grounds this idea)")
    for fact in exp.source_facts:
        lines.append(f"- {fact}")
    lines.append("")

    # Concrete locus — only emitted when we actually have one, so an idea with
    # neither anchors nor a rationale renders byte-identically to the legacy card.
    anchors = exp.anchors or []
    rationale = (exp.rationale or "").strip()
    if anchors or rationale:
        lines.append("## Where (the concrete locus)")
        rendered = [_render_anchor(a) for a in anchors]
        rendered = [r for r in rendered if r]
        if rendered:
            lines.append(f"- **Focus:** {rendered[0]}")
            for extra in rendered[1:]:
                lines.append(f"- also: {extra}")
        if rationale:
            lines.append(f"- {rationale}")
        lines.append("")

    lines.append("## Score breakdown")
    lines.append(f"- **Relevance:** {exp.relevance}")
    lines.append(f"- **Novelty:** {exp.novelty} — {exp.novelty_explanation}")
    lines.append(f"- **Feasibility:** {exp.feasibility} — {exp.feasibility_explanation}")
    lines.append(f"- **Value:** `{exp.value_formula}`")
    lines.append("")

    lines.append("## Roadmap placement")
    lines.append(f"- **Phase:** {exp.phase or '—'}")
    lines.append(f"- **Impact:** {exp.impact} — {exp.impact_explanation}")
    lines.append(f"- **Effort:** {exp.effort} — {exp.effort_explanation}")
    lines.append(f"- **ROI:** {exp.roi}  (impact ÷ effort)")
    lines.append("")

    lines.append("## Acting on it")
    kind = "executable by Apex" if exp.executable else "a design task for a human"
    lines.append(f"- **{exp.action_type}** ({kind}) — {exp.action_description}")
    lines.append("")

    if exp.caveats:
        lines.append("## Caveats (counterfactual stress-tests)")
        for c in exp.caveats:
            lines.append(f"- ⚠ {c}")
        lines.append("")
    return "\n".join(lines)
