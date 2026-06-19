"""Coverage-gradient exposure signal + its threshold-gated seed family.

A module is dangerous to change in proportion to fan-in x thin-coverage x churn;
the analysis (``app.engine.exposure_gradient``) ranks those, and the seeder
exposes them as an ADDITIVE, threshold-gated ``exposure:`` seed family that
leaves default seeding byte-identical when the signal doesn't fire.
"""

from app.engine.exposure_gradient import (
    COVERAGE_DEPTH,
    _norm,
    exposure_gradient,
    render_exposure_gradient_markdown,
)
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


# -- the analysis -----------------------------------------------------------

def test_hub_untested_churned_ranks_first_above_a_leaf():
    # ``hub`` is a high fan-in, untested, heavily-churned module; ``leaf`` has
    # some churn but no fan-in (nothing depends on it). The hub must rank #1.
    profile = _profile(
        module_fanin={"app/hub.py": 20, "app/leaf.py": 0},
        untested_modules=["app/hub.py"],
        churn_hotspots=[
            {"module": "app/hub.py", "commits": 15},
            {"module": "app/leaf.py", "commits": 15},
        ],
        module_to_tests={"app/leaf.py": ["tests/test_leaf.py"]},
    )
    leads = exposure_gradient(profile)
    assert leads, "the hub should produce an exposure lead"
    assert leads[0]["module"] == "app/hub.py"
    top = leads[0]
    assert top["fanin"] == 20
    assert top["coverage"] == "none"
    assert top["churn"] == 15
    assert 0.0 < top["exposure"] <= 1.0
    # The leaf has zero fan-in -> its exposure product is 0 -> it drops out.
    assert all(lead["module"] != "app/leaf.py" for lead in leads)


def test_well_covered_hub_has_zero_exposure():
    # A churned hub that is function-covered is NOT dangerous: (1 - depth) = 0.
    profile = _profile(
        module_fanin={"app/safe.py": 30},
        churn_hotspots=[{"module": "app/safe.py", "commits": 40}],
        module_to_tests={"app/safe.py": ["tests/test_safe.py"]},
    )
    assert exposure_gradient(profile) == []


def test_empty_and_all_leaf_project_yields_no_exposure():
    assert exposure_gradient(_profile()) == []
    # All-leaf: fan-in present but zero, no churn -> no candidate trips.
    leafy = _profile(module_fanin={"app/x.py": 0, "app/y.py": 0})
    assert exposure_gradient(leafy) == []


def test_determinism_across_two_runs():
    profile = _profile(
        module_fanin={"app/a.py": 10, "app/b.py": 10, "app/c.py": 4},
        untested_modules=["app/a.py", "app/b.py"],
        shallow_tested_modules=["app/c.py"],
        churn_hotspots=[
            {"module": "app/a.py", "commits": 9},
            {"module": "app/b.py", "commits": 9},
            {"module": "app/c.py", "commits": 9},
        ],
    )
    first = exposure_gradient(profile)
    second = exposure_gradient(profile)
    assert first == second
    # Tie on (fanin, coverage, churn) between a.py and b.py -> sorted by module.
    assert [lead["module"] for lead in first[:2]] == ["app/a.py", "app/b.py"]


def test_normalize_div_by_zero_guard():
    # peak <= 0 must return 0.0, never raise.
    assert _norm(0, 0) == 0.0
    assert _norm(5, 0) == 0.0
    assert _norm(5, 10) == 0.5
    # End-to-end: every churn is 0 -> churn axis peak 0 -> all exposures 0.
    profile = _profile(
        module_fanin={"app/hub.py": 9},
        untested_modules=["app/hub.py"],
        churn_hotspots=[{"module": "app/hub.py", "commits": 0}],
    )
    assert exposure_gradient(profile) == []


def test_coverage_depth_mapping_and_top_cap():
    assert COVERAGE_DEPTH == {"none": 0.0, "module": 0.5, "function": 1.0}
    profile = _profile(
        module_fanin={f"app/m{i}.py": 10 for i in range(5)},
        untested_modules=[f"app/m{i}.py" for i in range(5)],
        churn_hotspots=[{"module": f"app/m{i}.py", "commits": 8} for i in range(5)],
    )
    assert len(exposure_gradient(profile, top=2)) == 2


def test_render_markdown_empty_and_populated():
    assert "No exposed modules" in render_exposure_gradient_markdown([])
    leads = [{"module": "app/h.py", "exposure": 0.5, "fanin": 9,
              "coverage": "none", "churn": 7, "why": "x"}]
    md = render_exposure_gradient_markdown(leads)
    assert "app/h.py" in md and "0.5000" in md


# -- the seed family --------------------------------------------------------

def _exposed_profile() -> ProjectProfile:
    return _profile(
        module_fanin={"app/hub.py": 20},
        untested_modules=["app/hub.py"],
        churn_hotspots=[{"module": "app/hub.py", "commits": 15}],
        ci_files=["ci.yml"],
    )


def test_exposure_seed_family_fires_above_threshold():
    roots = IdeaSeeder().seed(_exposed_profile())
    exposure_roots = [r for r in roots
                      if r.source_facts and r.source_facts[0].startswith("exposure-gradient:")]
    assert len(exposure_roots) == 1
    root = exposure_roots[0]
    # Quantified clause: "module X: fan-in N, coverage none, churn rising".
    assert "fan-in 20" in root.source_facts[0]
    assert "coverage none" in root.source_facts[0]
    assert "churn rising" in root.source_facts[0]
    # Suffixed subject so it never collides with another family's module.
    assert root.subject == "app/hub.py::exposure"


def test_default_seeding_is_byte_identical_below_threshold():
    # A profile that names a hub + churn but the module is COVERED -> exposure 0
    # -> no exposure seed -> seeded set byte-identical to the same profile run
    # without the exposure family ever being reachable.
    profile = _profile(
        dependency_hubs=["app/a.py"],
        module_fanin={"app/a.py": 20},
        churn_hotspots=[{"module": "app/a.py", "commits": 15}],
        module_to_tests={"app/a.py": ["tests/test_a.py"]},
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    assert all(not (r.source_facts and r.source_facts[0].startswith("exposure-gradient:"))
               for r in roots)


def test_all_leaf_project_seeds_no_exposure_and_is_unchanged():
    # No fan-in / churn at all: the exposure family appends nothing, so the
    # output is exactly the lone CI idea the empty profile produces.
    roots = IdeaSeeder().seed(_profile())
    assert len(roots) == 1
    assert roots[0].subject == "CI pipeline"
    assert all(not (r.source_facts and r.source_facts[0].startswith("exposure-gradient:"))
               for r in roots)


def test_exposure_seed_is_additive_and_last():
    # The exposure root must be APPENDED after the budgeted families: removing
    # it leaves every prior root byte-identical (same order, same content).
    roots = IdeaSeeder().seed(_exposed_profile())
    non_exposure = [r for r in roots
                    if not (r.source_facts and r.source_facts[0].startswith("exposure-gradient:"))]
    # The exposure root is the very last one (additive tail).
    assert roots[-1].source_facts[0].startswith("exposure-gradient:")
    assert non_exposure == roots[:-1]


def test_seed_family_determinism():
    a = IdeaSeeder().seed(_exposed_profile())
    b = IdeaSeeder().seed(_exposed_profile())
    assert [(r.subject, r.title, tuple(r.source_facts)) for r in a] == \
           [(r.subject, r.title, tuple(r.source_facts)) for r in b]
