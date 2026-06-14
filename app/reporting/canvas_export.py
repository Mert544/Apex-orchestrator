"""Export Apex's deterministic graph analyses as a JSONCanvas (`.canvas`) file.

JSONCanvas (jsoncanvas.org, maintained by Obsidian) is the open infinite-canvas
format: a JSON object ``{"nodes": [...], "edges": [...]}``. Emitting Apex's
dependency graph in this format lets users open the project's import structure as
a navigable visual knowledge graph in Obsidian or any JSONCanvas tool.

Everything here is deterministic and stdlib-only: nodes/edges are sorted by their
stable keys, ids derive from the module path, and the layout is a fixed grid
sorted by module path — so the same project yields a byte-identical canvas. No
LLM, no network, no time, no randomness.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.tools.dependency_graph import DependencyGraphBuilder

# Layout constants (deterministic grid). A module lands at column ``i % COLUMNS``
# and row ``i // COLUMNS`` for its index ``i`` in the path-sorted node list.
_COLUMNS = 6
_NODE_WIDTH = 250
_NODE_HEIGHT = 60
_COL_GAP = 100
_ROW_GAP = 80

# Directories whose files never belong in a dependency canvas. Worktrees live
# under ``.claude/worktrees`` and must be excluded so a checked-out agent copy
# never leaks into the exported graph.
_EXCLUDED_DIRS = (
    ".claude",
    ".git",
    ".apex",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)


def _is_excluded(module_path: str) -> bool:
    """True if ``module_path`` lives under an excluded directory."""
    parts = Path(module_path).parts
    return any(part in _EXCLUDED_DIRS for part in parts)


def _node_id(module_path: str) -> str:
    """Derive a stable, deterministic node id from a module path."""
    return module_path.replace("\\", "/")


def node(
    node_id: str,
    text: str,
    x: int,
    y: int,
    width: int = _NODE_WIDTH,
    height: int = _NODE_HEIGHT,
    color: str | None = None,
) -> dict:
    """Build a spec-valid JSONCanvas text node."""
    out: dict = {
        "id": node_id,
        "type": "text",
        "text": text,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }
    if color is not None:
        out["color"] = color
    return out


def edge(
    edge_id: str,
    from_node: str,
    to_node: str,
    label: str | None = None,
) -> dict:
    """Build a spec-valid JSONCanvas edge."""
    out: dict = {
        "id": edge_id,
        "fromNode": from_node,
        "toNode": to_node,
    }
    if label is not None:
        out["label"] = label
    return out


def to_canvas(nodes: list[dict], edges: list[dict]) -> dict:
    """Assemble a spec-valid JSONCanvas document from nodes and edges."""
    return {"nodes": list(nodes), "edges": list(edges)}


def dependency_canvas(project_root: str | Path) -> dict:
    """Build a JSONCanvas from Apex's dependency graph.

    One node per module, one edge per import edge. Layout is a fixed grid sorted
    by module path; ids derive from the module path. Modules under excluded
    directories (worktrees, caches, VCS) are dropped so the canvas reflects only
    real project source.
    """
    builder = DependencyGraphBuilder(project_root)
    graph = builder.build()

    # Sorted, excluded-filtered module list drives both ids and the grid layout.
    module_paths = sorted(
        path for path in graph if not _is_excluded(path)
    )
    kept = set(module_paths)

    nodes: list[dict] = []
    for index, module_path in enumerate(module_paths):
        column = index % _COLUMNS
        row = index // _COLUMNS
        x = column * (_NODE_WIDTH + _COL_GAP)
        y = row * (_NODE_HEIGHT + _ROW_GAP)
        nodes.append(node(_node_id(module_path), module_path, x, y))

    # Edges: one per (source -> target) import, both endpoints kept. Sorted by
    # endpoint for determinism and de-duplicated by id.
    seen: set[str] = set()
    edges: list[dict] = []
    for source in module_paths:
        for target in sorted(graph[source].imports):
            if target not in kept:
                continue
            edge_id = f"{_node_id(source)}->{_node_id(target)}"
            if edge_id in seen:
                continue
            seen.add(edge_id)
            edges.append(edge(edge_id, _node_id(source), _node_id(target)))
    edges.sort(key=lambda item: item["id"])

    return to_canvas(nodes, edges)


def write_canvas(canvas: dict, path: str | Path) -> None:
    """Write a JSONCanvas document to ``path`` deterministically.

    Keys are sorted and a trailing newline is appended so the same canvas always
    serializes to byte-identical content.
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(canvas, indent=2, sort_keys=True) + "\n"
    out_path.write_text(text, encoding="utf-8")
