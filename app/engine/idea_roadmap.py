"""Turn a scored idea tree into a sequenced engineering roadmap.

The IdeaPermutationEngine answers *"what could we build?"* — it emits a scored
tree of grounded development directions. This module answers the next, more
valuable question a senior engineer would ask: **"in what order, and why?"**

It does so deterministically, with no LLM, by:

  1. Estimating each idea's **impact** (blast radius — derived from real
     structural facts: fragility, dependency hubs, sensitive paths, cycles) and
     **effort** (inverse feasibility + permutation depth), giving a bounded
     **ROI** for prioritization.
  2. Assigning each idea to one of four phases that encode hard-won engineering
     sequencing: **Stabilize → Secure → Evolve → Refine**. You build a safety
     net before you change risky code; you secure what is exposed; only then do
     you grow capability; polish comes last.
  3. Ordering ideas inside each phase by ROI, and surfacing cross-cutting
     **quick wins** (high impact, low effort) regardless of phase.

Everything is traceable back to the idea's ``source_facts`` and lens chain, so
the roadmap is a *reasoned* plan, not an opaque ranking.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.idea import IdeaNode, IdeaTreeReport

# --- Phase model --------------------------------------------------------------

# Ordered, named phases. The order is the engineering thesis of this module.
STABILIZE = "Stabilize"
SECURE = "Secure"
EVOLVE = "Evolve"
REFINE = "Refine"

PHASE_ORDER = [STABILIZE, SECURE, EVOLVE, REFINE]

PHASE_THEME: dict[str, str] = {
    STABILIZE: "Build a safety net before changing risky code",
    SECURE: "Harden the exposed surface against failure and abuse",
    EVOLVE: "Grow capability and untangle architecture once it is safe to move",
    REFINE: "Polish: documentation, observability, and simplification",
}

# Fact labels that signal high structural blast-radius (impact).
_HIGH_IMPACT_LABELS = {
    "fragile",
    "critical-untested",
    "dependency-hub",
    "sensitive-path",
    "security-finding",
    "complexity-hotspot",
    "hotspot-function",
}

# Lens / fact routing for phase assignment. Checked most-specific first.
_STABILIZE_LABELS = {"untested", "critical-untested", "partial-coverage", "shallow-coverage", "fragile", "missing-ci", "complexity-hotspot", "hotspot-function", "convergence"}
_SECURE_LABELS = {"sensitive-path", "security-finding"}
_EVOLVE_LABELS = {"dependency-hub", "symbol-hub", "entrypoint", "top-directory"}
_REFINE_OPS = {"document", "observe", "simplify"}
_EVOLVE_OPS = {"extend", "generalize", "integrate"}


@dataclass
class RoadmapItem:
    """One prioritized idea, with the reasoning that placed it."""

    branch_path: str
    title: str
    subject: str
    phase: str
    impact: float
    effort: float
    roi: float
    value: float
    kind: str
    rationale: str
    fan_in: int = 0          # measured: modules importing the subject
    loc: int = 0             # measured: subject module size
    source_facts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoadmapPhase:
    name: str
    theme: str
    items: list[RoadmapItem] = field(default_factory=list)

    @property
    def total_impact(self) -> float:
        return round(sum(i.impact for i in self.items), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "theme": self.theme,
            "total_impact": self.total_impact,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class Roadmap:
    objective: str
    project_root: str
    phases: list[RoadmapPhase] = field(default_factory=list)
    quick_wins: list[RoadmapItem] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "project_root": self.project_root,
            "phases": [p.to_dict() for p in self.phases],
            "quick_wins": [i.to_dict() for i in self.quick_wins],
            "stats": self.stats,
        }


# --- Scoring helpers (pure, deterministic) ------------------------------------

def _first_label(node: IdeaNode) -> str:
    return node.source_facts[0].split(":")[0].strip() if node.source_facts else ""


def estimate_impact(node: IdeaNode, fan_in: int = 0) -> float:
    """Blast radius, 0..1: seed from the idea's *structural* signals, then boost
    by structural risk and by *measured* fan-in (how many modules import the
    subject).

    Decoupled-from-feasibility design (chosen: option (a) from the audit).
    ``node.value`` is deliberately *not* used as the seed: it already folds in a
    feasibility term (``0.3``/``0.4 * feasibility`` in IdeaPermutationEngine
    ``_score``). Effort already carries the ``(1 - feasibility)`` axis, so seeding
    impact from ``node.value`` would let feasibility raise impact AND lower effort
    at once — counting the same property twice with the same sign in ROI (this is
    why low-effort ideas dominated quick-win lists unjustifiably). Here we seed
    impact only from the feasibility-free structural axes that ``_score`` blends
    into value: ``relevance`` (objective alignment) and ``novelty``. An equal
    blend keeps the seed bounded in [0, 1] and independent of which weight set
    (objective / no-objective) produced ``value``.

    Ideas touching fragile/critical/hub/sensitive code, breaking real import
    cycles, or sitting under a heavily-imported module move more of the system
    when done — so they score higher. ``fan_in`` is the real in-degree from the
    dependency graph; each importer adds a little, capped so it can't dominate.
    """
    label = _first_label(node)
    # Structural seed only — no feasibility term (that lives in estimate_effort).
    impact = 0.5 * node.relevance + 0.5 * node.novelty
    if label in _HIGH_IMPACT_LABELS:
        impact += 0.25
    if any("dependency-cycle" in f for f in node.source_facts):
        impact += 0.20
    if node.kind in ("synthesis", "pair"):
        impact += 0.10
    # Convergence: impact scales with the number of independent analyses that
    # agree — that *is* leverage. This reaches the ceiling for a 3+-signal
    # agreement, so the convergence idea lands in the top-impact tier instead of
    # being dragged down by the novelty penalty of sitting on a much-mined hot
    # subject (novelty measures exploration, not impact).
    conv = next((f for f in node.source_facts if f.startswith("convergence:")), "")
    if conv:
        n_signals = len([p for p in conv.split(":", 1)[1].split("+") if p.strip()])
        impact += 0.15 * n_signals
    if fan_in > 0:
        impact += min(0.3, 0.06 * fan_in)
    return round(min(1.0, impact), 4)


def estimate_effort(node: IdeaNode, loc: int = 0, complexity: int = 0) -> float:
    """Relative effort, 0.1..1.0: cheaper (high-feasibility) and shallower ideas
    cost less; larger and more branch-heavy subjects cost more.

    ``loc`` and ``complexity`` are measured from the subject module (see
    :class:`~app.tools.code_metrics.CodeMetrics`). Both contributions are capped
    so a single huge file can't peg every idea at max effort. Floored at 0.1 so
    ROI stays bounded.
    """
    effort = (1.0 - node.feasibility) + 0.1 * node.depth
    if loc > 0:
        effort += min(0.3, loc / 600.0 * 0.3)        # ~600+ LOC → full size bump
    if complexity > 0:
        effort += min(0.15, complexity / 60.0 * 0.15)  # branch-heavy → extra cost
    return round(max(0.1, min(1.0, effort)), 4)


def classify_phase(node: IdeaNode) -> str:
    """Route an idea into the earliest phase its intent belongs to.

    Permutation nodes are classified by their most-recent lens (``operator``)
    with the root fact label as a tie-breaker; synthesis/pair ideas route by
    their architectural nature.
    """
    label = _first_label(node)
    op = node.operator

    # Synthesis = a dedicated security test suite -> Secure. Pair = interface /
    # cycle work -> Evolve (architecture).
    if node.kind == "synthesis":
        return SECURE
    if node.kind == "pair":
        return EVOLVE

    # Permutation / root nodes: lens first (most specific action), then label.
    if op == "test" or label in _STABILIZE_LABELS:
        # A 'harden' lens on an untested module still needs the safety net first,
        # but an explicit harden on a sensitive path is a Secure action.
        if op == "harden" and label in _SECURE_LABELS:
            return SECURE
        if op in _REFINE_OPS:
            return REFINE
        if op in _EVOLVE_OPS:
            return EVOLVE
        return STABILIZE
    if op == "harden" or label in _SECURE_LABELS:
        return SECURE
    if op in _EVOLVE_OPS or label in _EVOLVE_LABELS:
        return EVOLVE
    if op in _REFINE_OPS:
        return REFINE
    # Roots with no decisive lens default to Evolve (a capability direction).
    return EVOLVE


# --- Synthesizer --------------------------------------------------------------

class RoadmapSynthesizer:
    """Compose a scored idea tree into a sequenced, reasoned roadmap."""

    def __init__(self, quick_win_count: int = 3, quick_win_min_roi: float = 1.5) -> None:
        self.quick_win_count = quick_win_count
        self.quick_win_min_roi = quick_win_min_roi

    def build(self, report: IdeaTreeReport) -> Roadmap:
        # Measured structural signals from the engine: fan-in (blast radius) and
        # per-module size/complexity (effort). Both ground the ROI in real code.
        stats = report.stats or {}
        fan_in = stats.get("fan_in", {})
        metrics = stats.get("metrics", {})
        items: list[RoadmapItem] = []
        for node in report.ideas:
            base_subject = node.subject.split(" :: ", 1)[0]
            subj_fan_in = fan_in.get(base_subject, 0)
            mm = metrics.get(base_subject, {})
            loc = int(mm.get("loc", 0))
            complexity = int(mm.get("complexity", 0))
            impact = estimate_impact(node, fan_in=subj_fan_in)
            effort = estimate_effort(node, loc=loc, complexity=complexity)
            roi = round(impact / effort, 4)
            items.append(
                RoadmapItem(
                    branch_path=node.branch_path,
                    title=node.title,
                    subject=node.subject,
                    phase=classify_phase(node),
                    impact=impact,
                    effort=effort,
                    roi=roi,
                    value=node.value,
                    kind=node.kind,
                    rationale=node.rationale,
                    fan_in=subj_fan_in,
                    loc=loc,
                    source_facts=list(node.source_facts),
                )
            )

        # Group into ordered phases; sort each by ROI then raw value, both desc.
        phases: list[RoadmapPhase] = []
        for name in PHASE_ORDER:
            phase_items = sorted(
                (i for i in items if i.phase == name),
                key=lambda i: (i.roi, i.value),
                reverse=True,
            )
            if phase_items:
                phases.append(RoadmapPhase(name=name, theme=PHASE_THEME[name], items=phase_items))

        # Quick wins: best ROI across the whole tree, above a floor. A tie on ROI
        # breaks toward higher impact so "big & cheap" beats "small & cheap".
        quick_wins = sorted(
            (i for i in items if i.roi >= self.quick_win_min_roi),
            key=lambda i: (i.roi, i.impact),
            reverse=True,
        )[: self.quick_win_count]

        stats = {
            "total_items": len(items),
            "phase_counts": {p.name: len(p.items) for p in phases},
            "mean_roi": round(sum(i.roi for i in items) / len(items), 4) if items else 0.0,
            "quick_win_count": len(quick_wins),
        }
        return Roadmap(
            objective=report.objective,
            project_root=report.project_root,
            phases=phases,
            quick_wins=quick_wins,
            stats=stats,
        )


def render_roadmap_markdown(roadmap: Roadmap) -> str:
    """Render the roadmap as a readable, phase-ordered markdown document."""
    lines = [f"# Engineering Roadmap for `{roadmap.project_root}`", ""]
    meta = (
        f"{roadmap.stats.get('total_items', 0)} ideas sequenced · "
        f"mean ROI {roadmap.stats.get('mean_roi', 0)}"
    )
    if roadmap.objective:
        meta = f"objective: _{roadmap.objective}_ · " + meta
    lines += [meta, ""]

    if roadmap.quick_wins:
        lines.append("## ⚡ Quick wins (high impact, low effort)")
        for i in roadmap.quick_wins:
            lines.append(
                f"- `{i.branch_path}` **{i.title}** "
                f"(ROI {i.roi} · impact {i.impact} · effort {i.effort})"
            )
        lines.append("")

    for n, phase in enumerate(roadmap.phases, start=1):
        lines.append(f"## Phase {n}: {phase.name} — {phase.theme}")
        lines.append(f"_{len(phase.items)} ideas · total impact {phase.total_impact}_")
        lines.append("")
        for i in phase.items:
            measured = []
            if i.fan_in:
                measured.append(f"imported by {i.fan_in}")
            if i.loc:
                measured.append(f"{i.loc} LOC")
            measured_str = f" · {' · '.join(measured)}" if measured else ""
            lines.append(
                f"- `{i.branch_path}` {i.title}  "
                f"(ROI {i.roi} · impact {i.impact} · effort {i.effort}{measured_str})"
            )
        lines.append("")
    return "\n".join(lines)
