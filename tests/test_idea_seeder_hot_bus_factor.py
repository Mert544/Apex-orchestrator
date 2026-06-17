"""Tests for the hot bus-factor seeding signal.

A module that is BOTH a churn hotspot AND knowledge-concentrated to one author
is the most urgent bus-factor case. The signal is purely additive: existing
roots are unchanged and stay in the same order (deterministic superset).
"""

from app.engine.idea_permutation import IdeaSeeder
from app.tools.project_profile import ProjectProfile
from app.utils.branching import make_branch_path


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _hot_bus(roots):
    return [r for r in roots if r.source_facts[0].startswith("hot-bus-factor")]


def test_hot_bus_factor_fires_on_churn_and_single_author_intersection():
    profile = _profile(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        knowledge_risks=[{"module": "app/core.py", "share": 90, "commits": 30}],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    hot = _hot_bus(roots)
    assert len(hot) == 1
    node = hot[0]
    # Distinct subject so it never collides with the plain churn/knowledge root.
    assert node.subject == "app/core.py (bus-factor)"
    assert node.depth == 0
    assert node.operator == "root"
    assert node.branch_path.startswith("x.")
    # Grounds in BOTH measured facts.
    assert "42 recent commits" in node.title
    assert "90% single-author" in node.title
    assert "hot-bus-factor" in node.source_facts[0]


def test_does_not_fire_without_intersection():
    # Churn hotspot but no matching knowledge risk -> no hot-bus-factor root.
    only_churn = _profile(
        churn_hotspots=[{"module": "app/a.py", "commits": 10}],
        knowledge_risks=[{"module": "app/b.py", "share": 80, "commits": 5}],
        ci_files=["ci.yml"],
    )
    assert _hot_bus(IdeaSeeder().seed(only_churn)) == []

    # Knowledge risk but no churn -> nothing.
    only_risk = _profile(
        knowledge_risks=[{"module": "app/a.py", "share": 80, "commits": 5}],
        ci_files=["ci.yml"],
    )
    assert _hot_bus(IdeaSeeder().seed(only_risk)) == []


def test_empty_profile_unaffected():
    # No git facts at all: the seed contributes nothing.
    assert _hot_bus(IdeaSeeder().seed(_profile())) == []


def test_capped_at_three():
    churn = [{"module": f"app/m{i}.py", "commits": 50 - i} for i in range(6)]
    risks = [{"module": f"app/m{i}.py", "share": 70 + i, "commits": 20} for i in range(6)]
    profile = _profile(churn_hotspots=churn, knowledge_risks=risks, ci_files=["ci.yml"])
    assert len(_hot_bus(IdeaSeeder().seed(profile))) == 3


def test_deterministic_superset_prior_roots_unchanged_and_ordered():
    """The signal is purely additive: removing the intersecting knowledge_risk
    leaves every prior root identical and in the same order, and the new run is
    a strict superset (the hot-bus-factor root is the only addition)."""
    base = dict(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        dependency_hubs=["app/core.py"],
        fragile_modules=["app/util.py"],
        ci_files=["ci.yml"],
    )
    without = IdeaSeeder().seed(_profile(**base))
    with_signal = IdeaSeeder().seed(
        _profile(
            **base,
            knowledge_risks=[{"module": "app/core.py", "share": 88, "commits": 30}],
        )
    )

    # Every prior root is present, unchanged, in the SAME order (prefix match).
    assert len(with_signal) == len(without) + 1
    for before, after in zip(without, with_signal[: len(without)]):
        assert before.subject == after.subject
        assert before.title == after.title
        assert before.branch_path == after.branch_path
        assert before.source_facts == after.source_facts

    # The single addition is the new signal, appended at the end.
    added = with_signal[-1]
    assert added.subject == "app/core.py (bus-factor)"
    assert added.source_facts[0].startswith("hot-bus-factor")
    # branch_path is the next index, so the prior paths never shift.
    assert added.branch_path == make_branch_path("x", len(without))


def test_deterministic_same_input_same_output():
    profile_kw = dict(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        knowledge_risks=[{"module": "app/core.py", "share": 90, "commits": 30}],
        ci_files=["ci.yml"],
    )
    a = IdeaSeeder().seed(_profile(**profile_kw))
    b = IdeaSeeder().seed(_profile(**profile_kw))
    assert [r.model_dump() for r in a] == [r.model_dump() for r in b]
