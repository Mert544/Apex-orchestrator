"""Byte-identical characterization harness for ``canvas_from_ideas``.

Pins the *exact* JSONCanvas output of the refactored ``canvas_from_ideas``
against a verbatim copy of the pre-refactor implementation (``_reference``
below, lifted from ``git show HEAD:app/reporting/idea_canvas.py``). Every input
below is constructed to exercise a distinct branch:

* empty list (early return),
* single root, multi-child tree, deep tree,
* parentless synthesis/pair ideas (rendered as roots),
* dangling parent_id (parent not in tree),
* duplicate canvas ids (last-write-wins index),
* duplicate parent->child edge ids (de-dup),
* orphaned-but-non-root ideas (unreachable fallback placement),
* scrambled emit order, unknown kind (no color), kind == "".

The comparison serialises the full canvas with ``json.dumps(..., sort_keys=True,
indent=2)`` so any node/edge/coordinate/color/text difference fails loudly.
"""

from __future__ import annotations

import json

import pytest

from app.models.idea import IdeaNode
from app.reporting.idea_canvas import (
    _KIND_COLORS,
    _node_id,
    _sort_key,
    _text,
    canvas_from_ideas,
    edge,
    node,
    to_canvas,
)

# Layout constants copied verbatim from the pre-refactor module so the reference
# is fully self-contained.
_NODE_WIDTH = 320
_NODE_HEIGHT = 60
_COL_GAP = 120
_ROW_GAP = 30


def _reference(ideas: list[IdeaNode]) -> dict:
    """Verbatim pre-refactor ``canvas_from_ideas`` (HEAD snapshot)."""
    if not ideas:
        return to_canvas([], [])

    by_id: dict[str, IdeaNode] = {}
    for idea in ideas:
        by_id[_node_id(idea)] = idea

    children: dict[str | None, list[IdeaNode]] = {}
    for idea in ideas:
        parent = idea.parent_id if (idea.parent_id in by_id) else None
        children.setdefault(parent, []).append(idea)
    for bucket in children.values():
        bucket.sort(key=_sort_key)

    row_in_depth: dict[int, int] = {}
    positioned: dict[str, tuple[int, int]] = {}

    def place(idea: IdeaNode, depth: int) -> None:
        key = _node_id(idea)
        if key in positioned:
            return
        row = row_in_depth.get(depth, 0)
        row_in_depth[depth] = row + 1
        positioned[key] = (depth, row)
        for child in children.get(key, []):
            place(child, depth + 1)

    for root in sorted(children.get(None, []), key=_sort_key):
        place(root, 0)
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


def _idea(id_: str, **kw) -> IdeaNode:
    kw.setdefault("title", f"Title {id_}")
    kw.setdefault("branch_path", f"x.{id_}")
    return IdeaNode(id=id_, **kw)


# Each case is (label, list-of-ideas) exercising a distinct branch.
_CASES: list[tuple[str, list[IdeaNode]]] = [
    ("empty", []),
    ("single_root", [_idea("r")]),
    (
        "root_two_children",
        [
            _idea("r"),
            _idea("r-0", parent_id="r"),
            _idea("r-1", parent_id="r"),
        ],
    ),
    (
        "deep_tree_scrambled",
        [
            _idea("r-0-0", parent_id="r-0", depth=2),
            _idea("r-1", parent_id="r"),
            _idea("r"),
            _idea("r-0", parent_id="r", depth=1),
            _idea("r-0-1", parent_id="r-0", depth=2),
        ],
    ),
    (
        "parentless_synthesis_and_pair",
        [
            _idea("synth-0", kind="synthesis", branch_path="x.s0"),
            _idea("pair-0", kind="pair", branch_path="x.p0"),
            _idea("r"),
            _idea("r-0", parent_id="r"),
        ],
    ),
    (
        "dangling_parent",
        [
            _idea("orphan", parent_id="ghost"),
            _idea("r"),
        ],
    ),
    (
        "facet_kind",
        [
            _idea("r"),
            _idea("r.f0", parent_id="r", kind="facet"),
        ],
    ),
    (
        "unknown_kind_no_color",
        [
            _idea("r", kind="mystery"),
            _idea("r-0", parent_id="r", kind="permutation"),
        ],
    ),
    (
        "empty_kind_defaults_permutation",
        [
            _idea("r", kind=""),
        ],
    ),
    (
        "duplicate_ids_last_wins",
        [
            _idea("dup", title="First"),
            _idea("dup", title="Second", parent_id="root"),
            _idea("root"),
        ],
    ),
    (
        "wide_tree",
        [_idea("r")] + [_idea(f"r-{i}", parent_id="r") for i in range(6)],
    ),
    (
        "multiple_roots",
        [
            _idea("a"),
            _idea("b"),
            _idea("c"),
            _idea("a-0", parent_id="a"),
            _idea("b-0", parent_id="b"),
        ],
    ),
    (
        "missing_id_uses_branch_then_title",
        [
            IdeaNode(id="", title="NoId", branch_path="bp-1"),
            IdeaNode(id="", title="OnlyTitle", branch_path=""),
        ],
    ),
    (
        "cycle_guard",
        [
            _idea("p", parent_id="q"),
            _idea("q", parent_id="p"),
        ],
    ),
]


def _dump(canvas: dict) -> str:
    return json.dumps(canvas, sort_keys=True, indent=2)


@pytest.mark.parametrize("label,ideas", _CASES, ids=[c[0] for c in _CASES])
def test_canvas_from_ideas_byte_identical(label: str, ideas: list[IdeaNode]):
    assert _dump(canvas_from_ideas(ideas)) == _dump(_reference(ideas)), label


def test_every_branch_label_covered():
    # Guard that the case table keeps exercising the named branches.
    labels = {c[0] for c in _CASES}
    assert {
        "empty",
        "parentless_synthesis_and_pair",
        "dangling_parent",
        "duplicate_ids_last_wins",
        "cycle_guard",
        "unknown_kind_no_color",
    } <= labels
