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

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.idea import IdeaNode, IdeaTreeReport

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.engine.idea_memory import IdeaMemory

# --- Historical-outcome (learned) re-ranking ---------------------------------

# How far a perfect/abysmal track record may nudge an idea's ROI for ranking.
# Deliberately tiny: this re-ranks ties and nudges neighbours; it never
# overrides the grounded impact/effort signal. Additive in ROI space.
_OUTCOME_MAX_ADJUST = 0.05
# Don't let a single fluke swing ranking: a key needs at least this many
# recorded outcomes before its landing rate influences the roadmap at all.
_OUTCOME_MIN_SAMPLES = 3

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
    "correctness-bug",
    "complexity-hotspot",
    "hotspot-function",
    "impure-untested",
    "hub-untested",
    "confluence",
}

# Lens / fact routing for phase assignment. Checked most-specific first.
_STABILIZE_LABELS = {"untested", "critical-untested", "partial-coverage", "shallow-coverage", "fragile", "missing-ci", "complexity-hotspot", "hotspot-function", "impure-untested", "hub-untested", "convergence", "confluence", "cochange-testgap", "knowledge-risk"}
_SECURE_LABELS = {"sensitive-path", "security-finding", "correctness-bug"}
_EVOLVE_LABELS = {"dependency-hub", "symbol-hub", "entrypoint", "top-directory", "churn-hotspot", "dream-insight", "polyglot-hotspot", "incomplete-protocol", "generalizable-duplication", "coordinator", "god-class"}
_REFINE_OPS = {"document", "observe", "simplify"}
_REFINE_LABELS = {"doc-drift", "dead-parameter", "extractable-block", "inlinable-helper", "deep-nesting"}
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
    """Blast radius, 0..1 — built from *structural* signals only.

    Impact answers "how much of the system moves when this is done" and is
    deliberately independent of every value axis:

    - not ``feasibility`` (that is the effort axis; using it here would count
      the same property twice in ROI — the audit's double-count finding);
    - not ``relevance``/``novelty`` (alignment with an objective and how
      explored a branch is say nothing about blast radius — and since roots
      score 1.0 on both, seeding from them pinned nearly every idea at the
      1.0 ceiling, flattening a 1700-LOC 17-importer hub and an 11-LOC leaf
      into the same "impact").

    Instead, impact starts from a low base and is earned by structure: the
    risk class of the seeding fact, real measured fan-in, breadth (themes),
    agreement (convergence), and cycle membership.
    """
    label = _first_label(node)
    # Low base; everything above it must be earned by a structural signal.
    impact = 0.35
    if label in _HIGH_IMPACT_LABELS:
        impact += 0.25
    if any("dependency-cycle" in f for f in node.source_facts):
        impact += 0.20
    if node.kind in ("synthesis", "pair"):
        impact += 0.10
    # Convergence: impact scales with the number of independent analyses that
    # agree — that *is* leverage, so a 3+-signal agreement reaches the top tier.
    conv = next((f for f in node.source_facts if f.startswith("convergence:")), "")
    if conv:
        n_signals = len([p for p in conv.split(":", 1)[1].split("+") if p.strip()])
        impact += 0.15 * n_signals
    # Theme: a systemic initiative's blast radius is the number of modules it
    # spans — the more it touches, the more of the system it moves.
    theme = next((f for f in node.source_facts if f.startswith("theme:")), "")
    if theme:
        m = re.search(r"\((\d+) modules\)", theme)
        if m:
            impact += min(0.4, 0.06 * int(m.group(1)))
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


# Lens -> phase for a *theme* synthesis (coverage -> Stabilize, security ->
# Secure, cleanup -> Refine); anything else falls through to Evolve.
_THEME_LENS_PHASE: dict[str, str] = {"test": STABILIZE, "harden": SECURE}


def _classify_theme_synthesis(node: IdeaNode) -> str:
    """A theme synthesis routes by its most-recent lens; default Evolve."""
    lens = node.operator_chain[-1] if node.operator_chain else ""
    if lens in _THEME_LENS_PHASE:
        return _THEME_LENS_PHASE[lens]
    if lens in _REFINE_OPS:
        return REFINE
    return EVOLVE


