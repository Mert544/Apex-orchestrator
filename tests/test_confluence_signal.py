"""Confluence (signal convergence) seeding-signal tests.

A confluence is a module named by >= 3 DISTINCT signal families at once — no
single lens names it, yet several independent pressures converging make it the
highest-leverage development target. Mirrors the hub-untested / impure-untested
signals end-to-end: profile field -> seeded root -> fact hint -> roadmap phase
-> action.
"""

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import _FACT_HINTS, _SECURITY_LABELS
from app.engine.idea_roadmap import (
    STABILIZE,
    _HIGH_IMPACT_LABELS,
    _STABILIZE_LABELS,
    classify_phase,
    estimate_impact,
)
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


# --------------------------------------------------------------------------- #
# _scan_confluences — counting DISTINCT families on the profile.
# --------------------------------------------------------------------------- #

def _scan(profile: ProjectProfile) -> ProjectProfile:
    # The scan reads only profile fields, so it needs no filesystem root.
    profiler = ProjectProfiler.__new__(ProjectProfiler)
    profiler._scan_confluences(profile)
    return profile


def test_three_distinct_families_flags_a_confluence():
    profile = _profile(
        dependency_hubs=["app/engine/objective_compiler.py"],
        symbol_hubs=["app/engine/objective_compiler.py"],
        churn_hotspots=[{"module": "app/engine/objective_compiler.py", "commits": 12}],
    )
    _scan(profile)
    assert len(profile.confluence_modules) == 1
    entry = profile.confluence_modules[0]
    assert entry["module"] == "app/engine/objective_compiler.py"
    assert entry["family_count"] == 3
    assert entry["families"] == ("high-churn", "hub", "symbol-hub")


def test_two_families_does_not_flag_a_confluence():
    profile = _profile(
        dependency_hubs=["app/cli.py"],
        symbol_hubs=["app/cli.py"],  # only 2 distinct families
    )
    _scan(profile)
    assert profile.confluence_modules == []


def test_same_family_is_never_double_counted():
    # untested + critical-untested + hub-untested all collapse to ONE family
    # ("untested"); with only the hub family beside it that is 2, not a
    # confluence — proving families dedup.
    profile = _profile(
        untested_modules=["app/m.py"],
        critical_untested_modules=["app/m.py"],
        hub_untested_modules=[{"module": "app/m.py", "fan_in": 9}],
        dependency_hubs=["app/m.py"],
    )
    _scan(profile)
    assert profile.confluence_modules == []


def test_deterministic_ordering_count_desc_then_module_asc():
    profile = _profile(
        dependency_hubs=["app/b.py", "app/a.py"],
        symbol_hubs=["app/b.py", "app/a.py"],
        churn_hotspots=[
            {"module": "app/b.py", "commits": 5},
            {"module": "app/a.py", "commits": 5},
        ],
        fragile_modules=["app/b.py"],  # b gets a 4th family
    )
    _scan(profile)
    mods = [e["module"] for e in profile.confluence_modules]
    # b (4 families) before a (3 families); count desc, then module asc.
    assert mods == ["app/b.py", "app/a.py"]
    assert [e["family_count"] for e in profile.confluence_modules] == [4, 3]


def test_two_runs_are_identical():
    kw = dict(
        dependency_hubs=["app/x.py"],
        symbol_hubs=["app/x.py"],
        fragile_modules=["app/x.py"],
    )
    a, b = _profile(**kw), _profile(**kw)
    _scan(a)
    _scan(b)
    assert a.confluence_modules == b.confluence_modules


def test_light_mode_absent_families_contribute_nothing():
    # In light mode the git families (churn / co-change) are empty lists; the
    # scan must not pretend they ran. With only hub + symbol-hub populated that
    # is 2 families -> no confluence claimed.
    profile = _profile(
        dependency_hubs=["app/y.py"],
        symbol_hubs=["app/y.py"],
        churn_hotspots=[],
        change_coupling=[],
    )
    _scan(profile)
    assert profile.confluence_modules == []


def test_security_is_a_supporting_family_not_the_headline():
    profile = _profile(
        security_finding_modules=["app/auth.py"],
        dependency_hubs=["app/auth.py"],
        symbol_hubs=["app/auth.py"],
    )
    _scan(profile)
    assert profile.confluence_modules[0]["family_count"] == 3
    assert "security" in profile.confluence_modules[0]["families"]


def test_co_change_counts_both_pair_endpoints():
    profile = _profile(
        change_coupling=[{"a": "app/p.py", "b": "app/q.py", "commits": 7}],
        dependency_hubs=["app/p.py"],
        symbol_hubs=["app/p.py"],
    )
    _scan(profile)
    assert profile.confluence_modules[0]["module"] == "app/p.py"
    assert "co-change" in profile.confluence_modules[0]["families"]


