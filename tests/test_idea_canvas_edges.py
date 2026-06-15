"""Edge-path coverage for app.reporting.idea_canvas.

Targets the conservative guards in ``canvas_from_ideas`` that the happy-path
tests don't reach: the place()-cycle guard, the unreachable-orphan fallback,
and duplicate-edge de-duplication. All synthetic, deterministic, hermetic — no
engine run, no project on disk.
"""

from __future__ import annotations

from app.models.idea import IdeaNode
from app.reporting.idea_canvas import canvas_from_ideas


def test_cyclic_parent_links_do_not_loop_and_every_idea_is_placed():
    # Two ideas that name each other as parent form a cycle. Both parents are in
    # the tree, so neither is a root (children.get(None) is empty); the orphan
    # fallback then seeds one at depth 0 and place()'s positioned-guard stops the
    # recursion from looping forever. The canvas must still contain both nodes.
    a = IdeaNode(id="a", title="A", parent_id="b", branch_path="x.a")
    b = IdeaNode(id="b", title="B", parent_id="a", branch_path="x.b")

    canvas = canvas_from_ideas([a, b])

    ids = {n["id"] for n in canvas["nodes"]}
    assert ids == {"a", "b"}
    # Each node placed exactly once (the cycle guard prevented a re-place).
    assert len(canvas["nodes"]) == 2
    # Both endpoints exist, so both parent->child edges are emitted.
    edge_ids = {e["id"] for e in canvas["edges"]}
    assert edge_ids == {"a->b", "b->a"}


def test_self_parent_idea_is_placed_once_via_cycle_guard():
    # An idea that is its own parent: it is its own (in-tree) parent, so it's not
    # a root; the orphan fallback places it at depth 0 and the place()-guard
    # blocks the self-recursion. A self-edge is still emitted (both endpoints =
    # the same present node).
    me = IdeaNode(id="me", title="Me", parent_id="me", branch_path="x.me")

    canvas = canvas_from_ideas([me])

    assert [n["id"] for n in canvas["nodes"]] == ["me"]
    assert canvas["nodes"][0]["x"] == 0  # placed at depth 0
    assert {e["id"] for e in canvas["edges"]} == {"me->me"}


def test_unreachable_orphan_gets_a_depth_zero_slot():
    # A child whose parent id is present, but that parent is itself unreachable
    # from any root because IT names a missing parent. The first idea is never
    # reached from children.get(None); the orphan fallback gives it a depth-0
    # slot so no idea is silently dropped.
    orphan_parent = IdeaNode(
        id="op", title="OrphanParent", parent_id="ghost", branch_path="x.op"
    )
    child = IdeaNode(id="c", title="Child", parent_id="op", branch_path="x.c")

    canvas = canvas_from_ideas([orphan_parent, child])

    ids = {n["id"] for n in canvas["nodes"]}
    assert ids == {"op", "c"}
    pos = {n["id"]: (n["x"], n["y"]) for n in canvas["nodes"]}
    # The orphan parent has no in-tree parent ("ghost" absent) -> root, column 0.
    assert pos["op"][0] == 0
    # Its child sits one column to the right.
    assert pos["c"][0] > pos["op"][0]
    # Only the in-tree parent->child link is an edge ("ghost" is absent).
    assert {e["id"] for e in canvas["edges"]} == {"op->c"}


def test_duplicate_parent_child_link_yields_one_edge():
    # Two distinct ideas sharing the same id collapse to one canvas node id, so
    # the same parent->child edge id is generated twice. The seen-set must keep
    # exactly one edge.
    root = IdeaNode(id="r", title="Root", branch_path="x.r")
    c1 = IdeaNode(id="dup", title="C1", parent_id="r", branch_path="x.c1")
    c2 = IdeaNode(id="dup", title="C2", parent_id="r", branch_path="x.c2")

    canvas = canvas_from_ideas([root, c1, c2])

    edges = [e for e in canvas["edges"] if e["id"] == "r->dup"]
    assert len(edges) == 1
    # And it is a real parent->child link.
    assert edges[0]["fromNode"] == "r"
    assert edges[0]["toNode"] == "dup"


def test_edges_omitted_when_parent_absent_from_tree():
    # parent_id points outside the supplied list -> no edge (the `parent not in
    # by_id` guard), and the child renders as its own root.
    lonely = IdeaNode(id="lo", title="Lonely", parent_id="not-here", branch_path="x.lo")

    canvas = canvas_from_ideas([lonely])

    assert canvas["edges"] == []
    assert canvas["nodes"][0]["x"] == 0
