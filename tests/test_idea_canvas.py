from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode
from app.reporting.idea_canvas import (
    canvas_from_ideas,
    idea_canvas,
    write_canvas,
)


def _project(tmp: Path) -> Path:
    """Mirror the synthetic project the permutation-engine tests build on."""
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp / "app" / "api.py").write_text(
        "import app.main\n\ndef handler():\n    return app.main.main()\n"
    )
    return tmp


_CFG = {"max_total_ideas": 25, "max_idea_depth": 2, "breadth": 3}


def test_idea_canvas_is_spec_valid(tmp_path: Path):
    _project(tmp_path)
    canvas = idea_canvas(tmp_path, **_CFG)

    assert set(canvas.keys()) == {"nodes", "edges"}
    assert canvas["nodes"], "expected at least one idea node"

    node_ids = {n["id"] for n in canvas["nodes"]}
    assert len(node_ids) == len(canvas["nodes"])  # ids are unique
    for n in canvas["nodes"]:
        assert {"id", "type", "text", "x", "y", "width", "height"} <= set(n)
        assert n["type"] == "text"
        assert all(isinstance(n[k], int) for k in ("x", "y", "width", "height"))
        assert n["text"]
    for e in canvas["edges"]:
        assert {"id", "fromNode", "toNode"} <= set(e)
        assert e["fromNode"] in node_ids
        assert e["toNode"] in node_ids


def test_idea_canvas_edges_match_the_tree(tmp_path: Path):
    _project(tmp_path)
    report = IdeaPermutationEngine(_CFG, tmp_path).run()
    canvas = canvas_from_ideas(report.ideas)

    by_id = {i.id: i for i in report.ideas}
    expected = {
        f"{i.parent_id}->{i.id}"
        for i in report.ideas
        if i.parent_id and i.parent_id in by_id
    }
    actual = {e["id"] for e in canvas["edges"]}
    assert actual == expected
    assert expected, "engine should produce at least one parent->child link"

    # Every edge points from a parent to its real child (depth strictly grows).
    id_to_node = {n["id"]: n for n in canvas["nodes"]}
    for e in canvas["edges"]:
        child = by_id[e["toNode"]]
        assert child.parent_id == e["fromNode"]
        # A child sits to the right of (or below) its parent — never above-left.
        assert id_to_node[e["toNode"]]["x"] > id_to_node[e["fromNode"]]["x"]


def test_idea_canvas_layout_by_depth(tmp_path: Path):
    _project(tmp_path)
    report = IdeaPermutationEngine(_CFG, tmp_path).run()
    canvas = canvas_from_ideas(report.ideas)
    by_id = {i.id: i for i in report.ideas}
    id_to_x = {n["id"]: n["x"] for n in canvas["nodes"]}

    # Roots (and parentless synthesis/pair ideas) live in column 0.
    for n in canvas["nodes"]:
        idea = by_id[n["id"]]
        if not idea.parent_id or idea.parent_id not in by_id:
            assert n["x"] == 0
        else:
            # A child always sits in a column to the right of its parent.
            assert id_to_x[n["id"]] > id_to_x[idea.parent_id]


def test_idea_canvas_is_deterministic(tmp_path: Path):
    _project(tmp_path)
    first = json.dumps(idea_canvas(tmp_path, **_CFG), indent=2, sort_keys=True)
    second = json.dumps(idea_canvas(tmp_path, **_CFG), indent=2, sort_keys=True)
    assert first == second


def test_write_canvas_byte_identical(tmp_path: Path):
    _project(tmp_path)
    out1 = tmp_path / "one.canvas"
    out2 = tmp_path / "two.canvas"
    write_canvas(idea_canvas(tmp_path, **_CFG), out1)
    write_canvas(idea_canvas(tmp_path, **_CFG), out2)
    assert out1.read_bytes() == out2.read_bytes()


def test_canvas_from_ideas_synthetic_tree():
    # A tiny explicit tree: root -> a, b ; a -> a1. Emit order is intentionally
    # scrambled to prove layout is independent of it.
    root = IdeaNode(id="r", title="Root", branch_path="x0", depth=0)
    a = IdeaNode(id="r-0", title="A", parent_id="r", branch_path="x0.0", depth=1)
    b = IdeaNode(id="r-1", title="B", parent_id="r", branch_path="x0.1", depth=1)
    a1 = IdeaNode(id="r-0-0", title="A1", parent_id="r-0", branch_path="x0.0.0", depth=2)
    canvas = canvas_from_ideas([a1, b, root, a])

    ids = {n["id"] for n in canvas["nodes"]}
    assert ids == {"r", "r-0", "r-1", "r-0-0"}

    edge_ids = {e["id"] for e in canvas["edges"]}
    assert edge_ids == {"r->r-0", "r->r-1", "r-0->r-0-0"}

    xs = {n["id"]: n["x"] for n in canvas["nodes"]}
    # Columns follow tree depth.
    assert xs["r"] == 0
    assert xs["r-0"] == xs["r-1"] > xs["r"]
    assert xs["r-0-0"] > xs["r-0"]
    # Text is the kind-prefixed title.
    text = {n["id"]: n["text"] for n in canvas["nodes"]}
    assert text["r"] == "[permutation] Root"


def test_canvas_from_ideas_parentless_synthesis_are_roots():
    # Synthesis/pair ideas carry no parent_id: they render in column 0 with no
    # incoming edge, just like a real root.
    synth = IdeaNode(id="synth-0", title="Synth", kind="synthesis", branch_path="x.s0")
    canvas = canvas_from_ideas([synth])
    assert canvas["edges"] == []
    assert canvas["nodes"][0]["x"] == 0
    assert canvas["nodes"][0]["text"] == "[synthesis] Synth"


def test_idea_canvas_empty_tree(tmp_path: Path):
    # An empty project yields no ideas -> an empty (but spec-valid) canvas.
    assert canvas_from_ideas([]) == {"nodes": [], "edges": []}
    canvas = idea_canvas(tmp_path, **_CFG)
    assert set(canvas.keys()) == {"nodes", "edges"}
