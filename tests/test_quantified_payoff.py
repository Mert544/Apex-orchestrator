"""Quantified payoff: module-level roots name their concrete blast radius.

Module-level recommendations (confluence, dependency-hub, fragile, complexity-
hotspot) now enrich their ``rationale`` with a GROUNDED, quantified clause pulled
from the SAME dependency data the profiler already builds (no second graph):

- **fan-in** — ``Imported by N modules — a change here ripples to all of them``
  (the literal blast radius, on every module-level root);
- **decoupling targets** — for hub/confluence roots, names this module's heaviest
  fan-out dependencies (e.g. ``Its 3 heaviest dependencies are app/x.py, ... —
  decoupling one cuts the convergence``).

These tests pin: the clause names a REAL fan-in count derived from a synthetic
edge list; hub roots name their ACTUAL heaviest dependencies in deterministic
(fan-in desc, then path) order; the byte-identical fallback when no dependency
data is available; determinism; and the value/feasibility/novelty invariants.
Numbers are derived straight from ``dependency_edges`` so a synthetic graph is
enough — no profiler/filesystem run needed.
"""

from app.engine.idea_permutation import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _confluence(module, families=("complex-function", "high-churn", "hub")) -> dict:
    fams = tuple(sorted(families))
    return {"module": module, "family_count": len(fams), "families": fams}


def _root(roots, subject):
    return next(r for r in roots if r.subject == subject)


# --- fan-in clause from a synthetic edge list -------------------------------

def test_fragile_root_names_real_fanin_count():
    module = "app/core.py"
    # Three DISTINCT modules import app/core.py -> fan-in 3.
    edges = [
        ("app/a.py", "app/core.py"),
        ("app/b.py", "app/core.py"),
        ("app/c.py", "app/core.py"),
        ("app/a.py", "app/b.py"),  # noise: unrelated edge
    ]
    profile = _profile(fragile_modules=[module], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), module)
    assert "Imported by 3 modules — a change here ripples to all of them." in root.rationale
    # Fragile is depended-ON; it does NOT name decoupling targets.
    assert "heaviest" not in root.rationale


def test_fanin_counts_distinct_importers_not_edges():
    module = "app/core.py"
    # Same source imports core twice (two symbols) -> still fan-in 1.
    edges = [
        ("app/a.py", "app/core.py"),
        ("app/a.py", "app/core.py"),
    ]
    profile = _profile(fragile_modules=[module], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), module)
    assert "Imported by 1 module — a change here ripples to all of them." in root.rationale


def test_complexity_hotspot_root_carries_fanin_only():
    module = "app/hot.py"
    edges = [("app/x.py", module), ("app/y.py", module)]
    profile = _profile(hotspot_modules=[module], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), module)
    assert "Imported by 2 modules" in root.rationale
    assert "heaviest" not in root.rationale


# --- decoupling targets: hub/confluence name heaviest dependencies ----------

def test_dependency_hub_root_names_heaviest_dependencies_sorted():
    hub = "app/hub.py"
    # hub depends on x, y, z, w. Their OWN fan-in decides the ranking.
    edges = [
        ("app/hub.py", "app/x.py"),
        ("app/hub.py", "app/y.py"),
        ("app/hub.py", "app/z.py"),
        ("app/hub.py", "app/w.py"),
        # x imported by 3 others, y by 2, z by 1, w by 1.
        ("app/a.py", "app/x.py"), ("app/b.py", "app/x.py"), ("app/c.py", "app/x.py"),
        ("app/a.py", "app/y.py"), ("app/b.py", "app/y.py"),
        ("app/a.py", "app/z.py"),
        ("app/a.py", "app/w.py"),
        # someone imports the hub too -> hub has fan-in 1.
        ("app/d.py", "app/hub.py"),
    ]
    profile = _profile(dependency_hubs=[hub], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), hub)
    # fan-in clause present.
    assert "Imported by 1 module" in root.rationale
    # Heaviest THREE deps, fan-in desc then path: x(3), y(2), then z/w tie at 1
    # -> path asc picks w before z. Capped at 3, so z is dropped.
    assert ("Its 3 heaviest dependencies are app/w.py, app/x.py, app/y.py "
            "— decoupling one cuts the convergence.") not in root.rationale
    assert ("Its 3 heaviest dependencies are app/x.py, app/y.py, app/w.py "
            "— decoupling one cuts the convergence.") in root.rationale


def test_confluence_root_names_decoupling_targets():
    module = "app/conv.py"
    edges = [
        ("app/conv.py", "app/dep1.py"),
        ("app/conv.py", "app/dep2.py"),
        ("app/imp.py", "app/conv.py"),
        # dep1 is depended on more than dep2.
        ("app/a.py", "app/dep1.py"), ("app/b.py", "app/dep1.py"),
        ("app/a.py", "app/dep2.py"),
    ]
    profile = _profile(confluence_modules=[_confluence(module)],
                       dependency_edges=edges, ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), module)
    assert "Imported by 1 module" in root.rationale
    assert ("Its 2 heaviest dependencies are app/dep1.py, app/dep2.py "
            "— decoupling one cuts the convergence.") in root.rationale


