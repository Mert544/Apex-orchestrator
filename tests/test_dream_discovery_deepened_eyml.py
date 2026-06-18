"""Deepened dream discovery — the recurring multi-signal CLIQUE dimension.

The classic three discoveries answer "which pair travels together" (association),
"which pair implies a third" (triple), and "which one module carries an unusually
broad fingerprint" (confluence). The clique dimension answers a question none of
those can: *which whole bundle of three-or-more signals recurs together across
several modules?* — a fingerprint the data binds, not one any rule named.

These tests pin the new dimension's behaviour on synthetic profiles, prove the
richer ``discovered_idea_seeds`` descriptors still carry exactly the four keys,
and re-assert determinism, the cap, dedup, and the empty/clean -> ``[]`` floor
that keeps a consuming seeder byte-identical. They never touch the pinned
``discover_structured`` golden — the clique view is purely additive.
"""

from __future__ import annotations

from app.engine.dream_discovery import (
    CLIQUE_MIN_SIZE,
    CLIQUE_MIN_SUPPORT,
    SEED_CAP,
    discover_cliques,
    discover_emergent,
    discover_structured,
    discovered_idea_seeds,
)
from app.tools.project_profile import ProjectProfile

_REQUIRED_KEYS = {"module", "title", "fact_label", "fact_value"}


def _clique_profile() -> ProjectProfile:
    # Two modules carry the IDENTICAL broad bundle {security, untested, fragile,
    # debt}; a third carries only one tag. The full bundle recurs on two modules
    # -> a clique no single association/confluence names.
    bundle_mods = ["app/core.py", "app/io.py"]
    return ProjectProfile(
        root=".",
        security_finding_modules=list(bundle_mods),
        untested_modules=bundle_mods + ["app/lonely.py"],
        fragile_modules=list(bundle_mods),
        debt_marker_modules=list(bundle_mods),
    )


def test_clique_surfaces_a_recurring_signal_bundle():
    found = discover_cliques(_clique_profile())
    assert found, "a bundle recurring on >= CLIQUE_MIN_SUPPORT modules is a clique"
    top = found[0]
    assert top.kind == "clique"
    # The whole >= 3-signal bundle is named, not just a pair.
    for tag in ("security", "untested", "fragile", "debt"):
        assert tag in top.text
    assert top.support >= CLIQUE_MIN_SUPPORT
    assert 0.0 <= top.confidence <= 1.0


def test_clique_key_is_magnitude_free_and_sorted():
    top = discover_cliques(_clique_profile())[0]
    # Stable identity: the sorted tag set, independent of support/confidence.
    assert top.key == "clique:debt&fragile&security&untested"


def test_no_clique_when_bundle_does_not_recur():
    # The broad bundle lands on ONE module only (support 1 < CLIQUE_MIN_SUPPORT);
    # a one-off fingerprint is a confluence, not a recurring clique.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/hot.py"],
        untested_modules=["app/hot.py", "app/x.py"],
        fragile_modules=["app/hot.py"],
        debt_marker_modules=["app/hot.py"],
    )
    assert discover_cliques(profile) == []


def test_no_clique_below_min_size():
    # Two modules share a 2-signal bundle: that is an association, never a clique
    # (a clique needs at least CLIQUE_MIN_SIZE distinct signals).
    assert CLIQUE_MIN_SIZE >= 3
    profile = ProjectProfile(
        root=".",
        untested_modules=["app/a.py", "app/b.py"],
        debt_marker_modules=["app/a.py", "app/b.py"],
    )
    assert discover_cliques(profile) == []


def test_discover_emergent_is_purely_additive():
    profile = _clique_profile()
    base = discover_structured(profile)
    emergent = discover_emergent(profile)
    # The classic discoveries are an exact prefix; cliques are appended last.
    assert [d.to_dict() for d in emergent[: len(base)]] == [d.to_dict() for d in base]
    assert any(d.kind == "clique" for d in emergent)
    # Opting out reproduces the classic view byte-for-byte.
    assert [d.to_dict() for d in discover_emergent(profile, include_cliques=False)] == \
        [d.to_dict() for d in base]


def test_discover_structured_is_untouched_by_clique_dimension():
    # The pinned classic surface never carries a clique.
    assert all(d.kind != "clique" for d in discover_structured(_clique_profile()))


def test_clique_descriptor_carries_all_four_keys():
    seeds = discovered_idea_seeds(_clique_profile())
    assert seeds
    for seed in seeds:
        assert set(seed.keys()) == _REQUIRED_KEYS
        assert all(isinstance(seed[k], str) and seed[k] for k in _REQUIRED_KEYS)
        assert seed["fact_label"] == "discovered-pattern"


def _clique_source_profile() -> ProjectProfile:
    # z1/z2 carry the recurring 3-signal bundle {fragile, security, untested}.
    # The o/p/q modules raise the typical breadth and dilute each individual tag
    # so neither a pairwise association nor a confluence claims z1/z2 first —
    # leaving the CLIQUE as the discovery that grounds them. This is exactly the
    # case the clique dimension exists to surface: a bundle no narrower lens names.
    return ProjectProfile(
        root=".",
        security_finding_modules=["app/z1.py", "app/z2.py", "app/o1.py",
                                  "app/o2.py", "app/o3.py"],
        untested_modules=["app/z1.py", "app/z2.py", "app/o1.py",
                          "app/p1.py", "app/p2.py"],
        fragile_modules=["app/z1.py", "app/z2.py", "app/o2.py",
                         "app/q1.py", "app/q2.py"],
        debt_marker_modules=["app/o1.py", "app/o2.py", "app/o3.py",
                             "app/p1.py", "app/q1.py"],
    )


def test_clique_descriptor_grounds_in_a_real_carrier_module():
    seeds = discovered_idea_seeds(_clique_source_profile())
    bundle_seed = next(
        (s for s in seeds if "all travel together" in s["fact_value"]), None)
    assert bundle_seed is not None, "the recurring bundle should become a seed"
    # Bound to a concrete module carrying the WHOLE bundle (sorted-first).
    assert bundle_seed["module"] in {"app/z1.py", "app/z2.py"}
    assert bundle_seed["module"] in bundle_seed["title"]
    assert "bundle" in bundle_seed["title"]
    assert set(bundle_seed.keys()) == _REQUIRED_KEYS


def test_seeds_are_deterministic():
    profile = _clique_profile()
    assert discovered_idea_seeds(profile) == discovered_idea_seeds(profile)
    assert [d.to_dict() for d in discover_cliques(profile)] == \
        [d.to_dict() for d in discover_cliques(profile)]


def test_seeds_dedup_one_per_module_and_respect_cap():
    # Eight modules all carry the same broad bundle: associations, confluences
    # AND a clique all point at these modules, but the output is deduped by
    # module and bounded at SEED_CAP.
    mods = [f"app/m{i}.py" for i in range(8)]
    profile = ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
        fragile_modules=list(mods),
        debt_marker_modules=list(mods),
    )
    seeds = discovered_idea_seeds(profile)
    assert len(seeds) <= SEED_CAP
    modules = [s["module"] for s in seeds]
    assert len(modules) == len(set(modules))


def test_empty_profile_yields_nothing():
    empty = ProjectProfile(root=".")
    assert discover_cliques(empty) == []
    assert discover_emergent(empty) == []
    assert discovered_idea_seeds(empty) == []


def test_clean_profile_below_threshold_yields_nothing():
    # A single broad module is not a recurring bundle.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py"],
        fragile_modules=["app/a.py"],
    )
    assert discover_cliques(profile) == []
