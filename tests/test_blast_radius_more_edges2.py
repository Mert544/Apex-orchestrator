from __future__ import annotations

from pathlib import Path

from app.engine.blast_radius import (
    _reverse_map,
    blast_radius,
)
from app.tools.dependency_graph import DependencyNode


def _node(path: str, imports: list[str]) -> DependencyNode:
    return DependencyNode(path=path, imports=set(imports))


def test_reverse_map_skips_skipped_path_key_and_target():
    # The real DependencyGraphBuilder pre-filters worktree copies, so the
    # is_skipped guards inside _reverse_map are only reachable with a synthetic
    # graph that still contains skipped nodes. A skipped node must be dropped as
    # a reverse-map KEY (line 139-140) and any edge whose TARGET is skipped must
    # be ignored (line 142-143), so a .claude copy can neither be a dependent
    # nor pull a real module into the radius.
    graph = {
        "app/a.py": _node("app/a.py", ["app/b.py"]),
        # A worktree copy that imports a real module — its edge must be ignored.
        ".claude/worktrees/wt/app/copy.py": _node(
            ".claude/worktrees/wt/app/copy.py", ["app/b.py"]
        ),
        # A real module that imports a worktree copy — that target is skipped.
        "app/x.py": _node("app/x.py", [".claude/worktrees/wt/app/copy.py"]),
        "app/b.py": _node("app/b.py", []),
    }
    reverse = _reverse_map(graph)

    # No skipped path survives as a key.
    assert all(not k.startswith(".claude/") for k in reverse)
    # app/b.py's dependents include the real importer only, never the copy.
    assert reverse["app/b.py"] == {"app/a.py"}
    # The copy never appears as a dependent of anything.
    for dependents in reverse.values():
        assert all(not d.startswith(".claude/") for d in dependents)
    # The edge into the skipped target produced no reverse entry for it.
    assert ".claude/worktrees/wt/app/copy.py" not in reverse


def test_reverse_map_only_skipped_nodes_yields_empty():
    # Every node is skipped -> the comprehension drops them all and the loop's
    # body never runs past the guard, so the reverse map is empty.
    graph = {
        ".claude/wt/a.py": _node(".claude/wt/a.py", [".claude/wt/b.py"]),
        ".claude/wt/b.py": _node(".claude/wt/b.py", []),
    }
    assert _reverse_map(graph) == {}


def test_transitive_bfs_skips_already_visited_node(tmp_path: Path):
    # Force the BFS revisit guard (line 278): a node that is a direct dependent
    # is also reached again in a later queue layer through another module, so it
    # re-enters the queue after being visited and must be skipped once.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    # b and c both import a (direct dependents); c also imports b; e imports both
    # b and c. Following reverse edges, c is queued from a (direct) and again as a
    # dependent of b, so it re-enters after being visited.
    (tmp_path / "app" / "b.py").write_text("import app.a\n", encoding="utf-8")
    (tmp_path / "app" / "c.py").write_text(
        "import app.a\nimport app.b\n", encoding="utf-8"
    )
    (tmp_path / "app" / "e.py").write_text(
        "import app.b\nimport app.c\n", encoding="utf-8"
    )

    br = blast_radius(tmp_path, ["app/a.py"])
    assert br.direct_dependents == ["app/b.py", "app/c.py"]
    # Full transitive set is unique and sorted despite multiple reach paths.
    assert br.transitive_dependents == ["app/b.py", "app/c.py", "app/e.py"]
    assert len(br.transitive_dependents) == len(set(br.transitive_dependents))


def test_blast_radius_ignores_skipped_changed_paths(tmp_path: Path):
    # A changed path under .claude is dropped before analysis (is_skipped guard
    # in the changed_norm comprehension), contributing nothing to the radius.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("import app.a\n", encoding="utf-8")

    br = blast_radius(
        tmp_path, ["app/a.py", ".claude/worktrees/wt/app/a.py"]
    )
    assert br.changed == ["app/a.py"]
    assert br.direct_dependents == ["app/b.py"]