def test_single_dependency_uses_singular_grammar():
    hub = "app/hub.py"
    edges = [
        ("app/hub.py", "app/only.py"),
        ("app/a.py", "app/hub.py"),
        ("app/b.py", "app/hub.py"),
    ]
    profile = _profile(dependency_hubs=[hub], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), hub)
    assert "Imported by 2 modules" in root.rationale
    assert "Its 1 heaviest dependency is app/only.py — decoupling one cuts the convergence." in root.rationale


# --- precomputed dicts on the profile are used when present -----------------

def test_precomputed_module_fanin_fanout_are_used():
    hub = "app/hub.py"
    # No dependency_edges at all — only the precomputed dicts. The clause must
    # still fire off them (the profiler-populated path).
    profile = _profile(
        dependency_hubs=[hub],
        module_fanin={hub: 7},
        module_fanout={hub: ["app/x.py", "app/y.py"]},
        ci_files=["ci.yml"],
    )
    root = _root(IdeaSeeder().seed(profile), hub)
    assert "Imported by 7 modules" in root.rationale
    assert ("Its 2 heaviest dependencies are app/x.py, app/y.py "
            "— decoupling one cuts the convergence.") in root.rationale


# --- byte-identical fallback when no dependency data ------------------------

def test_byte_identical_fallback_with_no_dependency_data():
    module = "app/plain.py"
    base = _profile(fragile_modules=[module], ci_files=["ci.yml"])
    # An IDENTICAL profile that wires an empty edge list / empty dicts must
    # produce the same rationale bytes as one with no dependency fields at all.
    with_empty = _profile(fragile_modules=[module], ci_files=["ci.yml"],
                          dependency_edges=[], module_fanin={}, module_fanout={})
    r_base = _root(IdeaSeeder().seed(base), module)
    r_empty = _root(IdeaSeeder().seed(with_empty), module)
    assert r_base.rationale == r_empty.rationale
    # And no quantified phrasing leaked in.
    assert "Imported by" not in r_base.rationale
    assert "heaviest" not in r_base.rationale


def test_module_absent_from_graph_degrades_silently():
    # Edges exist but name OTHER modules; the fragile module isn't in them.
    module = "app/orphan.py"
    edges = [("app/a.py", "app/b.py"), ("app/c.py", "app/b.py")]
    profile = _profile(fragile_modules=[module], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), module)
    assert "Imported by" not in root.rationale
    assert "heaviest" not in root.rationale


def test_hub_with_fanin_but_no_dependencies_emits_only_fanin():
    hub = "app/leaf_hub.py"
    # Imported by two modules, imports nothing itself.
    edges = [("app/a.py", hub), ("app/b.py", hub)]
    profile = _profile(dependency_hubs=[hub], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), hub)
    assert "Imported by 2 modules" in root.rationale
    assert "heaviest" not in root.rationale  # name_targets=True but no fan-out


# --- non-hub _RULES roots carry no quantified clause ------------------------

def test_sensitive_path_root_has_no_quantified_clause():
    sens = "app/auth.py"
    edges = [("app/a.py", sens), ("app/b.py", sens)]
    profile = _profile(sensitive_paths=[sens], dependency_edges=edges,
                       ci_files=["ci.yml"])
    root = _root(IdeaSeeder().seed(profile), sens)
    assert "Imported by" not in root.rationale
    assert "heaviest" not in root.rationale


# --- determinism -------------------------------------------------------------

def test_quantified_rationale_is_deterministic_across_runs():
    hub = "app/hub.py"
    edges = [
        ("app/hub.py", "app/x.py"), ("app/hub.py", "app/y.py"),
        ("app/a.py", "app/x.py"), ("app/b.py", "app/x.py"),
        ("app/a.py", "app/y.py"),
        ("app/c.py", "app/hub.py"),
    ]
    profile = _profile(dependency_hubs=[hub], dependency_edges=edges,
                       ci_files=["ci.yml"])
    first = IdeaSeeder().seed(profile)
    second = IdeaSeeder().seed(profile)
    assert [r.to_dict() for r in first] == [r.to_dict() for r in second]


def test_fanin_fanout_helper_is_deterministic_and_capped():
    edges = [
        ("m.py", "t1.py"), ("m.py", "t2.py"), ("m.py", "t3.py"), ("m.py", "t4.py"),
        ("a.py", "m.py"), ("b.py", "m.py"),
        # ties at fan-in 0 for all targets -> path-sorted, capped at 3.
    ]
    fanin, targets = IdeaSeeder._fanin_fanout_from_edges(edges, "m.py")
    assert fanin == 2
    assert targets == ["t1.py", "t2.py", "t3.py"]  # sorted by path, capped


# --- value / feasibility / novelty invariants -------------------------------

def test_node_invariants_hold_with_quantified_clause():
    hub = "app/hub.py"
    edges = [
        ("app/hub.py", "app/x.py"),
        ("app/a.py", "app/hub.py"), ("app/b.py", "app/hub.py"),
    ]
    profile = _profile(dependency_hubs=[hub], confluence_modules=[_confluence("app/c.py")],
                       fragile_modules=["app/f.py"], dependency_edges=edges,
                       ci_files=["ci.yml"])
    for r in IdeaSeeder().seed(profile):
        assert 0.0 <= r.value <= 1.0
        assert 0.0 <= r.feasibility <= 1.0
        assert 0.0 <= r.novelty <= 1.0
        assert r.novelty == 1.0  # roots keep novelty == 1.0
