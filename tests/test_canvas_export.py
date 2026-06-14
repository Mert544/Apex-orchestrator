from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli import cmd_canvas
from app.reporting.canvas_export import (
    dependency_canvas,
    edge,
    node,
    to_canvas,
    write_canvas,
)


def _make_project(root: Path) -> None:
    app = root / "app"
    app.mkdir()
    (app / "a.py").write_text("import app.b\n")
    (app / "b.py").write_text("import app.c\n")
    (app / "c.py").write_text("def c():\n    return 1\n")


def test_node_and_edge_are_spec_valid():
    n = node("app/a.py", "app/a.py", 0, 0)
    assert n["id"] == "app/a.py"
    assert n["type"] == "text"
    assert n["text"] == "app/a.py"
    assert all(isinstance(n[k], int) for k in ("x", "y", "width", "height"))
    assert "color" not in n

    n_colored = node("app/a.py", "x", 0, 0, color="4")
    assert n_colored["color"] == "4"

    e = edge("app/a.py->app/b.py", "app/a.py", "app/b.py")
    assert e == {"id": "app/a.py->app/b.py", "fromNode": "app/a.py", "toNode": "app/b.py"}

    e_labeled = edge("e1", "a", "b", label="imports")
    assert e_labeled["label"] == "imports"


def test_to_canvas_shape():
    canvas = to_canvas([node("n1", "n1", 0, 0)], [])
    assert set(canvas.keys()) == {"nodes", "edges"}
    assert isinstance(canvas["nodes"], list)
    assert isinstance(canvas["edges"], list)


def test_dependency_canvas_is_spec_valid(tmp_path: Path):
    _make_project(tmp_path)
    canvas = dependency_canvas(tmp_path)

    assert set(canvas.keys()) == {"nodes", "edges"}
    assert canvas["nodes"], "expected at least one module node"

    node_ids = {n["id"] for n in canvas["nodes"]}
    for n in canvas["nodes"]:
        assert {"id", "type", "text", "x", "y", "width", "height"} <= set(n)
        assert n["type"] == "text"
    for e in canvas["edges"]:
        assert {"id", "fromNode", "toNode"} <= set(e)
        assert e["fromNode"] in node_ids
        assert e["toNode"] in node_ids

    # a->b and b->c import edges are present
    edge_ids = {e["id"] for e in canvas["edges"]}
    assert "app/a.py->app/b.py" in edge_ids
    assert "app/b.py->app/c.py" in edge_ids


def test_dependency_canvas_is_deterministic(tmp_path: Path):
    _make_project(tmp_path)
    first = json.dumps(dependency_canvas(tmp_path), indent=2, sort_keys=True)
    second = json.dumps(dependency_canvas(tmp_path), indent=2, sort_keys=True)
    assert first == second


def test_write_canvas_byte_identical(tmp_path: Path):
    _make_project(tmp_path)
    canvas = dependency_canvas(tmp_path)
    out1 = tmp_path / "one.canvas"
    out2 = tmp_path / "two.canvas"
    write_canvas(canvas, out1)
    write_canvas(dependency_canvas(tmp_path), out2)
    assert out1.read_bytes() == out2.read_bytes()


def test_dependency_canvas_excludes_worktree(tmp_path: Path):
    _make_project(tmp_path)
    worktree = tmp_path / ".claude" / "worktrees" / "agent-x" / "app"
    worktree.mkdir(parents=True)
    (worktree / "copy.py").write_text("import app.b\n")

    canvas = dependency_canvas(tmp_path)
    node_ids = {n["id"] for n in canvas["nodes"]}
    assert not any(".claude" in nid for nid in node_ids)
    assert not any("copy.py" in nid for nid in node_ids)
    for e in canvas["edges"]:
        assert ".claude" not in e["fromNode"]
        assert ".claude" not in e["toNode"]


def test_dependency_canvas_empty_project(tmp_path: Path):
    canvas = dependency_canvas(tmp_path)
    assert canvas == {"nodes": [], "edges": []}


def test_cli_writes_parseable_canvas(tmp_path: Path):
    _make_project(tmp_path)
    out = tmp_path / "apex.canvas"
    args = argparse.Namespace(target=str(tmp_path), out=str(out))
    assert cmd_canvas(args) == 0
    assert out.exists()

    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert set(parsed.keys()) == {"nodes", "edges"}
    assert parsed["nodes"]
