"""Regression guard: executable simplifications survive cross-family contention.

Before the ``::simplify-<transform>`` additive-subject fix, a module's EXECUTABLE
behaviour-preserving simplification was emitted on the BARE module subject and so
was silently deduped away whenever a higher-priority RECOMMEND-ONLY family
(dependency-hub, docstring, …) had already claimed that module — leaving
``apex maintain`` able to SEE a safe code change but never APPLY it.

These tests pin the fixed contract: the simplification root carries a
``<module>::simplify-<transform>`` subject (purely additive — no other family can
claim it), the recommend-only family idea still coexists on the bare module, and
the bridge still resolves the transform's target file to the bare module.
"""

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _contended_profile() -> ProjectProfile:
    # app/x.py is BOTH a dependency hub (a higher-priority, recommend-only family
    # that runs early and claims the bare-module subject) AND has a safe
    # simplification opportunity (a low-priority, EXECUTABLE family that runs late).
    prof = ProjectProfile(root=".", dependency_hubs=["app/x.py"], ci_files=["ci.yml"])
    prof.simplification_opportunities = [
        {"module": "app/x.py", "transform": "augmented_assign",
         "fact_label": "augmented-assign"},
    ]
    return prof


def test_executable_simplification_survives_higher_family_claim():
    roots = IdeaSeeder().seed(_contended_profile())

    # The recommend-only dependency-hub idea still owns the bare-module subject.
    hub = [r for r in roots if r.subject == "app/x.py"]
    assert len(hub) == 1
    assert hub[0].source_facts[0].startswith("dependency-hub")

    # The executable simplification is NO LONGER deduped away: it rides on the
    # additive ``::simplify-<transform>`` subject.
    simp = [r for r in roots if r.subject == "app/x.py::simplify-augmented_assign"]
    assert len(simp) == 1
    assert simp[0].source_facts[0].startswith("augmented-assign")
    assert simp[0].title == "Apply augmented_assign to simplify app/x.py"


def test_bridge_resolves_target_to_bare_module_despite_suffix():
    roots = IdeaSeeder().seed(_contended_profile())
    simp = next(r for r in roots
                if r.subject == "app/x.py::simplify-augmented_assign")
    step = IdeaActionBridge().plan_idea(simp)
    # The suffix is only a dedup key; the bridge splits on ``::`` so the transform
    # still applies to the real file.
    assert step.executable is True
    assert step.action_type == "augmented_assign"
    assert step.target == "app/x.py"


def test_every_transform_on_one_module_gets_its_own_executable_root():
    # Three distinct safe rewrites on the SAME module must yield THREE executable
    # roots (distinct ``::simplify-<transform>`` subjects), not one — they no
    # longer dedupe each other on the shared bare-module subject.
    prof = ProjectProfile(root=".", ci_files=["ci.yml"])
    prof.simplification_opportunities = [
        {"module": "app/y.py", "transform": "augmented_assign",
         "fact_label": "augmented-assign"},
        {"module": "app/y.py", "transform": "redundant_else",
         "fact_label": "redundant-else"},
        {"module": "app/y.py", "transform": "simplify_bool_return",
         "fact_label": "simplify-bool-return"},
    ]
    roots = IdeaSeeder().seed(prof)
    simp_subjects = sorted(r.subject for r in roots if r.subject.startswith("app/y.py::"))
    assert simp_subjects == [
        "app/y.py::simplify-augmented_assign",
        "app/y.py::simplify-redundant_else",
        "app/y.py::simplify-simplify_bool_return",
    ]
    # All three plan as executable steps targeting the same bare module.
    bridge = IdeaActionBridge()
    for r in (r for r in roots if r.subject.startswith("app/y.py::")):
        step = bridge.plan_idea(r)
        assert step.executable is True
        assert step.target == "app/y.py"


def test_simplification_is_additive_superset_over_no_opportunity():
    # Seeding WITH the contended simplification yields exactly the same roots as
    # WITHOUT it, plus the one appended executable simplification root — proving
    # the fix never drops or reorders a prior idea.
    base = ProjectProfile(root=".", dependency_hubs=["app/x.py"], ci_files=["ci.yml"])
    without = IdeaSeeder().seed(base)

    with_opp = IdeaSeeder().seed(_contended_profile())

    # Every prior (subject, first-fact) pair is preserved, in order.
    base_pairs = [(r.subject, r.source_facts[0]) for r in without]
    with_pairs = [(r.subject, r.source_facts[0]) for r in with_opp]
    added = [p for p in with_pairs if p not in base_pairs]
    assert [p for p in with_pairs if p in base_pairs] == base_pairs
    assert len(added) == 1
    assert added[0][0] == "app/x.py::simplify-augmented_assign"
