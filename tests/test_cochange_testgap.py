"""Co-change test-gap seeding-signal tests.

A co-change test-gap is a module PAIR that frequently changes together (from
git co-change, ``ProjectProfile.change_coupling``) yet NO single test file
exercises BOTH — a change to one can silently break the other with nothing to
catch it. Mirrors the hub-untested / confluence signals end-to-end: profile
field -> scan -> seeded root -> fact hint -> action.

The signal reuses ``change_coupling`` (git-only, EMPTY under ``light=True``)
and the linker's ``module_to_tests``, so it adds no new scan and yields nothing
in light mode — exactly like confluence.
"""

from app.engine.idea_action_bridge import IdeaActionBridge, _FACT_ACTIONS
from app.engine.idea_permutation import _FACT_HINTS
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _scan(profile: ProjectProfile) -> ProjectProfile:
    # The scan reads only profile fields, so it needs no filesystem root.
    profiler = ProjectProfiler.__new__(ProjectProfiler)
    profiler._scan_cochange_test_gaps(profile)
    return profile


# --------------------------------------------------------------------------- #
# _scan_cochange_test_gaps — a co-change PAIR with no shared test is a gap.
# --------------------------------------------------------------------------- #

def test_pair_without_shared_test_is_a_gap():
    profile = _profile(
        change_coupling=[{"a": "app/p.py", "b": "app/q.py", "commits": 7}],
        module_to_tests={
            "app/p.py": ["tests/test_p.py"],
            "app/q.py": ["tests/test_q.py"],  # disjoint test sets -> no shared test
        },
    )
    _scan(profile)
    assert profile.cochange_test_gaps == [
        {"a": "app/p.py", "b": "app/q.py", "cochanges": 7}
    ]


def test_pair_with_shared_test_yields_nothing():
    # A single test references BOTH modules -> the gap is already covered.
    profile = _profile(
        change_coupling=[{"a": "app/r.py", "b": "app/s.py", "commits": 9}],
        module_to_tests={
            "app/r.py": ["tests/test_shared.py"],
            "app/s.py": ["tests/test_shared.py"],
        },
    )
    _scan(profile)
    assert profile.cochange_test_gaps == []


def test_pair_with_no_tests_at_all_is_still_a_gap():
    # Neither module has linked tests; their (empty) test sets do not intersect,
    # so the co-change pair is correctly a gap.
    profile = _profile(
        change_coupling=[{"a": "app/u.py", "b": "app/v.py", "commits": 4}],
        module_to_tests={},
    )
    _scan(profile)
    assert profile.cochange_test_gaps == [
        {"a": "app/u.py", "b": "app/v.py", "cochanges": 4}
    ]


def test_deterministic_ordering_cochanges_desc_then_pair_asc():
    profile = _profile(
        change_coupling=[
            {"a": "app/b.py", "b": "app/c.py", "commits": 2},
            {"a": "app/a.py", "b": "app/z.py", "commits": 5},
            {"a": "app/a.py", "b": "app/c.py", "commits": 5},  # ties at 5
        ],
        module_to_tests={},
    )
    _scan(profile)
    pairs = [(g["a"], g["b"]) for g in profile.cochange_test_gaps]
    # 5 before 2 (cochanges desc); within 5, ("a","c") before ("a","z") (pair asc).
    assert pairs == [("app/a.py", "app/c.py"), ("app/a.py", "app/z.py"),
                     ("app/b.py", "app/c.py")]


def test_capped_at_five():
    profile = _profile(
        change_coupling=[
            {"a": f"app/m{i}.py", "b": f"app/n{i}.py", "commits": 10 - i}
            for i in range(8)
        ],
        module_to_tests={},
    )
    _scan(profile)
    assert len(profile.cochange_test_gaps) == 5


def test_skipped_paths_are_excluded():
    # A canonical skip-dir path (reusing ``is_skipped``) is never a gap subject.
    profile = _profile(
        change_coupling=[
            {"a": ".venv/lib/x.py", "b": "app/q.py", "commits": 6},
            {"a": "app/p.py", "b": "app/q.py", "commits": 3},
        ],
        module_to_tests={},
    )
    _scan(profile)
    pairs = [(g["a"], g["b"]) for g in profile.cochange_test_gaps]
    assert pairs == [("app/p.py", "app/q.py")]


def test_light_mode_yields_nothing():
    # In light mode the git-only ``change_coupling`` family is an empty list;
    # the scan must claim no gaps.
    profile = _profile(
        change_coupling=[],
        module_to_tests={"app/p.py": ["tests/test_p.py"]},
    )
    _scan(profile)
    assert profile.cochange_test_gaps == []


def test_field_is_additive_default_empty():
    # A bare profile carries the new field with no effect on existing fields.
    profile = _profile()
    assert profile.cochange_test_gaps == []
    assert profile.change_coupling == []