def _classify_synthesis(node: IdeaNode) -> str:
    """Route a synthesis idea by its nature.

    Convergence starts with the safety net (test-first) -> Stabilize; a theme
    routes by its lens; everything else is a cross-lens security suite -> Secure.
    """
    if any(f.startswith("convergence:") for f in node.source_facts):
        return STABILIZE
    if any(f.startswith("theme:") for f in node.source_facts):
        return _classify_theme_synthesis(node)
    return SECURE


def _classify_stabilize_action(op: str) -> str:
    """A stabilize-routed node still honours an explicit refine/evolve lens.

    A 'harden' lens on an untested/stabilize-labelled module still needs the
    safety net (test) first, so it stays Stabilize. An explicit harden on a
    sensitive path is classified Secure earlier — the secure and stabilize
    label sets are disjoint, so it never reaches here.
    """
    if op in _REFINE_OPS:
        return REFINE
    if op in _EVOLVE_OPS:
        return EVOLVE
    return STABILIZE


# Ordered phase rules for a permutation/root node, checked most-specific first.
# Each rule is ``(triggering ops, triggering labels, phase)``; the first whose
# op OR label matches wins. Stabilize is special-cased (see _classify_permutation)
# because an explicit refine/evolve lens overrides it.
_PERMUTATION_RULES: tuple[tuple[frozenset[str], frozenset[str], str], ...] = (
    (frozenset({"harden"}), frozenset(_SECURE_LABELS), SECURE),
    (frozenset(_EVOLVE_OPS), frozenset(_EVOLVE_LABELS), EVOLVE),
    (frozenset(_REFINE_OPS), frozenset(_REFINE_LABELS), REFINE),
)


def _classify_permutation(node: IdeaNode) -> str:
    """Classify a permutation/root node: lens first (most specific), then label."""
    label = _first_label(node)
    op = node.operator
    if op == "test" or label in _STABILIZE_LABELS:
        return _classify_stabilize_action(op)
    for ops, labels, phase in _PERMUTATION_RULES:
        if op in ops or label in labels:
            return phase
    # Roots with no decisive lens default to Evolve (a capability direction).
    return EVOLVE


def classify_phase(node: IdeaNode) -> str:
    """Route an idea into the earliest phase its intent belongs to.

    Permutation nodes are classified by their most-recent lens (``operator``)
    with the root fact label as a tie-breaker; synthesis/pair ideas route by
    their architectural nature.
    """
    if node.kind == "synthesis":
        return _classify_synthesis(node)
    if node.kind == "pair":
        # Pair = interface / cycle work -> Evolve (architecture).
        return EVOLVE
    return _classify_permutation(node)


# --- Learned re-ranking (historical landing rate) -----------------------------

def _outcome_rates(memory: IdeaMemory | None) -> dict[str, dict[str, float]]:
    """Best-effort ``key -> {success_rate, samples}`` from a memory ledger.

    Reads :meth:`IdeaMemory.summary`'s ``most_reliable`` / ``least_reliable``
    operator tracks (the only per-key landing-rate views the memory exposes).
    Wrapped defensively: a missing or malformed ledger must never break roadmap
    generation, so any failure collapses to an empty (no-opinion) map. Empty
    memory yields ``{}`` — and an empty map produces a byte-identical roadmap.
    """
    if memory is None:
        return {}
    rates: dict[str, dict[str, float]] = {}
    try:
        summary = memory.summary()
        for bucket in ("most_reliable", "least_reliable"):
            for entry in summary.get(bucket, []) or []:
                key = entry.get("key")
                if not key:
                    continue
                rates[key] = {
                    "success_rate": float(entry.get("success_rate", 0.0)),
                    "samples": int(entry.get("samples", 0)),
                }
    except Exception:  # pragma: no cover - defensive; corrupt/foreign ledger
        return {}
    return rates


def _outcome_adjustment(node: IdeaNode, rates: dict[str, dict[str, float]]) -> float:
    """Bounded, additive ROI nudge in ``[-_OUTCOME_MAX_ADJUST, +_OUTCOME_MAX_ADJUST]``.

    Looks up the idea's *dominant* key — its development ``operator`` (or, for a
    root, its seeding fact label) — in the historical-outcome map. A landing
    rate above 0.5 yields a small boost; below 0.5 a small penalty; exactly 0.5
    is neutral. Keys with fewer than ``_OUTCOME_MIN_SAMPLES`` recorded outcomes
    are ignored entirely (returns 0.0), so one fluke can't move the ranking.

    Returns 0.0 — a true no-op — when ``rates`` is empty (no memory).
    """
    if not rates:
        return 0.0
    op = node.operator
    key = op if (op and op != "root") else _first_label(node)
    entry = rates.get(key)
    if entry is None or entry.get("samples", 0) < _OUTCOME_MIN_SAMPLES:
        return 0.0
    # success_rate 0.5 -> 0.0; 1.0 -> +MAX; 0.0 -> -MAX.
    return round((entry["success_rate"] - 0.5) * 2.0 * _OUTCOME_MAX_ADJUST, 4)


