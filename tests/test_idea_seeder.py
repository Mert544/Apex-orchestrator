from app.engine.idea_permutation import DEVELOPMENT_OPERATORS, IdeaSeeder, Operator
from app.models.idea import IdeaNode, IdeaTreeReport
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def test_seeds_roots_from_dependency_hubs():
    profile = _profile(dependency_hubs=["app/routes/api.py"], ci_files=["ci.yml"])
    roots = IdeaSeeder().seed(profile)
    assert any(r.subject == "app/routes/api.py" for r in roots)
    hub = next(r for r in roots if r.subject == "app/routes/api.py")
    assert hub.depth == 0
    assert hub.operator == "root"
    assert hub.branch_path.startswith("x.")
    # Every idea is traceable to a concrete fact.
    assert any("dependency-hub" in f for f in hub.source_facts)


def test_seeds_cover_multiple_fact_types():
    profile = _profile(
        dependency_hubs=["app/a.py"],
        sensitive_paths=["app/auth.py"],
        critical_untested_modules=["app/pay.py"],
        entrypoints=["app/main.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    subjects = {r.subject for r in roots}
    assert {"app/a.py", "app/auth.py", "app/pay.py", "app/main.py"} <= subjects
    # All roots carry a traceable fact and a unique branch path.
    assert all(r.source_facts for r in roots)
    assert len({r.branch_path for r in roots}) == len(roots)


def test_missing_ci_becomes_a_root_idea():
    profile = _profile(dependency_hubs=["app/a.py"], ci_files=[])
    roots = IdeaSeeder().seed(profile)
    assert any("CI" in r.title or "continuous-integration" in r.title for r in roots)


def test_respects_per_category_limit_and_dedup():
    profile = _profile(
        dependency_hubs=["m1", "m2", "m3", "m4", "m5"],  # limit 3
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    hub_subjects = [r.subject for r in roots if "dependency-hub" in r.source_facts[0]]
    assert len(hub_subjects) == 3


def test_empty_profile_yields_only_ci_idea():
    roots = IdeaSeeder().seed(_profile())  # no facts, no ci
    assert len(roots) == 1
    assert roots[0].subject == "CI pipeline"


def test_operator_alphabet_is_well_formed():
    assert len(DEVELOPMENT_OPERATORS) >= 6
    assert all(isinstance(op, Operator) for op in DEVELOPMENT_OPERATORS)
    assert all("{x}" in op.template for op in DEVELOPMENT_OPERATORS)
    assert all(0.0 <= op.feasibility <= 1.0 for op in DEVELOPMENT_OPERATORS)
    # Names are unique.
    assert len({op.name for op in DEVELOPMENT_OPERATORS}) == len(DEVELOPMENT_OPERATORS)


def test_idea_tree_report_helpers():
    a = IdeaNode(id="idea-0", title="root", depth=0)
    b = IdeaNode(id="idea-1", title="child", depth=1, parent_id="idea-0")
    report = IdeaTreeReport(ideas=[a, b])
    assert report.roots() == [a]
    assert report.children_of("idea-0") == [b]
