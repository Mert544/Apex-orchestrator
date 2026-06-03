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


def test_seeds_partial_coverage_distinct_from_untested():
    profile = _profile(
        module_to_tests={"app/a.py": ["t1"], "app/b.py": []},
        untested_modules=["app/b.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    facts = [f for r in roots for f in r.source_facts]
    # a.py has 1 test -> partial-coverage; b.py has 0 -> untested (different idea)
    assert any(f.startswith("partial-coverage: app/a.py") for f in facts)


def test_seeds_extension_and_directory_signals():
    profile = _profile(
        extension_counts={".py": 12},
        top_directories=["app"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    facts = [f for r in roots for f in r.source_facts]
    assert any(f.startswith("extension-py:") for f in facts)
    assert any(f.startswith("top-directory:") for f in facts)


def test_seeds_fragile_modules_first():
    profile = _profile(
        fragile_modules=["app/core.py"],
        dependency_hubs=["app/core.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    facts = [f for r in roots for f in r.source_facts]
    assert any(f.startswith("fragile: app/core.py") for f in facts)
    # Fragility is highest priority -> dedup keeps it over the hub rule.
    frag = next(r for r in roots if r.source_facts[0].startswith("fragile:"))
    assert "Reduce fragility" in frag.title


def test_seeds_modernization_idea():
    from app.engine.idea_permutation import IdeaSeeder
    from app.tools.project_profile import ProjectProfile

    profile = ProjectProfile(root="/x", modernizable_modules=["app/legacy.py"])
    roots = IdeaSeeder().seed(profile)
    mod = [r for r in roots if r.source_facts and r.source_facts[0].startswith("modernization")]
    assert mod, "expected a modernization root idea"
    assert "Modernize comparisons in app/legacy.py" == mod[0].title


def test_modernization_idea_maps_to_executable_action():
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_permutation import IdeaSeeder
    from app.tools.project_profile import ProjectProfile

    profile = ProjectProfile(root="/x", modernizable_modules=["app/legacy.py"])
    idea = next(r for r in IdeaSeeder().seed(profile)
                if r.source_facts and r.source_facts[0].startswith("modernization"))
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "modernize_comparisons"
    assert step.executable is True
    assert step.target == "app/legacy.py"