# --- Synthesizer --------------------------------------------------------------

class RoadmapSynthesizer:
    """Compose a scored idea tree into a sequenced, reasoned roadmap."""

    def __init__(self, quick_win_count: int = 3, quick_win_min_roi: float = 1.5) -> None:
        self.quick_win_count = quick_win_count
        self.quick_win_min_roi = quick_win_min_roi

    def build(self, report: IdeaTreeReport, memory: IdeaMemory | None = None) -> Roadmap:
        # Measured structural signals from the engine: fan-in (blast radius) and
        # per-module size/complexity (effort). Both ground the ROI in real code.
        stats = report.stats or {}
        fan_in = stats.get("fan_in", {})
        metrics = stats.get("metrics", {})
        # Learned landing-rate map (empty -> no-op, byte-identical roadmap).
        rates = _outcome_rates(memory)
        items: list[RoadmapItem] = []
        # Ranking ROI per item: grounded ROI plus a tiny, bounded learned nudge.
        # The reported ``item.roi`` stays exactly impact/effort; only the *sort*
        # sees the adjustment, so a fresh repo's roadmap is unchanged.
        ranked_roi: dict[int, float] = {}
        for node in report.ideas:
            base_subject = node.subject.split(" :: ", 1)[0]
            subj_fan_in = fan_in.get(base_subject, 0)
            mm = metrics.get(base_subject, {})
            loc = int(mm.get("loc", 0))
            complexity = int(mm.get("complexity", 0))
            impact = estimate_impact(node, fan_in=subj_fan_in)
            effort = estimate_effort(node, loc=loc, complexity=complexity)
            roi = round(impact / effort, 4)
            item = RoadmapItem(
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
            items.append(item)
            # Keep the ranking ROI clamped to [0, 1]-ish ROI space sanely: ROI is
            # impact/effort (impact<=1, effort>=0.1 -> roi<=10), and the nudge is
            # additive and tiny, so the ranking key stays well-defined and the
            # grounded signal continues to dominate.
            ranked_roi[id(item)] = round(roi + _outcome_adjustment(node, rates), 4)

        # Group into ordered phases; sort each by ranking-ROI then raw value, desc.
        phases: list[RoadmapPhase] = []
        for name in PHASE_ORDER:
            phase_items = sorted(
                (i for i in items if i.phase == name),
                key=lambda i: (ranked_roi[id(i)], i.value),
                reverse=True,
            )
            if phase_items:
                phases.append(RoadmapPhase(name=name, theme=PHASE_THEME[name], items=phase_items))

        # Quick wins: best ROI across the whole tree, above a floor (measured on
        # the grounded ROI). A tie on ranking-ROI breaks toward higher impact so
        # "big & cheap" beats "small & cheap".
        quick_wins = sorted(
            (i for i in items if i.roi >= self.quick_win_min_roi),
            key=lambda i: (ranked_roi[id(i)], i.impact),
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


def best_first_move(roadmap: Roadmap) -> RoadmapItem | None:
    """The single highest value-per-effort item — "if you do ONE thing, do this."

    This is the roadmap-local analogue of the pareto frontier's *knee point*: the
    item that buys the most value per unit of effort, biased toward acting early
    (an earlier phase breaks ties, since you cannot safely skip the safety net).
    It is computed only from the roadmap's own *phased* nodes — no import of
    ``idea_pareto`` — so there is no coupling and no circular-import risk.

    Ratio is ``value / effort`` (effort is floored at 0.1 by ``estimate_effort``,
    so the denominator is always safe). Ties break deterministically and
    identically to the pareto knee where they overlap: earlier phase, then higher
    value, then lower effort, then higher ROI, then lexicographic branch path.

    Returns ``None`` for an empty roadmap (no phases / no items), so an empty
    roadmap renders byte-for-byte as it did before this callout existed.
    """
    candidates = [i for phase in roadmap.phases for i in phase.items]
    if not candidates:
        return None
    phase_rank = {name: n for n, name in enumerate(PHASE_ORDER)}
    return min(
        candidates,
        key=lambda i: (
            -round(i.value / max(i.effort, 0.1), 6),
            phase_rank.get(i.phase, len(PHASE_ORDER)),
            -i.value,
            i.effort,
            -i.roi,
            i.branch_path,
        ),
    )


def _render_header(roadmap: Roadmap) -> list[str]:
    """Title + meta block (objective, idea count, mean ROI)."""
    meta = (
        f"{roadmap.stats.get('total_items', 0)} ideas sequenced · "
        f"mean ROI {roadmap.stats.get('mean_roi', 0)}"
    )
    if roadmap.objective:
        meta = f"objective: _{roadmap.objective}_ · " + meta
    return [f"# Engineering Roadmap for `{roadmap.project_root}`", "", meta, ""]


def _render_best_first_move(roadmap: Roadmap) -> list[str]:
    """Best-first-move block, or empty when the roadmap has no pick.

    The single highest value-per-effort pick, surfaced up top so a reader knows
    where to start. Gated on a real pick so an empty roadmap (no phases) renders
    exactly as before. Wording avoids literal magnitude tokens so the byte-stable
    / negative render tests stay green.
    """
    best = best_first_move(roadmap)
    if best is None:
        return []
    return [
        "## 🎯 Best first move",
        (
            f"- `{best.branch_path}` **{best.title}** in {best.phase} "
            f"(ROI {best.roi} · impact {best.impact} · effort {best.effort}) — "
            f"the strongest value-per-effort pick to start with."
        ),
        "",
    ]


def _render_quick_wins(roadmap: Roadmap) -> list[str]:
    """Quick-wins block, or empty when there are none."""
    if not roadmap.quick_wins:
        return []
    lines = ["## ⚡ Quick wins (high impact, low effort)"]
    for i in roadmap.quick_wins:
        lines.append(
            f"- `{i.branch_path}` **{i.title}** "
            f"(ROI {i.roi} · impact {i.impact} · effort {i.effort})"
        )
    lines.append("")
    return lines


def _render_measured(item: RoadmapItem) -> str:
    """The ` · imported by N · M LOC` suffix for an item's headline (may be empty)."""
    measured = []
    if item.fan_in:
        measured.append(f"imported by {item.fan_in}")
    if item.loc:
        measured.append(f"{item.loc} LOC")
    return f" · {' · '.join(measured)}" if measured else ""


def _render_why(item: RoadmapItem) -> list[str]:
    """The grounded ``↳ why:`` line for an item, or empty when there's nothing.

    Surfaces the already-grounded reasoning (the node's rationale, else its
    seeding fact) plus an expected payoff, turning a ranked list into a *reasoned*
    plan. Phrased to avoid the literals "imported by"/"LOC" so the zero-metric
    negative-render test holds.
    """
    why = (item.rationale or "").strip() or (
        item.source_facts[0].strip() if item.source_facts else "")
    payoff = (
        f" — doing it protects the {item.fan_in} module(s) that depend on it"
        if item.fan_in else "")
    if why or payoff:
        return [f"    ↳ why: {why}{payoff}"]
    return []


def _render_phase(n: int, phase: RoadmapPhase) -> list[str]:
    """One phase: heading, summary line, then each item with its why-line."""
    lines = [
        f"## Phase {n}: {phase.name} — {phase.theme}",
        f"_{len(phase.items)} ideas · total impact {phase.total_impact}_",
        "",
    ]
    for i in phase.items:
        lines.append(
            f"- `{i.branch_path}` {i.title}  "
            f"(ROI {i.roi} · impact {i.impact} · effort {i.effort}{_render_measured(i)})"
        )
        lines += _render_why(i)
    lines.append("")
    return lines


def render_roadmap_markdown(roadmap: Roadmap) -> str:
    """Render the roadmap as a readable, phase-ordered markdown document."""
    lines = _render_header(roadmap)
    lines += _render_best_first_move(roadmap)
    lines += _render_quick_wins(roadmap)
    for n, phase in enumerate(roadmap.phases, start=1):
        lines += _render_phase(n, phase)
    return "\n".join(lines)
