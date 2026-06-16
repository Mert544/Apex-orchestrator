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


def test_coverage_depth_is_substance_based_not_file_count():
    # A module with one test (app/a.py) is not nagged by a crude file-count
    # heuristic; only genuinely untested code is seeded. Coverage DEPTH is now
    # the substance-based shallow-coverage signal, not "1 test file = thin".
    profile = _profile(
        module_to_tests={"app/a.py": ["t1"], "app/b.py": []},
        untested_modules=["app/b.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    facts = [f for r in roots for f in r.source_facts]
    assert not any(f.startswith("partial-coverage") for f in facts)
    assert not any(f.startswith("untested: app/a.py") for f in facts)


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


def test_seeds_debt_marker_modules():
    profile = _profile(
        debt_marker_modules=["app/legacy.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    facts = [f for r in roots for f in r.source_facts]
    assert any(f.startswith("debt-markers: app/legacy.py") for f in facts)
    debt = next(r for r in roots if r.source_facts[0].startswith("debt-markers:"))
    assert debt.subject == "app/legacy.py"
    assert "debt markers" in debt.title


def test_no_debt_root_when_no_marker_modules():
    profile = _profile(dependency_hubs=["app/a.py"], ci_files=["ci.yml"])
    roots = IdeaSeeder().seed(profile)
    facts = [f for r in roots for f in r.source_facts]
    assert not any(f.startswith("debt-markers:") for f in facts)


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


def test_seeds_mutable_default_idea_and_maps_to_action():
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_permutation import IdeaSeeder
    from app.tools.project_profile import ProjectProfile

    profile = ProjectProfile(root="/x", mutable_default_modules=["app/svc.py"])
    idea = next(r for r in IdeaSeeder().seed(profile)
                if r.source_facts and r.source_facts[0].startswith("mutable-default"))
    assert "Fix mutable default arguments in app/svc.py" == idea.title
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "fix_mutable_defaults" and step.executable is True


def test_seeds_complexity_hotspot_idea(tmp_path):
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder
    profile = ProjectProfile(root=str(tmp_path), hotspot_modules=["app/hot.py"])
    roots = IdeaSeeder().seed(profile)
    hot = [r for r in roots if any("complexity-hotspot" in f for f in r.source_facts)]
    assert hot and any("app/hot.py" in r.subject for r in hot)


def test_seeds_deepen_shallow_coverage_idea(tmp_path):
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder
    profile = ProjectProfile(root=str(tmp_path), shallow_tested_modules=["pkg/shallow.py"])
    roots = IdeaSeeder().seed(profile)
    sc = [r for r in roots if any("shallow-coverage" in f for f in r.source_facts)]
    assert sc and any("pkg/shallow.py" in r.subject for r in sc)


def test_seeds_hotspot_function_idea_with_symbol_caveat(tmp_path):
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder, IdeaPermutationEngine

    profile = ProjectProfile(
        root=str(tmp_path),
        hotspot_functions=[{"module": "app/core.py", "function": "Engine.crunch",
                            "line": 40, "complexity": 14}],
    )
    roots = IdeaSeeder().seed(profile)
    hot = [r for r in roots if any(f.startswith("hotspot-function:") for f in r.source_facts)]
    assert hot
    root = hot[0]
    assert root.subject == "app/core.py::Engine.crunch"     # symbol-granular subject
    assert "crunch()" in root.title and "complexity 14" in root.title

    # Scoring attaches a caveat that names the actual function, not a template.
    from app.skills.relevance_scorer import RelevanceScorer
    engine = IdeaPermutationEngine(config={}, project_root=str(tmp_path))
    engine._score(root, RelevanceScorer(objective=""))
    assert root.caveats and "crunch()" in root.caveats[0]


def test_seeds_security_finding_module():
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder
    profile = ProjectProfile(root=".", security_finding_modules=["app/report.py"])
    roots = IdeaSeeder().seed(profile)
    sf = [r for r in roots if r.source_facts and r.source_facts[0].startswith("security-finding:")]
    assert sf and sf[0].subject == "app/report.py"


def test_security_finding_maps_to_executable_harden():
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Fix the security findings in app/report.py",
                    subject="app/report.py", operator="root",
                    source_facts=["security-finding: app/report.py (eval/... detected)"])
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "harden_security" and step.executable is True


def test_correctness_bug_seeds_and_claims_subject_over_untested():
    # A module that is BOTH untested and has a crash bug is framed by the more
    # urgent crash bug, not "untested" — the high-severity signal claims it.
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder
    profile = ProjectProfile(
        root=".",
        correctness_bug_modules=["app/buggy.py"],
        untested_modules=["app/buggy.py"],
    )
    roots = IdeaSeeder().seed(profile)
    buggy = [r for r in roots if r.subject == "app/buggy.py"]
    assert len(buggy) == 1
    assert buggy[0].source_facts[0].startswith("correctness-bug:")


def test_correctness_bug_maps_to_executable_harden():
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Fix the likely crash/logic bug in app/b.py",
                    subject="app/b.py", operator="root",
                    source_facts=["correctness-bug: app/b.py (high-severity logic bug detected)"])
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "harden_security" and step.executable is True


def test_seeds_churn_hotspot_idea():
    profile = _profile(
        churn_hotspots=[{"module": "app/busy.py", "commits": 7}],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    churn = next(r for r in roots if r.subject == "app/busy.py")
    assert "7 recent commits" in churn.title
    assert any(f.startswith("churn-hotspot:") for f in churn.source_facts)


def test_churn_hotspot_routes_to_evolve_phase():
    from app.engine.idea_roadmap import EVOLVE, classify_phase
    profile = _profile(
        churn_hotspots=[{"module": "app/busy.py", "commits": 5}],
        ci_files=["ci.yml"],
    )
    churn = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/busy.py")
    assert classify_phase(churn) == EVOLVE


def test_stale_debt_markers_narrate_their_age():
    profile = _profile(
        debt_marker_modules=["app/old.py"],
        debt_marker_ages={"app/old.py": 400},
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/old.py")
    assert "waited 13 months" in root.title
    assert "oldest ~13 months old" in root.source_facts[0]


def test_fresh_debt_markers_keep_plain_title():
    profile = _profile(
        debt_marker_modules=["app/new.py"],
        debt_marker_ages={"app/new.py": 30},  # < 90 days -> no age claim
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/new.py")
    assert root.title == "Address the TODO/FIXME debt markers in app/new.py"


def test_old_security_finding_narrates_exposure_window():
    profile = _profile(
        security_finding_modules=["app/danger.py"],
        security_finding_ages={"app/danger.py": 430},
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/danger.py")
    assert "exposed for ~14 months" in root.title
    assert "in the code ~14 months" in root.source_facts[0]


def test_fresh_security_finding_keeps_plain_title():
    profile = _profile(
        security_finding_modules=["app/danger.py"],
        security_finding_ages={"app/danger.py": 20},
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/danger.py")
    assert root.title == "Fix the security findings in app/danger.py"


def test_doc_drift_seeds_one_root_per_doc():
    profile = _profile(
        doc_drift=[
            {"doc": "README.md", "reference": "app/a.py", "line": 3},
            {"doc": "README.md", "reference": "app/b.py", "line": 9},
            {"doc": "docs/guide.md", "reference": "app/c.py", "line": 1},
        ],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    readme = next(r for r in roots if r.subject == "README.md")
    assert "references `app/a.py`, which doesn't exist (+1 more)" in readme.title
    assert readme.source_facts[0].startswith("doc-drift:")
    guide = next(r for r in roots if r.subject == "docs/guide.md")
    assert "(+0 more)" not in guide.title and "+1 more" not in guide.title


def test_doc_drift_routes_to_refine_phase():
    from app.engine.idea_roadmap import REFINE, classify_phase

    profile = _profile(
        doc_drift=[{"doc": "README.md", "reference": "app/a.py", "line": 3}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "README.md")
    assert classify_phase(root) == REFINE


def test_knowledge_risk_seeds_and_routes_to_stabilize():
    from app.engine.idea_roadmap import STABILIZE, classify_phase

    profile = _profile(
        knowledge_risks=[{"module": "app/owned.py", "share": 94, "commits": 17}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/owned.py")
    assert "94% of its recent changes come from one author" in root.title
    assert root.source_facts == ["knowledge-risk: app/owned.py (94% single-author across 17 commits)"]
    assert classify_phase(root) == STABILIZE


def test_knowledge_risk_share_drives_the_magnitude_bonus():
    from app.engine.idea_permutation import _magnitude_bonus
    from app.models.idea import IdeaNode

    def _root(share):
        return IdeaNode(id="i", title="t", subject="s", operator="root",
                        operator_chain=["root"],
                        source_facts=[f"knowledge-risk: m ({share}% single-author across 9 commits)"])

    assert _magnitude_bonus(_root(100)) == 0.08   # saturated
    assert 0 < _magnitude_bonus(_root(86)) < 0.08


def test_dead_parameter_seeds_root_with_drop_command():
    profile = _profile(
        dead_params=[{"module": "app/core.py", "function": "render",
                      "param": "color", "line": 12}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/core.py")
    assert root.title == "Drop the dead parameter `color` from render() in app/core.py"
    assert root.source_facts[0].startswith("dead-parameter:")
    # The hands already exist — the fact hands you the exact command.
    assert "apex signature drop render color" in root.source_facts[0]


def test_dead_parameter_routes_to_refine_phase():
    from app.engine.idea_roadmap import REFINE, classify_phase

    profile = _profile(
        dead_params=[{"module": "app/core.py", "function": "render",
                      "param": "color", "line": 12}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/core.py")
    assert classify_phase(root) == REFINE


def test_extractable_block_seeds_root_with_extract_command():
    profile = _profile(
        extractable_blocks=[{"module": "app/big.py", "function": "process",
                             "line": 10, "start": 14, "end": 42,
                             "name": "_process_part", "params": ["data", "cfg"],
                             "returns": ["total"], "lines_saved": 29}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/big.py")
    assert "Extract a helper from process()" in root.title
    assert "saves 29 lines" in root.title
    assert root.source_facts[0].startswith("extractable-block:")
    # The fact hands you the exact, runnable command.
    assert "apex extract app/big.py 14 42 _process_part" in root.source_facts[0]
    # And it states the computed interface so the size of the move is visible.
    assert "2 param(s) in, 1 value(s) out" in root.source_facts[0]


def test_extractable_block_routes_to_refine_phase():
    from app.engine.idea_roadmap import REFINE, classify_phase

    profile = _profile(
        extractable_blocks=[{"module": "app/big.py", "function": "process",
                             "line": 10, "start": 14, "end": 42,
                             "name": "_process_part", "params": ["data"],
                             "returns": ["total"], "lines_saved": 29}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/big.py")
    assert classify_phase(root) == REFINE


def test_inlinable_helper_seeds_root_with_inline_command():
    profile = _profile(
        inlinable_helpers=[{"module": "app/calc.py", "function": "fee",
                            "line": 12, "call_sites": 1}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/calc.py")
    assert "Inline the single-use helper fee() in app/calc.py" in root.title
    assert root.source_facts[0].startswith("inlinable-helper:")
    # The fact hands you the exact, runnable command.
    assert "apex inline fee" in root.source_facts[0]
    assert "app/calc.py:12" in root.source_facts[0]


def test_inlinable_helper_routes_to_refine_phase():
    from app.engine.idea_roadmap import REFINE, classify_phase

    profile = _profile(
        inlinable_helpers=[{"module": "app/calc.py", "function": "fee",
                            "line": 12, "call_sites": 1}],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == "app/calc.py")
    assert classify_phase(root) == REFINE


def test_seeds_impure_untested_function_idea(tmp_path):
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder, IdeaPermutationEngine
    from app.skills.relevance_scorer import RelevanceScorer

    profile = ProjectProfile(
        root=str(tmp_path),
        impure_untested_functions=[{
            "module": "app/io_logic.py", "function": "emit",
            "line": 5, "side_effects": ["global_state", "module:logging"],
        }],
    )
    roots = IdeaSeeder().seed(profile)
    imp = [r for r in roots if any(f.startswith("impure-untested:") for f in r.source_facts)]
    assert imp
    root = imp[0]
    # Symbol-granular subject so it coexists with the module's other ideas.
    assert root.subject == "app/io_logic.py::emit"
    assert "Isolate the side effects of emit()" in root.title
    assert "global_state" in root.source_facts[0] and "module:logging" in root.source_facts[0]
    assert "no direct tests" in root.source_facts[0]

    # The grounded root keeps the invariants: value in [0,1], root novelty 1.0.
    engine = IdeaPermutationEngine(config={}, project_root=str(tmp_path))
    engine._score(root, RelevanceScorer(objective=""))
    assert 0.0 <= root.value <= 1.0
    assert root.novelty == 1.0
    assert root.kind == "permutation"


def test_no_impure_untested_root_when_signal_absent(tmp_path):
    # A profile with a pure/tested-only world surfaces no impure-untested root.
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder

    profile = ProjectProfile(root=str(tmp_path), dependency_hubs=["app/a.py"])
    roots = IdeaSeeder().seed(profile)
    assert not any(
        f.startswith("impure-untested:") for r in roots for f in r.source_facts
    )


def test_impure_untested_routes_to_stabilize_phase():
    from app.engine.idea_roadmap import STABILIZE, classify_phase
    from app.models.idea import IdeaNode

    root = IdeaNode(
        id="i", title="Isolate the side effects of emit() in app/io_logic.py and cover the core with tests",
        subject="app/io_logic.py::emit", operator="root", operator_chain=["root"],
        source_facts=["impure-untested: app/io_logic.py::emit (impure: module:logging, line 5, no direct tests)"],
    )
    # Cover before changing risky code -> Stabilize.
    assert classify_phase(root) == STABILIZE


def test_impure_untested_maps_to_executable_test_stub():
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import IdeaNode

    idea = IdeaNode(
        id="i", title="Isolate the side effects of emit() in app/io_logic.py and cover the core with tests",
        subject="app/io_logic.py::emit", operator="root",
        source_facts=["impure-untested: app/io_logic.py::emit (impure: module:logging, line 5, no direct tests)"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.executable is True
    # Symbol-granular subject acts on the module file.
    assert step.target == "app/io_logic.py"


def test_impure_untested_yields_security_lens_caveat():
    # The label is reliability-relevant, so scoring attaches an on-topic caveat
    # (decouple/isolate side effects) rather than a generic one.
    from app.engine.idea_permutation import _caveat_hint
    from app.models.idea import IdeaNode

    root = IdeaNode(
        id="i", title="Isolate the side effects of emit() in app/io_logic.py and cover the core with tests",
        subject="app/io_logic.py::emit", operator="root", operator_chain=["root"],
        source_facts=["impure-untested: app/io_logic.py::emit (impure: module:logging, line 5, no direct tests)"],
    )
    hint = _caveat_hint(root)
    assert "isolate" in hint and "side effect" in hint


def test_complexity_hotspot_claims_subject_over_impure_untested():
    # A function that is BOTH a complexity hotspot and impure-untested is framed
    # by the more-severe hotspot root (it runs first); the impure root dedups.
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder

    profile = ProjectProfile(
        root=".",
        hotspot_functions=[{"module": "app/m.py", "function": "f",
                            "line": 3, "complexity": 12, "cognitive": 9}],
        impure_untested_functions=[{"module": "app/m.py", "function": "f",
                                    "line": 3, "side_effects": ["module:os"]}],
    )
    roots = IdeaSeeder().seed(profile)
    claims = [r for r in roots if r.subject == "app/m.py::f"]
    assert len(claims) == 1
    assert claims[0].source_facts[0].startswith("hotspot-function:")


def test_seeds_hub_untested_module_idea(tmp_path):
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder, IdeaPermutationEngine
    from app.skills.relevance_scorer import RelevanceScorer

    profile = ProjectProfile(
        root=str(tmp_path),
        hub_untested_modules=[{"module": "app/core.py", "fan_in": 7}],
    )
    roots = IdeaSeeder().seed(profile)
    hub = [r for r in roots if any(f.startswith("hub-untested:") for f in r.source_facts)]
    assert hub
    root = hub[0]
    # Module-granular subject (a hub is a file, not a symbol).
    assert root.subject == "app/core.py"
    assert "Cover the dependency hub app/core.py first" in root.title
    assert "7 modules import it" in root.title
    assert "7 dependents" in root.source_facts[0]
    assert "regression here breaks all 7" in root.source_facts[0]

    # Grounded root keeps the invariants: value in [0,1], root novelty 1.0.
    engine = IdeaPermutationEngine(config={}, project_root=str(tmp_path))
    engine._score(root, RelevanceScorer(objective=""))
    assert 0.0 <= root.value <= 1.0
    assert root.novelty == 1.0
    assert root.kind == "permutation"


def test_no_hub_untested_root_when_signal_absent(tmp_path):
    # A profile without the signal surfaces no hub-untested root.
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder

    profile = ProjectProfile(root=str(tmp_path), dependency_hubs=["app/a.py"])
    roots = IdeaSeeder().seed(profile)
    assert not any(
        f.startswith("hub-untested:") for r in roots for f in r.source_facts
    )


def test_hub_untested_routes_to_stabilize_phase():
    from app.engine.idea_roadmap import STABILIZE, classify_phase
    from app.models.idea import IdeaNode

    root = IdeaNode(
        id="i", title="Cover the dependency hub app/core.py first (7 modules import it, no/shallow tests)",
        subject="app/core.py", operator="root", operator_chain=["root"],
        source_facts=["hub-untested: app/core.py (dependency hub: 7 dependents, untested or shallow — a regression here breaks all 7)"],
    )
    # Cover the hub before changing it -> Stabilize.
    assert classify_phase(root) == STABILIZE


def test_hub_untested_maps_to_executable_test_stub():
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import IdeaNode

    idea = IdeaNode(
        id="i", title="Cover the dependency hub app/core.py first (7 modules import it, no/shallow tests)",
        subject="app/core.py", operator="root",
        source_facts=["hub-untested: app/core.py (dependency hub: 7 dependents, untested or shallow — a regression here breaks all 7)"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.executable is True
    assert step.target == "app/core.py"


def test_hub_untested_yields_reliability_lens_caveat():
    # The label is in _SECURITY_LABELS, so scoring attaches an on-topic caveat
    # (regression net / dependents) rather than a generic one.
    from app.engine.idea_permutation import _caveat_hint
    from app.models.idea import IdeaNode

    root = IdeaNode(
        id="i", title="Cover the dependency hub app/core.py first (7 modules import it, no/shallow tests)",
        subject="app/core.py", operator="root", operator_chain=["root"],
        source_facts=["hub-untested: app/core.py (dependency hub: 7 dependents, untested or shallow — a regression here breaks all 7)"],
    )
    hint = _caveat_hint(root)
    assert "regression net" in hint and "dependents" in hint


def test_fragile_claims_subject_over_hub_untested():
    # A module that is BOTH fragile and a hub-untested is framed by the
    # more-severe fragile root (it runs first); the hub-untested root dedups.
    from app.tools.project_profile import ProjectProfile
    from app.engine.idea_permutation import IdeaSeeder

    profile = ProjectProfile(
        root=".",
        fragile_modules=["app/core.py"],
        hub_untested_modules=[{"module": "app/core.py", "fan_in": 7}],
    )
    roots = IdeaSeeder().seed(profile)
    claims = [r for r in roots if r.subject == "app/core.py"]
    assert len(claims) == 1
    assert claims[0].source_facts[0].startswith("fragile:")


# --- characterization: byte-identical seeded set under the perf optimization ---
#
# These pin the FULL seeded-root list (subject + source_facts + values +
# novelty + title + rationale) for a rich profile that exercises the memoized
# fast paths added for performance: several modules share one
# ``hotspot_functions`` / ``impure_untested_functions`` list (the per-module
# index) and one ``dependency_edges`` list with no precomputed fan-in/out (the
# importers-graph reuse in ``_quantified_clause``). If any optimization changed
# the output, the frozen snapshot below — or the same-input-twice equality —
# would break.

def _rich_profile() -> ProjectProfile:
    return _profile(
        # Shared function lists scanned once per module by the index.
        hotspot_functions=[
            {"module": "app/a.py", "function": "Klass.run", "line": 30,
             "complexity": 14, "cognitive": 9},
            {"module": "app/a.py", "function": "helper", "line": 10,
             "complexity": 7},
            {"module": "app/b.py", "function": "compute", "line": 5,
             "complexity": 11},
        ],
        impure_untested_functions=[
            {"module": "app/c.py", "function": "writer", "line": 12,
             "side_effects": ["fs", "log"]},
        ],
        # One edge list, no precomputed fan-in/out -> the edge fallback fires
        # for every hub/confluence module and reuses the importers graph.
        dependency_edges=[
            ("app/x.py", "app/a.py"),
            ("app/y.py", "app/a.py"),
            ("app/z.py", "app/b.py"),
            ("app/a.py", "app/b.py"),
            ("app/a.py", "app/c.py"),
        ],
        confluence_modules=[
            {"module": "app/a.py", "family_count": 3,
             "families": ("high-churn", "hub", "untested")},
        ],
        fragile_modules=["app/b.py"],
        dependency_hubs=["app/a.py", "app/b.py"],
        hotspot_modules=["app/c.py"],
        hub_untested_modules=[{"module": "app/c.py", "fan_in": 4}],
        ci_files=["ci.yml"],
    )


def _snapshot(roots):
    return [
        (r.id, r.subject, r.title, r.rationale, tuple(r.source_facts),
         r.value, r.novelty, r.depth, r.operator,
         tuple((a["module"], a["symbol"], a["line"], a["metric"]) for a in r.anchors))
        for r in roots
    ]


def test_seeded_set_is_deterministic_across_runs():
    # Same input twice -> byte-identical seeded set (the optimization caches are
    # reset per pass, so a second seed must reproduce the first exactly).
    seeder = IdeaSeeder()
    profile = _rich_profile()
    first = _snapshot(seeder.seed(profile))
    second = _snapshot(seeder.seed(profile))
    assert first == second
    # A fresh seeder / fresh profile object reproduces the same set, too.
    assert _snapshot(IdeaSeeder().seed(_rich_profile())) == first


def test_seeded_set_matches_frozen_characterization():
    roots = IdeaSeeder().seed(_rich_profile())
    snap = _snapshot(roots)

    # Every root keeps the value/novelty root invariants.
    assert all(s[5] == 0.0 and s[6] == 1.0 and s[7] == 0 and s[8] == "root"
               for s in snap)

    # Subjects, in exact seeded order.
    assert [s[1] for s in snap] == [
        "app/a.py",            # confluence (claims the module subject first)
        "app/b.py",            # fragile
        "app/c.py",            # hotspot module / hub-untested (deduped to one)
        "app/a.py::Klass.run",  # symbol-grain hotspot functions (own subjects)
        "app/a.py::helper",
        "app/b.py::compute",
        "app/c.py::writer",     # impure-untested function
    ]

    by_subject = {s[1]: s for s in snap}

    # Confluence root: anchored at app/a.py's two hotspot functions (complexity
    # desc, then line) and quantified off the reused importers graph.
    a = by_subject["app/a.py"]
    assert a[0] == "idea-0"
    assert a[2].startswith("Untangle app/a.py — 3 independent pressures")
    assert a[4] == (
        "confluence: app/a.py (3 signal families converge: high-churn, hub, "
        "untested; untested)",
    )
    assert a[9] == (
        ("app/a.py", "Klass.run", 30, "cyclomatic 14"),
        ("app/a.py", "helper", 10, "cyclomatic 7"),
    )
    # Fan-in (2 importers: x, y) and heaviest fan-out targets named.
    assert "Imported by 2 modules" in a[3]
    assert "heaviest" in a[3]

    # Fragile root: app/b.py anchored at its single hotspot, fan-in quantified
    # (no named targets, name_targets=False).
    b = by_subject["app/b.py"]
    assert b[2].startswith("Reduce fragility")
    assert b[9] == (("app/b.py", "compute", 5, "cyclomatic 11"),)
    assert "Imported by 2 modules" in b[3]   # a and z import b
    assert "heaviest" not in b[3]

    # The c.py module is claimed once (hotspot-module before hub-untested) and
    # anchored at its impure-untested function (the hotspot fallback).
    c = by_subject["app/c.py"]
    assert c[4][0].startswith("complexity-hotspot:")
    assert c[9] == (("app/c.py", "writer", 12, "impure, untested"),)


def _all_families_profile() -> ProjectProfile:
    """A profile that lights up EVERY seeding family at once.

    Pins the full ordered seeded set so the orchestration order across the
    extracted ``_seed_*`` helpers stays byte-identical: subjects, fact labels
    and per-family count are characterized below. (``dream-insight`` is the one
    family that cannot fire here — the seeder is hermetic without an explicit
    ``project_root``, by design — so it is intentionally absent.)
    """
    return _profile(
        extension_counts={".py": 42, ".js": 3},
        top_directories=["app", "tests"],
        entrypoints=["app/main.py", "app/cli.py", "app/extra_entry.py"],
        ci_files=[],  # missing CI -> the CI root fires
        config_files=["settings.toml", "config2.ini"],
        sensitive_paths=["app/auth.py", "app/crypto.py", "app/secrets.py"],
        security_finding_modules=["app/sec1.py", "app/sec2.py", "app/sec3.py"],
        security_finding_ages={"app/sec1.py": 120, "app/sec2.py": 30},
        correctness_bug_modules=["app/bug1.py", "app/bug2.py"],
        dependency_hubs=["app/a.py", "app/b.py", "app/hub3.py"],
        symbol_hubs=["app/sym1.py", "app/sym2.py"],
        untested_modules=["app/ut1.py", "app/ut2.py"],
        critical_untested_modules=["app/cu1.py", "app/cu2.py"],
        dependency_edges=[
            ("app/x.py", "app/a.py"),
            ("app/y.py", "app/a.py"),
            ("app/z.py", "app/b.py"),
            ("app/a.py", "app/b.py"),
            ("app/a.py", "app/c.py"),
        ],
        fragile_modules=["app/b.py"],
        modernizable_modules=["app/mod1.py", "app/mod2.py"],
        mutable_default_modules=["app/mut1.py", "app/mut2.py"],
        debt_marker_modules=["app/debt1.py", "app/debt2.py"],
        debt_marker_ages={"app/debt1.py": 200},
        hotspot_modules=["app/c.py"],
        shallow_tested_modules=["app/shallow1.py"],
        hotspot_functions=[
            {"module": "app/a.py", "function": "Klass.run", "line": 30,
             "complexity": 14, "cognitive": 9},
            {"module": "app/a.py", "function": "helper", "line": 10,
             "complexity": 7},
            {"module": "app/b.py", "function": "compute", "line": 5,
             "complexity": 11},
        ],
        impure_untested_functions=[
            {"module": "app/c.py", "function": "writer", "line": 12,
             "side_effects": ["fs", "log", "net", "env"]},
        ],
        hub_untested_modules=[{"module": "app/hubu.py", "fan_in": 4}],
        confluence_modules=[
            {"module": "app/a.py", "family_count": 3,
             "families": ("high-churn", "hub", "untested")},
        ],
        churn_hotspots=[{"module": "app/churn1.py", "commits": 17}],
        cochange_test_gaps=[
            {"a": "app/p.py", "b": "app/q.py", "cochanges": 8,
             "links": [{"from": "app/p.py", "to": "app/q.py", "symbol": "foo"}]},
            {"a": "app/r.py", "b": "app/s.py", "cochanges": 3, "links": []},
        ],
        knowledge_risks=[{"module": "app/kr.py", "share": 92, "commits": 14}],
        doc_drift=[
            {"doc": "README.md", "reference": "app/gone.py"},
            {"doc": "README.md", "reference": "app/also_gone.py"},
        ],
        dead_params=[
            {"module": "app/dp.py", "function": "do", "param": "unused",
             "line": 7},
        ],
        extractable_blocks=[
            {"module": "app/eb.py", "function": "big", "line": 3,
             "start": 10, "end": 20, "name": "helper", "lines_saved": 8,
             "params": ["x", "y"], "returns": ["z"]},
        ],
        inlinable_helpers=[{"module": "app/ih.py", "function": "tiny", "line": 4}],
        polyglot_hotspots=[
            {"path": "app/big.js", "loc": 900, "churn": 12,
             "language": "JavaScript", "debt_markers": 3},
        ],
        incomplete_protocols=[
            {"module": "app/proto.py", "class": "Box", "line": 5,
             "have": "__enter__", "missing": "__exit__",
             "protocol": "context-manager"},
        ],
        generalizable_duplications=[
            {"modules": ["app/d1.py", "app/d2.py", "app/d3.py"],
             "occurrences": 3, "lines": 12},
        ],
        coordinator_modules=[
            {"module": "app/coord.py", "imports": ["app/m1.py", "app/m2.py"]},
        ],
        deeply_nested_functions=[{"module": "app/nest.py", "function": "deep"}],
        god_classes=[{"module": "app/god.py", "classname": "Mega"}],
    )


# The FULL ordered seeded set on _all_families_profile(): (subject, fact_label).
# This is the frozen characterization that pins the post-extraction orchestrator
# order across every ``_seed_*`` helper. Any reordering, drop or addition trips it.
_ALL_FAMILIES_ORDER = [
    ("app/bug1.py", "correctness-bug"),
    ("app/bug2.py", "correctness-bug"),
    ("app/sec1.py", "security-finding"),
    ("app/sec2.py", "security-finding"),
    ("app/sec3.py", "security-finding"),
    ("app/a.py", "confluence"),
    ("app/b.py", "fragile"),
    ("app/hub3.py", "dependency-hub"),
    ("app/cu1.py", "critical-untested"),
    ("app/cu2.py", "critical-untested"),
    ("app/ut1.py", "untested"),
    ("app/ut2.py", "untested"),
    ("app/auth.py", "sensitive-path"),
    ("app/crypto.py", "sensitive-path"),
    ("app/secrets.py", "sensitive-path"),
    ("app/main.py", "entrypoint"),
    ("app/cli.py", "entrypoint"),
    ("app/sym1.py", "symbol-hub"),
    ("app/sym2.py", "symbol-hub"),
    ("settings.toml", "config"),
    ("app/shallow1.py", "shallow-coverage"),
    ("app/c.py", "complexity-hotspot"),
    ("app/a.py::Klass.run", "hotspot-function"),
    ("app/a.py::helper", "hotspot-function"),
    ("app/b.py::compute", "hotspot-function"),
    ("app/c.py::writer", "impure-untested"),
    ("app/hubu.py", "hub-untested"),
    ("app/p.py + app/q.py", "cochange-testgap"),
    ("app/r.py + app/s.py", "cochange-testgap"),
    ("app/debt1.py", "debt-markers"),
    ("app/debt2.py", "debt-markers"),
    ("app/churn1.py", "churn-hotspot"),
    ("app/big.js", "polyglot-hotspot"),
    ("app/proto.py::Box", "incomplete-protocol"),
    ("app/d1.py + app/d2.py", "generalizable-duplication"),
    ("app/coord.py", "coordinator"),
    ("app/nest.py::deep", "deep-nesting"),
    ("app/god.py::Mega", "god-class"),
    ("app/kr.py", "knowledge-risk"),
    ("README.md", "doc-drift"),
    ("Python type coverage", "extension-py"),
    ("app/mut1.py", "mutable-default"),
    ("app/mut2.py", "mutable-default"),
    ("app/dp.py", "dead-parameter"),
    ("app/eb.py", "extractable-block"),
    ("app/ih.py", "inlinable-helper"),
    ("app/mod1.py", "modernization"),
    ("app/mod2.py", "modernization"),
    ("app/ package", "top-directory"),
    ("CI pipeline", "missing-ci"),
]


def test_full_ordered_seeded_set_across_all_families():
    # Characterization: the orchestrator calls every ``_seed_*`` helper in the
    # exact order that produces this byte-identical seeded set. This pins the
    # decomposition of the (former) 398-LOC ``seed`` method — the helper order,
    # the cross-helper dedup-by-subject, and each family's emission count.
    roots = IdeaSeeder().seed(_all_families_profile())
    got = [(r.subject, r.source_facts[0].split(":", 1)[0]) for r in roots]
    assert got == _ALL_FAMILIES_ORDER

    # Root invariants hold for every emitted node.
    assert all(r.depth == 0 and r.operator == "root" for r in roots)
    assert all(r.novelty == 1.0 for r in roots)
    assert all(0.0 <= r.value <= 1.0 for r in roots)

    # IDs are dense and in emission order (no gaps from the helper split).
    assert [r.id for r in roots] == [f"idea-{i}" for i in range(len(roots))]


def test_extraction_preserves_cross_helper_dedup():
    # app/a.py is named by BOTH confluence (an earlier helper) and the
    # dependency-hub rule family (a later helper). The dedup-by-subject must
    # carry ``seen_subjects`` ACROSS helpers, so app/a.py is seeded exactly once
    # (by confluence, which runs first) — not re-emitted by the rule family.
    roots = IdeaSeeder().seed(_all_families_profile())
    a_roots = [r for r in roots if r.subject == "app/a.py"]
    assert len(a_roots) == 1
    assert a_roots[0].source_facts[0].startswith("confluence:")


def test_all_families_profile_seeds_one_per_listed_family():
    # The frozen order list and the live seeded set agree on length — a guard so
    # the order constant can't silently drift out of sync with the seeder.
    roots = IdeaSeeder().seed(_all_families_profile())
    assert len(roots) == len(_ALL_FAMILIES_ORDER)
