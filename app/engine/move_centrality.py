"""Blast-radius (fan-in) signal for value-aware move targeting.

When the buyer opts into value-aware ordering (``min_move_value > 0``), the move
loop wants to land the HIGHEST-blast-radius move first — a characterization test
for a module five other modules import buys more safety than one for a leaf
nothing depends on. The fan-in number that ranks them already exists in the
dependency graph (``DependencyNode.in_degree``); this module is the one-line
adapter that turns that graph into a ``module -> in-degree`` map keyed exactly
like a move's target module (``_move_module``), so the compiler can use it as a
SUBORDINATE sort key without re-deriving the graph.

Determinism: pure function of the source tree (the graph builder is itself
deterministic — no clock, no random, no network). The per-root memo only avoids
re-walking the tree within one campaign; it never changes the result.
"""

from __future__ import annotations

from pathlib import Path

# Per-root memo: the in-degree map is a pure, expensive (full-tree walk +
# import resolution) derivation of the source tree, and ONE campaign re-asks for
# it on every pass. Keyed by the resolved absolute root string so two different
# project roots never collide; a fresh campaign on an edited tree gets a fresh
# answer because the cache key is per-root and the underlying parse cache is
# mtime-invalidated. The cache is module-level (process-wide), matching the
# DependencyGraphBuilder's own process-level parse cache.
_IN_DEGREES_CACHE: dict[str, dict[str, int]] = {}


def module_in_degrees(root: str | Path) -> dict[str, int]:
    """``module path -> number of internal modules that import it`` for ``root``.

    Wraps ``DependencyGraphBuilder(root).build()`` and reads each node's
    already-populated ``in_degree``. The keys are the graph's own node paths
    (root-relative, e.g. ``app/engine/foo.py``) — the SAME string a move's
    ``_move_module`` yields — so a caller can look a move's module up directly.

    Memoized per resolved root. Returns an EMPTY map for a tree with no Python
    modules (the in-degree of nothing), which the caller treats as a uniform-zero
    signal (a no-op tiebreak)."""
    key = str(Path(root).resolve())
    cached = _IN_DEGREES_CACHE.get(key)
    if cached is not None:
        return cached

    from app.tools.dependency_graph import DependencyGraphBuilder

    graph = DependencyGraphBuilder(root).build()
    # Normalise keys to POSIX separators so they match a move's ``_move_module``,
    # which yields ``Path.as_posix()`` (forward slashes). On POSIX ``node.path``
    # is already ``/``-separated so this is a no-op; on Windows ``str(node.path)``
    # would be ``\``-separated and the lookup would silently miss (degrading the
    # tiebreak to an inert uniform-zero) — ``as_posix`` keeps the signal working
    # cross-platform, which matters for the teams Apex serves on Windows.
    degrees = {Path(node.path).as_posix(): node.in_degree
               for node in graph.values()}
    _IN_DEGREES_CACHE[key] = degrees
    return degrees
