"""Edge-path coverage for app.reporting.canvas_export.

Targets the two conservative branches in ``dependency_canvas`` the happy-path
tests don't reach: an import edge whose *target* lives under an excluded dir (so
the edge is dropped), and a duplicate edge id (so the seen-set keeps one). Both
are driven by a stubbed DependencyGraphBuilder so the graph shape is explicit,
deterministic and hermetic — no real source tree needed.
"""

from __future__ import annotations

from app.reporting import canvas_export
from app.reporting.canvas_export import dependency_canvas
from app.tools.dependency_graph import DependencyNode


def _graph(spec: dict[str, set[str]]) -> dict[str, DependencyNode]:
    """Build a {path: DependencyNode(imports=...)} graph from a path->imports map."""
    nodes = {path: DependencyNode(path=path) for path in spec}
    for path, imports in spec.items():
        nodes[path].imports = set(imports)
    return nodes


def _patch_builder(monkeypatch, graph: dict[str, DependencyNode]) -> None:
    monkeypatch.setattr(
        canvas_export.DependencyGraphBuilder, "build", lambda self: graph
    )


def test_edge_to_excluded_target_is_dropped(tmp_path, monkeypatch):
    # app/a.py imports a module that lives under __pycache__ (an excluded dir).
    # The target is filtered out of `kept`, so the edge must not be emitted —
    # even though the source is a real, kept node.
    graph = _graph(
        {
            "app/a.py": {"app/__pycache__/gen.py"},
            "app/__pycache__/gen.py": set(),
        }
    )
    _patch_builder(monkeypatch, graph)

    canvas = dependency_canvas(tmp_path)

    node_ids = {n["id"] for n in canvas["nodes"]}
    assert node_ids == {"app/a.py"}  # excluded module is not a node
    # The edge to the excluded target was dropped (line: target not in kept).
    assert canvas["edges"] == []


def test_kept_edge_survives_alongside_dropped_excluded_edge(tmp_path, monkeypatch):
    # Same source imports both a kept module and an excluded one: the kept edge
    # is emitted, the excluded one dropped. Proves the filter is per-target.
    graph = _graph(
        {
            "app/a.py": {"app/b.py", "app/.venv/lib.py"},
            "app/b.py": set(),
            "app/.venv/lib.py": set(),
        }
    )
    _patch_builder(monkeypatch, graph)

    canvas = dependency_canvas(tmp_path)

    node_ids = {n["id"] for n in canvas["nodes"]}
    assert node_ids == {"app/a.py", "app/b.py"}
    assert {e["id"] for e in canvas["edges"]} == {"app/a.py->app/b.py"}


def test_duplicate_edge_id_is_de_duplicated(tmp_path, monkeypatch):
    # Two source paths that normalise to the same node id (backslash vs forward
    # slash) both import the same target, generating the same edge id twice. The
    # seen-set must keep exactly one edge.
    graph = _graph(
        {
            "app/a.py": {"app/b.py"},
            "app\\a.py": {"app/b.py"},
            "app/b.py": set(),
        }
    )
    _patch_builder(monkeypatch, graph)

    canvas = dependency_canvas(tmp_path)

    matching = [e for e in canvas["edges"] if e["id"] == "app/a.py->app/b.py"]
    assert len(matching) == 1
    assert matching[0]["fromNode"] == "app/a.py"
    assert matching[0]["toNode"] == "app/b.py"


def test_empty_graph_yields_empty_canvas(tmp_path, monkeypatch):
    _patch_builder(monkeypatch, {})
    assert dependency_canvas(tmp_path) == {"nodes": [], "edges": []}
