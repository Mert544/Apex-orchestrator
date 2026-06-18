"""discovered_idea_seeds — turning emergent discoveries into seedable directions.

The dream's open-ended discovery surfaces "what travels with what" on THIS
codebase; ``discovered_idea_seeds`` shapes the strongest of those associations
into deterministic, deduplicated, capped seed descriptors the IdeaSeeder can
consume directly. These tests pin the descriptor contract (the four keys the
seeder needs), determinism, the cap, dedup, and the empty/clean → ``[]`` path
that keeps an unchanged idea set byte-identical.
"""

from __future__ import annotations

from app.engine.dream_discovery import SEED_CAP, discovered_idea_seeds
from app.tools.project_profile import ProjectProfile

_REQUIRED_KEYS = {"module", "title", "fact_label", "fact_value"}


def _cooccurring_profile() -> ProjectProfile:
    # Every single-author module here is also high-churn -> a discovered law,
    # grounded in the concrete modules that carry both tags.
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/a.py", "commits": 9},
                        {"module": "app/b.py", "commits": 8},
                        {"module": "app/quiet.py", "commits": 7}],
        knowledge_risks=[{"module": "app/a.py", "share": 100, "commits": 9},
                         {"module": "app/b.py", "share": 90, "commits": 8}],
    )


def test_cooccurring_pair_yields_a_grounded_descriptor():
    seeds = discovered_idea_seeds(_cooccurring_profile())
    assert seeds, "a co-occurring signal pair should surface at least one seed"
    first = seeds[0]
    # Bound to a concrete module carrying BOTH co-occurring tags.
    assert first["module"] in {"app/a.py", "app/b.py"}
    assert "single-author" in first["fact_value"]
    assert "high-churn" in first["fact_value"]
    assert first["module"] in first["title"]


def test_every_descriptor_carries_all_four_required_keys():
    for seed in discovered_idea_seeds(_cooccurring_profile()):
        assert set(seed.keys()) == _REQUIRED_KEYS
        assert all(isinstance(seed[k], str) and seed[k] for k in _REQUIRED_KEYS)
        assert seed["fact_label"] == "discovered-pattern"


def test_deterministic_order_across_calls():
    profile = _cooccurring_profile()
    assert discovered_idea_seeds(profile) == discovered_idea_seeds(profile)


def test_confluence_descriptor_names_the_broad_module():
    # One module carries many distinct signals; it surfaces as a confluence seed.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/hot.py"],
        untested_modules=["app/hot.py", "app/x.py"],
        fragile_modules=["app/hot.py"],
        debt_marker_modules=["app/hot.py", "app/y.py"],
    )
    seeds = discovered_idea_seeds(profile)
    assert any(s["module"] == "app/hot.py" for s in seeds)
    hot = next(s for s in seeds if s["module"] == "app/hot.py")
    # Breadth-named: the confluence fact lists several co-occurring signals.
    assert "co-occur" in hot["fact_value"]
    assert hot["fact_label"] == "discovered-pattern"


def test_capped_at_seed_cap():
    # Many modules each carrying a broad, co-occurring fingerprint -> more than
    # SEED_CAP candidate descriptors, but the output is bounded.
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


def test_dedup_one_descriptor_per_module():
    seeds = discovered_idea_seeds(_cooccurring_profile())
    modules = [s["module"] for s in seeds]
    assert len(modules) == len(set(modules))


def test_empty_profile_yields_nothing():
    assert discovered_idea_seeds(ProjectProfile(root=".")) == []


def test_clean_profile_below_threshold_yields_nothing():
    # A single co-occurrence is a coincidence, not a discovered law.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py"],
    )
    assert discovered_idea_seeds(profile) == []
