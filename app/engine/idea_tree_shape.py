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

    subjects = Counter(i.subject for i in ideas if i.subject)
    distinct_subjects = len(subjects)
    top_subject, top_count = subjects.most_common(1)[0] if subjects else ("", 0)
    top_subject_share = round(top_count / total, 4)

    facet_penetration = round(by_kind.get("facet", 0) / total, 4)

    values = [i.value for i in ideas]
    mean_value = round(sum(values) / total, 4)
    value_range = round(max(values) - min(values), 4)
    distinct_values = len(set(values))

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
        facet_penetration=facet_penetration,
        mean_value=mean_value,
        value_range=value_range,
        distinct_values=distinct_values,
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
    if s.top_subject_share > 0.5:
        obs.append(
            f"One subject dominates ({int(s.top_subject_share * 100)}% of ideas: "
            f"`{s.top_subject}`) — coverage is narrow."
        )
    elif s.distinct_subjects >= max(3, s.roots):
        obs.append(f"Ideas spread across {s.distinct_subjects} subjects — good breadth of coverage.")
    if by_kind.get("synthesis", 0) + by_kind.get("pair", 0) == 0:
        obs.append("No synthesis/pair ideas — few cross-module couplings were found.")
    if s.facet_penetration == 0.0:
        obs.append("No fractal facets — enable --facets to drill into specifics.")
    else:
        obs.append(f"Fractal facets are {int(s.facet_penetration * 100)}% of the tree.")
    if s.distinct_values < max(3, s.total_ideas // 3):
        obs.append("Scores are clustered — limited prioritization signal between ideas.")
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
        + ", ".join(f"d{d}={n}" for d, n in shape.depth_distribution.items()),
        f"- **Branching factor:** {shape.branching_factor}",
        f"- **Subjects:** {shape.distinct_subjects} distinct · "
        f"top `{shape.top_subject}` ({int(shape.top_subject_share * 100)}%)",
        f"- **Fractal facets:** {int(shape.facet_penetration * 100)}% of ideas",
        f"- **Scoring:** mean {shape.mean_value} · range {shape.value_range} · "
        f"{shape.distinct_values} distinct values",
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
