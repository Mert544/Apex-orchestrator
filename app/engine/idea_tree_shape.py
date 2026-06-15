"""Measure the shape and health of a generated idea tree.

The IdeaPermutationEngine produces a fractal tree of development directions.
This module lets the engine *look back at the tree it produced* and quantify its
shape — how deep it branches, how evenly it spreads across subjects, what mix of
idea kinds it contains, and how much prioritization signal its scores carry. It
then turns those numbers into plain, deterministic observations ("the tree is
shallow", "one subject dominates", "no fractal facets") that tell a user how to
steer the next run (deeper, wider, with facets, ...).

Pure and deterministic — it reads an ``IdeaTreeReport`` and computes counts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.idea import IdeaTreeReport


@dataclass
class TreeShape:
    total_ideas: int
    roots: int
    max_depth: int
    by_kind: dict[str, int]
    depth_distribution: dict[int, int]
    branching_factor: float          # mean children per internal (parent) node
    distinct_subjects: int
    top_subject: str
    top_subject_share: float          # fraction of ideas on the most-mined subject
    facet_penetration: float          # fraction of ideas that are fractal facets
    mean_value: float
    value_range: float                # max value − min value
    distinct_values: int
    # Measured code-size telemetry (from report.stats["metrics"]).
    heaviest_module: str = ""
    heaviest_loc: int = 0
    total_measured_loc: int = 0
    # How well the tree is grounded in concrete code facts: the fraction of
    # ideas whose ``source_facts`` is non-empty (tied to a real code signal vs.
    # purely-permuted abstractions).
    grounded_count: int = 0
    grounding_ratio: float = 0.0      # grounded_count / total_ideas, in [0,1]
    # Lens diversity: how many DISTINCT development operators (lenses) the tree
    # actually applies. One lens everywhere is shallow reasoning; a balanced
    # spread is richer. The available-operator set is not recorded in the report,
    # so we expose the distinct count plus the single most-applied lens and its
    # share — orthogonal to grounding and kind mix.
    distinct_operators: int = 0
    dominant_operator: str = ""
    dominant_operator_share: float = 0.0  # share of ideas using the top lens, [0,1]
    # Depth balance: the fraction of ideas that are leaves (no child idea was
    # derived from them). A tree of all shallow roots with no facet/permutation
    # expansion sits near 1.0 (under-developed frontier); a tree expanded
    # everywhere drops well below 1.0 (deep interior). Orthogonal to
    # branching_factor (children per *internal* node, which ignores how much of
    # the tree is terminal) and facet_penetration (kind-based), this reads how
    # much of the tree is an unexplored frontier vs. an explored interior.
    leaf_count: int = 0
    leaf_ratio: float = 0.0  # leaf_count / total_ideas, in [0,1]
    # Developmental center of mass: the mean depth across all ideas. Where
    # leaf_ratio counts how much of the tree is *terminal* and branching_factor
    # counts children per *internal* node, mean_depth reads how far from the
    # roots the typical idea sits — two trees with identical leaf_ratio and
    # branching_factor can still differ here (a wide bush of depth-1 children vs.
    # a narrow deep spine). Roots-only trees sit at 0.0; deeply chained trees
    # climb toward max_depth. depth_balance normalizes it into [0,1] by
    # mean_depth / max_depth so it reads independently of how deep the run was
    # allowed to go (0.0 = everything clustered at the roots, →1.0 = mass pushed
    # to the deepest frontier).
    mean_depth: float = 0.0  # sum(depth) / total_ideas, ≥ 0
    depth_balance: float = 0.0  # mean_depth / max_depth, in [0,1]
    # Subject concentration: a Herfindahl-style index over the WHOLE subject
    # distribution — the sum of squared per-subject shares. Where
    # top_subject_share reads only how big the single largest subject is, this
    # reads how concentrated the entire tree is: two trees can share the same
    # top_subject_share yet differ sharply in their tail (the rest on 2 subjects
    # vs. spread over 20). 1.0 = every idea on one subject (maximal obsession);
    # 1/distinct_subjects when evenly spread, →0 as ideas fan out across many
    # subjects. Orthogonal to distinct_subjects (a raw count, blind to balance)
    # and top_subject_share (single-bucket). Roots' subjects count like any other.
    subject_concentration: float = 0.0  # sum of squared subject shares, in [0,1]
    # Function-grain specificity: the share of ideas that name a concrete
    # ``anchor`` (a specific risky function/line WITHIN a module, e.g.
    # "cyclomatic 18 at foo:42") rather than staying at file/module granularity.
    # Where grounding_ratio reads whether an idea ties to a code signal AT ALL
    # (non-empty ``source_facts``), this reads how FAR DOWN the idea drills: a
    # tree of "refactor module X" ideas with no function locus sits at 0.0, while
    # a tree that points at the riskiest symbol in each module climbs toward 1.0.
    # Orthogonal to grounding (signal presence) and subject concentration
    # (which subject) — it reads grain, not coverage. Anchors are additive and
    # default-empty, so legacy ideas with no anchor data simply read 0.0.
    anchored_count: int = 0
    anchor_coverage: float = 0.0  # anchored_count / total_ideas, in [0,1]
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _measured_loc(report: IdeaTreeReport) -> tuple[str, int, int]:
    """Return ``(heaviest_module, heaviest_loc, total_measured_loc)`` from the
    engine's per-subject metrics. Deterministic tie-break (loc desc, path asc);
    missing/empty/malformed metrics yield ``("", 0, 0)``.
    """
    metrics = (report.stats or {}).get("metrics", {}) or {}
    if not isinstance(metrics, dict) or not metrics:
        return "", 0, 0
    total = 0
    best_path = ""
    best_loc = 0
    for path in sorted(metrics):  # stable order before the tie-break
        entry = metrics[path] or {}
        try:
            loc = int(entry.get("loc", 0) or 0)
        except (TypeError, ValueError):
            loc = 0
        total += loc
        if loc > best_loc:
            best_loc = loc
            best_path = path
    if best_loc <= 0:
        return "", 0, total
    return best_path, best_loc, total


def analyze_tree_shape(report: IdeaTreeReport) -> TreeShape:
    ideas = report.ideas
    total = len(ideas)
    heaviest_module, heaviest_loc, total_measured_loc = _measured_loc(report)
    if total == 0:
        return TreeShape(
            total_ideas=0, roots=0, max_depth=0, by_kind={}, depth_distribution={},
            branching_factor=0.0, distinct_subjects=0, top_subject="",
            top_subject_share=0.0, facet_penetration=0.0, mean_value=0.0,
            value_range=0.0, distinct_values=0,
            heaviest_module=heaviest_module, heaviest_loc=heaviest_loc,
            total_measured_loc=total_measured_loc,
            observations=["Empty idea tree — nothing was generated."],
        )

    by_kind = dict(Counter(i.kind for i in ideas))
    depth_dist = dict(sorted(Counter(i.depth for i in ideas).items()))
    max_depth = max(i.depth for i in ideas)
    roots = sum(1 for i in ideas if i.depth == 0)

    # Branching factor: children per node that actually has children.
    child_counts = Counter(i.parent_id for i in ideas if i.parent_id)
    branching_factor = (
        round(sum(child_counts.values()) / len(child_counts), 4) if child_counts else 0.0
    )

    # Depth balance: leaves are ideas that are no idea's parent. The set of
    # parents is exactly the keys of child_counts; everything else is terminal.
    parent_ids = set(child_counts)
    leaf_count = sum(1 for i in ideas if i.id not in parent_ids)
    leaf_ratio = round(leaf_count / total, 4)

    # Developmental center of mass: mean idea depth, normalized by max_depth.
    mean_depth = round(sum(i.depth for i in ideas) / total, 4)
    depth_balance = round(mean_depth / max_depth, 4) if max_depth else 0.0

    subjects = Counter(i.subject for i in ideas if i.subject)
    distinct_subjects = len(subjects)
    top_subject, top_count = subjects.most_common(1)[0] if subjects else ("", 0)
    top_subject_share = round(top_count / total, 4)

    # Subject concentration: Herfindahl index over the whole subject
    # distribution (sum of squared shares). Shares are taken over the ideas that
    # carry a subject; an all-blank-subject tree concentrates on nothing (0.0).
    labelled = sum(subjects.values())
    subject_concentration = (
        round(sum((c / labelled) ** 2 for c in subjects.values()), 4)
        if labelled
        else 0.0
    )

    facet_penetration = round(by_kind.get("facet", 0) / total, 4)

    values = [i.value for i in ideas]
    mean_value = round(sum(values) / total, 4)
    value_range = round(max(values) - min(values), 4)
    distinct_values = len(set(values))

    grounded_count = sum(1 for i in ideas if i.source_facts)
    grounding_ratio = round(grounded_count / total, 4)

    # Function-grain specificity: ideas that carry at least one concrete anchor
    # (a function/line locus within a module) vs. ideas that stay file-level.
    anchored_count = sum(1 for i in ideas if i.anchors)
    anchor_coverage = round(anchored_count / total, 4)

    # Lens diversity: distinct operators used + the dominant lens and its share.
    # Tie-break for the dominant lens is deterministic (count desc, name asc).
    operators = Counter(i.operator for i in ideas if i.operator)
    distinct_operators = len(operators)
    if operators:
        dominant_operator, dominant_count = min(
            operators.items(), key=lambda kv: (-kv[1], kv[0])
        )
        dominant_operator_share = round(dominant_count / total, 4)
    else:
        dominant_operator, dominant_operator_share = "", 0.0

    shape = TreeShape(
        total_ideas=total,
        roots=roots,
        max_depth=max_depth,
        by_kind=by_kind,
        depth_distribution=depth_dist,
        branching_factor=branching_factor,
        distinct_subjects=distinct_subjects,
        top_subject=top_subject,
        top_subject_share=top_subject_share,
        subject_concentration=subject_concentration,
        facet_penetration=facet_penetration,
        mean_value=mean_value,
        value_range=value_range,
        distinct_values=distinct_values,
        grounded_count=grounded_count,
        grounding_ratio=grounding_ratio,
        anchored_count=anchored_count,
        anchor_coverage=anchor_coverage,
        distinct_operators=distinct_operators,
        dominant_operator=dominant_operator,
        dominant_operator_share=dominant_operator_share,
        leaf_count=leaf_count,
        leaf_ratio=leaf_ratio,
        mean_depth=mean_depth,
        depth_balance=depth_balance,
        heaviest_module=heaviest_module,
        heaviest_loc=heaviest_loc,
        total_measured_loc=total_measured_loc,
    )
    shape.observations = _observe(shape, by_kind)
    return shape


def _observe(s: TreeShape, by_kind: dict[str, int]) -> list[str]:
    """Deterministic, threshold-based readings of the tree's shape."""
    obs: list[str] = []
    if s.max_depth <= 1:
        obs.append("Tree is shallow (depth ≤ 1) — raise --depth to permute further.")
    if s.branching_factor and s.branching_factor < 1.5:
        obs.append("Sparse branching — raise --breadth to apply more lenses per idea.")
    if s.total_ideas > 1 and s.leaf_ratio >= 0.9:
        obs.append(
            "Almost every idea is a leaf — the tree is a flat frontier with little "
            "expansion; raise --depth to develop directions further."
        )
    elif s.total_ideas > 1 and s.leaf_ratio <= 0.25:
        obs.append(
            "Few leaves remain — the tree is densely expanded and may be "
            "over-elaborated; the frontier is small."
        )
    if s.max_depth >= 2 and s.depth_balance < 0.34:
        obs.append(
            "Most ideas cluster near the roots while only a few branches run deep "
            "— the tree's development is top-heavy rather than evenly elaborated."
        )
    if s.top_subject_share > 0.5:
        obs.append(
            f"One subject dominates ({int(s.top_subject_share * 100)}% of ideas: "
            f"`{s.top_subject}`) — coverage is narrow."
        )
    elif s.distinct_subjects >= max(3, s.roots):
        obs.append(f"Ideas spread across {s.distinct_subjects} subjects — good breadth of coverage.")
    if (
        s.distinct_subjects >= 3
        and s.top_subject_share <= 0.5
        and s.subject_concentration >= 0.34
    ):
        obs.append(
            "No single subject dominates, but ideas clump onto a handful of subjects "
            "— concentration is high across the whole tree, not just the top one."
        )
    if by_kind.get("synthesis", 0) + by_kind.get("pair", 0) == 0:
        obs.append("No synthesis/pair ideas — few cross-module couplings were found.")
    if s.facet_penetration == 0.0:
        obs.append("No fractal facets — enable --facets to drill into specifics.")
    else:
        obs.append(f"Fractal facets are {int(s.facet_penetration * 100)}% of the tree.")
    if s.distinct_values < max(3, s.total_ideas // 3):
        obs.append("Scores are clustered — limited prioritization signal between ideas.")
    if s.distinct_operators <= 1:
        obs.append(
            "A single lens shapes the whole tree — raise --breadth to apply more "
            "development operators per idea."
        )
    elif s.dominant_operator_share > 0.5:
        obs.append(
            f"One lens (`{s.dominant_operator}`) drives most ideas — reasoning leans "
            "on a single development operator."
        )
    if s.grounding_ratio < 0.5:
        obs.append(
            f"Weakly grounded — only {int(s.grounding_ratio * 100)}% of ideas tie to "
            "concrete code facts; many are pure permutations."
        )
    if s.total_ideas > 0 and s.anchor_coverage == 0.0:
        obs.append(
            "No function-grain anchors — ideas stay at file/module granularity; "
            "no idea names a specific risky symbol to act on first."
        )
    elif s.anchor_coverage >= 0.5:
        obs.append(
            f"Function-grain: {int(s.anchor_coverage * 100)}% of ideas name a concrete "
            "symbol/line to act on first, not just a file."
        )
    if s.total_measured_loc > 0 and s.heaviest_loc > 0.4 * s.total_measured_loc:
        pct = round(100 * s.heaviest_loc / s.total_measured_loc)
        obs.append(
            f"Most measured code sits in `{s.heaviest_module}` "
            f"({pct}% of {s.total_measured_loc} LOC) — a refactor/test focus."
        )
    if not obs:
        obs.append("Well-shaped tree: balanced depth, breadth, and scoring spread.")
    return obs


def render_tree_shape_markdown(shape: TreeShape) -> str:
    """Render the tree-shape analysis as a compact markdown report."""
    lines = ["# Idea Tree Shape", ""]
    lines += [
        f"- **Ideas:** {shape.total_ideas}  (roots {shape.roots}, max depth {shape.max_depth})",
        "- **By kind:** " + ", ".join(f"{k} {v}" for k, v in sorted(shape.by_kind.items())),
        "- **Depth distribution:** "
        + ", ".join(f"d{d}={n}" for d, n in sorted(shape.depth_distribution.items())),
        f"- **Branching factor:** {shape.branching_factor}",
        f"- **Depth balance:** {int(shape.leaf_ratio * 100)}% of ideas are leaves "
        f"({shape.leaf_count}/{shape.total_ideas}) — terminal frontier vs. expanded interior",
        f"- **Developmental center of mass:** mean depth {shape.mean_depth} "
        f"of {shape.max_depth} (balance {shape.depth_balance}) — roots vs. deep frontier",
        f"- **Subjects:** {shape.distinct_subjects} distinct · "
        f"top `{shape.top_subject}` ({int(shape.top_subject_share * 100)}%) · "
        f"concentration {shape.subject_concentration}",
        f"- **Fractal facets:** {int(shape.facet_penetration * 100)}% of ideas",
        f"- **Scoring:** mean {shape.mean_value} · range {shape.value_range} · "
        f"{shape.distinct_values} distinct values",
        f"- **Grounding:** {int(shape.grounding_ratio * 100)}% of ideas "
        f"({shape.grounded_count}/{shape.total_ideas}) tied to concrete code facts",
        f"- **Function-grain:** {int(shape.anchor_coverage * 100)}% of ideas "
        f"({shape.anchored_count}/{shape.total_ideas}) name a concrete symbol/line anchor",
        f"- **Lens diversity:** {shape.distinct_operators} distinct operators · "
        f"dominant `{shape.dominant_operator}` "
        f"({int(shape.dominant_operator_share * 100)}% of ideas)",
    ]
    if shape.total_measured_loc > 0:
        lines.append(
            f"- **Measured size:** {shape.total_measured_loc} LOC across modules · "
            f"heaviest `{shape.heaviest_module}` ({shape.heaviest_loc} LOC)"
        )
    lines += ["", "## Observations"]
    lines += [f"- {o}" for o in shape.observations]
    lines.append("")
    return "\n".join(lines)