def test_field_is_additive_default_empty():
    # A bare profile carries the new field with no effect on existing fields.
    profile = _profile()
    assert profile.confluence_modules == []
    assert profile.dependency_hubs == []


# --------------------------------------------------------------------------- #
# IdeaSeeder — confluence becomes a grounded root idea.
# --------------------------------------------------------------------------- #

def _confluence_profile() -> ProjectProfile:
    return _profile(
        confluence_modules=[{
            "module": "app/engine/objective_compiler.py",
            "family_count": 4,
            "families": ("complex-function", "high-churn", "hub", "symbol-hub"),
        }],
        ci_files=["ci.yml"],
    )


def test_seeds_a_confluence_root():
    roots = IdeaSeeder().seed(_confluence_profile())
    conv = [r for r in roots if r.source_facts and r.source_facts[0].startswith("confluence:")]
    assert len(conv) == 1
    idea = conv[0]
    assert idea.subject == "app/engine/objective_compiler.py"
    assert idea.operator == "root"
    assert idea.depth == 0
    assert "4 independent pressures converge" in idea.title
    # All families listed, security never the headline (it is not even present
    # here, and the title leads with the convergence).
    assert "complex-function" in idea.title and "symbol-hub" in idea.title
    assert idea.title.lower().startswith("untangle")


def test_no_confluence_when_max_two_families():
    # End-to-end: a profile whose modules top out at 2 families yields no
    # confluence idea.
    profile = _profile(dependency_hubs=["app/cli.py"], symbol_hubs=["app/cli.py"],
                       ci_files=["ci.yml"])
    roots = IdeaSeeder().seed(profile)
    assert not any(
        r.source_facts and r.source_facts[0].startswith("confluence:") for r in roots
    )


def test_confluence_dedups_against_hub_untested():
    # The same module is both a confluence and hub-untested; the confluence
    # claims it first, so it is seeded exactly once.
    profile = _profile(
        confluence_modules=[{
            "module": "app/m.py", "family_count": 3,
            "families": ("hub", "symbol-hub", "untested"),
        }],
        hub_untested_modules=[{"module": "app/m.py", "fan_in": 8}],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    for_module = [r for r in roots if r.subject == "app/m.py"]
    assert len(for_module) == 1
    assert for_module[0].source_facts[0].startswith("confluence:")


def test_invariants_value_feasibility_novelty_in_unit_interval():
    roots = IdeaSeeder().seed(_confluence_profile())
    for r in roots:
        assert 0.0 <= r.value <= 1.0
        assert 0.0 <= r.feasibility <= 1.0
        assert 0.0 <= r.novelty <= 1.0
        if r.depth == 0:
            assert r.novelty == 1.0


def test_seed_is_deterministic():
    a = IdeaSeeder().seed(_confluence_profile())
    b = IdeaSeeder().seed(_confluence_profile())
    assert [(r.subject, r.title, tuple(r.source_facts)) for r in a] == \
           [(r.subject, r.title, tuple(r.source_facts)) for r in b]


# --------------------------------------------------------------------------- #
# Wiring: fact hint, roadmap phase/impact, action bridge.
# --------------------------------------------------------------------------- #

def test_fact_hint_registered():
    assert "confluence" in _FACT_HINTS
    assert _FACT_HINTS["confluence"]
    assert "confluence" in _SECURITY_LABELS


def test_roadmap_ranks_confluence_high_impact_stabilize():
    assert "confluence" in _HIGH_IMPACT_LABELS
    assert "confluence" in _STABILIZE_LABELS
    idea = IdeaSeeder().seed(_confluence_profile())[0]
    assert idea.source_facts[0].startswith("confluence:")
    assert classify_phase(idea) == STABILIZE
    impact = estimate_impact(idea)
    assert 0.0 <= impact <= 1.0
    # The high-impact-label boost lifts it clearly above the 0.35 base.
    assert impact >= 0.6


def test_action_strengthen_tests_when_not_untested():
    # W98: a TESTED confluence flipped from recommend-only design_task to the
    # delegated strengthen_tests lander (mutant-killing assertions before
    # changing the module; the decoupling design stays a disclosed human
    # remainder, and the lander's apply-time gate keeps the claim honest).
    idea = IdeaSeeder().seed(_confluence_profile())[0]
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "strengthen_tests"
    assert step.executable is True


def test_action_creates_test_stub_when_untested():
    profile = _profile(
        confluence_modules=[{
            "module": "app/u.py", "family_count": 3,
            "families": ("hub", "symbol-hub", "untested"),
        }],
        ci_files=["ci.yml"],
    )
    idea = IdeaSeeder().seed(profile)[0]
    assert "untested" in idea.source_facts[0]
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.target == "app/u.py"
    assert step.executable is True
