"""Export Apex's Idea Permutation tree as a JSONCanvas (`.canvas`) file.

A companion to ``app.reporting.canvas_export`` (the dependency-graph exporter):
this module turns the Idea Permutation Engine's tree of development ideas into
the same open infinite-canvas format — ``{"nodes": [...], "edges": [...]}`` —
so a project's idea tree opens as a navigable left-to-right map in Obsidian or
any JSONCanvas tool.

The public entry point is :func:`idea_canvas`, which runs the engine
(``IdeaPermutationEngine(...).run()``) and lays the resulting ideas out by tree
DEPTH: depth → column (x), sibling order → row (y), with fixed gaps. One node
per idea, one edge per parent→child link.

Everything is deterministic and stdlib-only: ids derive from the stable idea id,
siblings are sorted by a stable key, and the layout is a fixed grid — so the same
project yields a byte-identical canvas. No LLM, no network, no time, no
randomness. The JSONCanvas primitives (``node``/``edge``/``to_canvas``/
``write_canvas``) are imported from ``canvas_export`` and never modified here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode
from app.reporting.canvas_export import (  # noqa: F401  (write_canvas re-exported)
    edge,
    node,
    to_canvas,
    write_canvas,
)

# Layout constants (deterministic left-to-right tree). An idea at tree depth
# ``d`` lands in column ``d`` (x); its position among all ideas drawn at that
# depth gives its row (y). Fixed gaps keep the layout reproducible.
_NODE_WIDTH = 320
_NODE_HEIGHT = 60
_COL_GAP = 120
_ROW_GAP = 30

# Preset JSONCanvas colors ("1".."6") per idea kind, so the visual tree
# distinguishes permutation branches from synthesized/paired/faceted ideas.
# Deterministic; unknown kinds simply carry no color.
_KIND_COLORS: dict[str, str] = {
    "permutation": "5",  # cyan
    "synthesis": "4",    # green
    "pair": "6",         # purple
    "facet": "2",        # orange
}


def _node_id(idea: IdeaNode) -> str:
    """Stable, deterministic canvas node id for an idea.

    The engine's idea ids are already unique per run and stable across runs
    (derived from seeding facts and operator indices); the branch_path is a
    stable tiebreaker for the rare case an id is missing.
    """
    return idea.id or idea.branch_path or idea.title


def _sort_key(idea: IdeaNode) -> tuple[str, str, str]:
    """Stable sibling ordering key: id, then branch_path, then title.

    Independent of value/score (which would couple layout to the scorer); a
    pure structural key keeps the canvas reproducible and order-insensitive to
    the order ideas happen to be emitted in.
    """
    return (_node_id(idea), idea.branch_path, idea.title)


def _text(idea: IdeaNode) -> str:
    """Canvas text for an idea: its title, prefixed by its kind tag."""
    kind = idea.kind or "permutation"
    return f"[{kind}] {idea.title}"


def idea_canvas(project_root: str | Path, **engine_config: Any) -> dict:
    """Build a JSONCanvas from Apex's Idea Permutation tree.

    Runs :class:`IdeaPermutationEngine` on ``project_root`` and renders one
    canvas node per idea and one edge per parent→child link. The layout is a
    deterministic left-to-right tree: tree depth selects the column (x), and the
    sibling order (a stable id/branch/title sort) selects the row (y).

    ``engine_config`` is forwarded to the engine (e.g. ``max_total_ideas``,
    ``max_idea_depth``, ``breadth``); defaults reproduce a standard ideate run.
    If the idea tree is empty, an empty canvas (``to_canvas([], [])``) is
    returned.
    """
    report = IdeaPermutationEngine(engine_config or None, project_root).run()
    return canvas_from_ideas(report.ideas)


def canvas_from_ideas(ideas: list[IdeaNode]) -> dict:
    """Render an explicit list of idea nodes as a JSONCanvas (layout + edges).

    Split out from :func:`idea_canvas` so the layout is testable on a synthetic
    tree without running the engine. Conservative on the empty case.
    """
    if not ideas:
        return to_canvas([], [])

    # Index ideas by their canvas id; map each parent to its sorted children so
    # the layout walks a deterministic tree regardless of emit order.
    by_id: dict[str, IdeaNode] = {}
    for idea in ideas:
        by_id[_node_id(idea)] = idea

    children: dict[str | None, list[IdeaNode]] = {}
    for idea in ideas:
        # An idea is a child of its parent only when that parent is in the tree;
        # synthesis/pair ideas are parentless and so render as their own roots.
        parent = idea.parent_id if (idea.parent_id in by_id) else None
        children.setdefault(parent, []).append(idea)
    for bucket in children.values():
        bucket.sort(key=_sort_key)

    # Assign each idea a (depth, row) slot. Depth comes from walking the parent
    # links (robust even if a stored ``depth`` field is stale), and a per-depth
    # running counter assigns rows in a stable pre-order walk.
    row_in_depth: dict[int, int] = {}
    positioned: dict[str, tuple[int, int]] = {}

    def place(idea: IdeaNode, depth: int) -> None:
        key = _node_id(idea)
        if key in positioned:
            return  # guard against any accidental cycle in parent links
        row = row_in_depth.get(depth, 0)
        row_in_depth[depth] = row + 1
        positioned[key] = (depth, row)
        for child in children.get(key, []):
            place(child, depth + 1)

    # Roots = parentless ideas, in stable order; walk each subtree pre-order.
    for root in sorted(children.get(None, []), key=_sort_key):
        place(root, 0)
    # Any idea unreachable from a root (e.g. an orphaned parent ref) still gets a
    # slot at depth 0 so no idea is silently dropped.
    for idea in sorted(ideas, key=_sort_key):
        if _node_id(idea) not in positioned:
            place(idea, 0)

    nodes: list[dict] = []
    for idea in sorted(ideas, key=_sort_key):
        key = _node_id(idea)
        depth, row = positioned[key]
        x = depth * (_NODE_WIDTH + _COL_GAP)
        y = row * (_NODE_HEIGHT + _ROW_GAP)
        nodes.append(
            node(
                key,
                _text(idea),
                x,
                y,
                width=_NODE_WIDTH,
                height=_NODE_HEIGHT,
                color=_KIND_COLORS.get(idea.kind or "permutation"),
            )
        )

    # One edge per parent→child link, both endpoints present. Sorted by id and
    # de-duplicated so the edge list is reproducible.
    seen: set[str] = set()
    edges: list[dict] = []
    for idea in ideas:
        parent = idea.parent_id
        if not parent or parent not in by_id:
            continue
        child_id = _node_id(idea)
        edge_id = f"{parent}->{child_id}"
        if edge_id in seen:
            continue
        seen.add(edge_id)
        edges.append(edge(edge_id, parent, child_id))
    edges.sort(key=lambda item: item["id"])

    return to_canvas(nodes, edges)
