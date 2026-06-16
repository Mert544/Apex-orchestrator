"""Characterization test for ``IdeaSeeder._quantified_clause`` refactor.

Pins the exact string output of ``_quantified_clause`` (and its helper
decomposition) across every branch: precomputed dicts present/absent, edge
fallback, fan-in zero/one/many, named targets zero/one/many, and the
name_targets toggle. The expected strings are frozen against the pre-refactor
implementation (proven byte-identical via an inlined reference below).
"""
from __future__ import annotations

from app.engine.idea_seeder import IdeaSeeder


class _Profile:
    def __init__(self, module_fanin=None, module_fanout=None,
                 dependency_edges=None):
        self.module_fanin = module_fanin
        self.module_fanout = module_fanout
        self.dependency_edges = dependency_edges


def _reference_clause(seeder, profile, module, *, name_targets):
    """Verbatim pre-refactor body of ``_quantified_clause``."""
    fanin = (getattr(profile, "module_fanin", {}) or {}).get(module)
    targets = (getattr(profile, "module_fanout", {}) or {}).get(module)
    if fanin is None or (name_targets and targets is None):
        edges = getattr(profile, "dependency_edges", []) or []
        cache = seeder.__dict__.setdefault("_importers_cache", {})
        ckey = id(profile)
        importers = cache.get(ckey)
        if importers is None:
            importers = seeder._build_importers(edges)
            cache[ckey] = importers
        edge_fanin, edge_targets = seeder._fanin_fanout_from_edges(
            edges, module, importers)
        if fanin is None:
            fanin = edge_fanin
        if targets is None:
            targets = edge_targets
    parts: list[str] = []
    if fanin:
        noun = "module" if fanin == 1 else "modules"
        parts.append(
            f"Imported by {fanin} {noun} — a change here ripples to all of them."
        )
    if name_targets and targets:
        listed = ", ".join(targets)
        n = len(targets)
        noun = "dependency" if n == 1 else "dependencies"
        verb = "is" if n == 1 else "are"
        parts.append(
            f"Its {n} heaviest {noun} {verb} {listed} "
            f"— decoupling one cuts the convergence."
        )
    return " ".join(parts)


def _profiles():
    profs = []
    # Precomputed dicts: fan-in 0/1/many, targets none/one/many.
    for fanin in (None, 0, 1, 2, 5):
        for targets in (None, [], ["app/a.py"], ["app/a.py", "app/b.py", "app/c.py"]):
            profs.append(_Profile(
                module_fanin={"m": fanin} if fanin is not None else {},
                module_fanout={"m": targets} if targets is not None else {},
                dependency_edges=[],
            ))
    # Edge-fallback scenarios (dicts empty/missing, edges drive the result).
    edge_sets = [
        [],
        [("x", "m")],
        [("x", "m"), ("y", "m"), ("z", "m")],
        [("m", "app/a.py"), ("m", "app/b.py")],
        [("m", "app/a.py"), ("x", "app/a.py"), ("m", "app/b.py"),
         ("m", "app/c.py"), ("m", "app/d.py")],
        [("m", "m")],  # self-edge ignored
        [("a", "m"), ("a", "m")],  # duplicate import
    ]
    for edges in edge_sets:
        profs.append(_Profile(module_fanin={}, module_fanout={},
                              dependency_edges=edges))
        profs.append(_Profile(module_fanin=None, module_fanout=None,
                              dependency_edges=edges))
        # Mixed: fan-in precomputed, targets fall back to edges.
        profs.append(_Profile(module_fanin={"m": 7}, module_fanout={},
                              dependency_edges=edges))
    return profs


def test_byte_identical_to_reference():
    mismatches = 0
    total = 0
    for profile in _profiles():
        for name_targets in (True, False):
            seeder_ref = IdeaSeeder()
            seeder_new = IdeaSeeder()
            expected = _reference_clause(
                seeder_ref, profile, "m", name_targets=name_targets)
            actual = seeder_new._quantified_clause(
                profile, "m", name_targets=name_targets)
            total += 1
            if expected != actual:
                mismatches += 1
    assert mismatches == 0, f"{mismatches}/{total} mismatched"
    assert total > 0


def test_exact_strings_pinned():
    s = IdeaSeeder()
    p = _Profile(module_fanin={"m": 1}, module_fanout={"m": ["app/a.py"]})
    assert s._quantified_clause(p, "m", name_targets=False) == (
        "Imported by 1 module — a change here ripples to all of them."
    )
    p2 = _Profile(module_fanin={"m": 3},
                  module_fanout={"m": ["app/a.py", "app/b.py"]})
    assert s._quantified_clause(p2, "m", name_targets=True) == (
        "Imported by 3 modules — a change here ripples to all of them. "
        "Its 2 heaviest dependencies are app/a.py, app/b.py "
        "— decoupling one cuts the convergence."
    )
    p3 = _Profile(module_fanin={"m": 0}, module_fanout={"m": []})
    assert s._quantified_clause(p3, "m", name_targets=True) == ""