def test_two_runs_are_identical():
    kw = dict(
        change_coupling=[{"a": "app/p.py", "b": "app/q.py", "commits": 7}],
        module_to_tests={},
    )
    a, b = _profile(**kw), _profile(**kw)
    _scan(a)
    _scan(b)
    assert a.cochange_test_gaps == b.cochange_test_gaps


# --------------------------------------------------------------------------- #
# IdeaSeeder — a co-change test-gap becomes a grounded development root.
# --------------------------------------------------------------------------- #

def _gap_profile() -> ProjectProfile:
    return _profile(
        cochange_test_gaps=[{"a": "app/p.py", "b": "app/q.py", "cochanges": 7}],
        ci_files=["ci.yml"],
    )


def test_seeds_a_cochange_testgap_root():
    roots = IdeaSeeder().seed(_gap_profile())
    gaps = [
        r for r in roots
        if r.source_facts and r.source_facts[0].startswith("cochange-testgap:")
    ]
    assert len(gaps) == 1
    idea = gaps[0]
    assert idea.subject == "app/p.py + app/q.py"
    assert idea.operator == "root"
    assert idea.depth == 0
    # Framed as a DEVELOPMENT move: add a joint test.
    assert idea.title.lower().startswith("add a test")
    assert "app/p.py" in idea.title and "app/q.py" in idea.title
    assert "together" in idea.title
    # The fact carries the concrete co-change count.
    assert "co-change 7x" in idea.source_facts[0]


def test_no_gap_yields_no_root():
    profile = _profile(cochange_test_gaps=[], ci_files=["ci.yml"])
    roots = IdeaSeeder().seed(profile)
    assert not any(
        r.source_facts and r.source_facts[0].startswith("cochange-testgap:")
        for r in roots
    )


def test_light_mode_seeds_no_cochange_testgap_root():
    # No git family -> no profile gaps -> no root, even though tests are linked.
    profile = _profile(
        cochange_test_gaps=[],
        module_to_tests={"app/p.py": ["tests/test_p.py"]},
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    assert not any(
        r.source_facts and r.source_facts[0].startswith("cochange-testgap:")
        for r in roots
    )


def test_pair_subject_never_collides_with_single_module_signals():
    # The PAIR subject ("a + b") is distinct from any single-module subject, so
    # a hub-untested root on app/p.py and a co-change gap on the (p, q) pair are
    # BOTH seeded — the dedup chokepoint keys on subject, and they differ.
    profile = _profile(
        cochange_test_gaps=[{"a": "app/p.py", "b": "app/q.py", "cochanges": 7}],
        hub_untested_modules=[{"module": "app/p.py", "fan_in": 8}],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    labels = {
        r.source_facts[0].split(":")[0] for r in roots if r.source_facts
    }
    assert "cochange-testgap" in labels
    assert "hub-untested" in labels
    pair_roots = [r for r in roots if r.subject == "app/p.py + app/q.py"]
    assert len(pair_roots) == 1


def test_dedup_seeds_each_pair_subject_once():
    # Two profile entries that collapse to the same PAIR subject seed one root.
    profile = _profile(
        cochange_test_gaps=[
            {"a": "app/p.py", "b": "app/q.py", "cochanges": 7},
            {"a": "app/p.py", "b": "app/q.py", "cochanges": 3},
        ],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    pair_roots = [r for r in roots if r.subject == "app/p.py + app/q.py"]
    assert len(pair_roots) == 1


def test_invariants_value_feasibility_novelty_in_unit_interval():
    roots = IdeaSeeder().seed(_gap_profile())
    for r in roots:
        assert 0.0 <= r.value <= 1.0
        assert 0.0 <= r.feasibility <= 1.0
        assert 0.0 <= r.novelty <= 1.0
        if r.depth == 0:
            assert r.novelty == 1.0


def test_seed_is_deterministic():
    a = IdeaSeeder().seed(_gap_profile())
    b = IdeaSeeder().seed(_gap_profile())
    assert [(r.subject, r.title, tuple(r.source_facts)) for r in a] == \
           [(r.subject, r.title, tuple(r.source_facts)) for r in b]


# --------------------------------------------------------------------------- #
# Wiring: fact hint and action bridge.
# --------------------------------------------------------------------------- #

def test_fact_hint_registered():
    assert "cochange-testgap" in _FACT_HINTS
    assert _FACT_HINTS["cochange-testgap"]
    # A test-oriented hint (it is a test gap).
    assert "test" in _FACT_HINTS["cochange-testgap"]


def test_fact_action_routes_to_create_test_stub():
    assert "cochange-testgap" in _FACT_ACTIONS
    action_type, _desc, executable = _FACT_ACTIONS["cochange-testgap"]
    assert action_type == "create_test_stub"
    assert executable is True


def test_action_bridge_plans_a_test_stub():
    idea = IdeaSeeder().seed(_gap_profile())[0]
    assert idea.source_facts[0].startswith("cochange-testgap:")
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert 0.0 <= step.value <= 1.0
