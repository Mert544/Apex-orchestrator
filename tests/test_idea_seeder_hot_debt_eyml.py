"""Tests for the hot-debt seeding signal.

A module that is BOTH a churn hotspot AND carries clustered TODO/FIXME/XXX/HACK
debt markers is debt that is actively decaying — friction the team pays on every
change. The signal is purely additive: existing roots are unchanged and stay in
the same order (deterministic superset), with a ``(hot-debt)``-suffixed subject
that no other family can claim.
"""

from app.engine.idea_permutation import IdeaSeeder
from app.tools.project_profile import ProjectProfile
from app.utils.branching import make_branch_path


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _hot_debt(roots):
    return [r for r in roots if r.source_facts[0].startswith("hot-debt")]


def test_hot_debt_fires_on_churn_and_debt_marker_intersection():
    profile = _profile(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        debt_marker_modules=["app/core.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    hot = _hot_debt(roots)
    assert len(hot) == 1
    node = hot[0]
    # Distinct subject so it never collides with the plain churn/debt root.
    assert node.subject == "app/core.py (hot-debt)"
    assert node.depth == 0
    assert node.operator == "root"
    assert node.branch_path.startswith("x.")
    # Grounds in BOTH measured facts.
    assert "42 recent commits" in node.title
    assert "TODO/FIXME markers" in node.title
    assert "hot-debt" in node.source_facts[0]


def test_pins_deterministic_output_on_synthetic_fixture():
    profile = _profile(
        churn_hotspots=[{"module": "app/svc.py", "commits": 17}],
        debt_marker_modules=["app/svc.py"],
        ci_files=["ci.yml"],
    )
    node = _hot_debt(IdeaSeeder().seed(profile))[0]
    assert node.title == (
        "Pay down the debt in app/svc.py now — it is both a change hotspot "
        "(17 recent commits) and carries clustered TODO/FIXME markers"
    )
    assert node.source_facts == [
        "hot-debt: app/svc.py (17 recent commits AND clustered "
        "TODO/FIXME/XXX/HACK markers — the fastest-changing code carries "
        "deferred work; pay it down while it is already open)"
    ]


def test_aged_markers_annotate_title_and_fact():
    profile = _profile(
        churn_hotspots=[{"module": "app/old.py", "commits": 9}],
        debt_marker_modules=["app/old.py"],
        debt_marker_ages={"app/old.py": 400},
        ci_files=["ci.yml"],
    )
    node = _hot_debt(IdeaSeeder().seed(profile))[0]
    # 400 // 30 == 13 months.
    assert "oldest marker waiting ~13 months" in node.source_facts[0]


def test_does_not_fire_without_intersection():
    # Churn hotspot but no matching debt marker -> no hot-debt root.
    only_churn = _profile(
        churn_hotspots=[{"module": "app/a.py", "commits": 10}],
        debt_marker_modules=["app/b.py"],
        ci_files=["ci.yml"],
    )
    assert _hot_debt(IdeaSeeder().seed(only_churn)) == []

    # Debt markers but no churn -> nothing.
    only_debt = _profile(
        debt_marker_modules=["app/a.py"],
        ci_files=["ci.yml"],
    )
    assert _hot_debt(IdeaSeeder().seed(only_debt)) == []


def test_empty_profile_unaffected():
    # No facts at all: the seed contributes nothing.
    assert _hot_debt(IdeaSeeder().seed(_profile())) == []


def test_capped_at_three():
    churn = [{"module": f"app/m{i}.py", "commits": 50 - i} for i in range(6)]
    debt = [f"app/m{i}.py" for i in range(6)]
    profile = _profile(churn_hotspots=churn, debt_marker_modules=debt, ci_files=["ci.yml"])
    assert len(_hot_debt(IdeaSeeder().seed(profile))) == 3


def test_deterministic_superset_prior_roots_unchanged_and_ordered():
    """The signal is purely additive: removing the intersecting debt marker
    leaves every prior root identical and in the same order, and the new run is
    a strict superset (the hot-debt root is the only addition)."""
    base = dict(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        dependency_hubs=["app/core.py"],
        fragile_modules=["app/util.py"],
        ci_files=["ci.yml"],
    )
    without = IdeaSeeder().seed(_profile(**base))
    with_signal = IdeaSeeder().seed(
        _profile(**base, debt_marker_modules=["app/core.py"])
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
    assert added.subject == "app/core.py (hot-debt)"
    assert added.source_facts[0].startswith("hot-debt")
    # branch_path is the next index, so the prior paths never shift.
    assert added.branch_path == make_branch_path("x", len(without))


def test_runs_after_hot_bus_factor():
    """When BOTH last-wired signals fire, hot-bus-factor precedes hot-debt so the
    final ordering is stable and hot-debt is genuinely seeded LAST."""
    profile = _profile(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        knowledge_risks=[{"module": "app/core.py", "share": 90, "commits": 30}],
        debt_marker_modules=["app/core.py"],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    bus_idx = next(i for i, r in enumerate(roots)
                   if r.source_facts[0].startswith("hot-bus-factor"))
    debt_idx = next(i for i, r in enumerate(roots)
                    if r.source_facts[0].startswith("hot-debt"))
    assert bus_idx < debt_idx
    # hot-debt is the very last root.
    assert debt_idx == len(roots) - 1


def test_deterministic_same_input_same_output():
    profile_kw = dict(
        churn_hotspots=[{"module": "app/core.py", "commits": 42}],
        debt_marker_modules=["app/core.py"],
        ci_files=["ci.yml"],
    )
    a = IdeaSeeder().seed(_profile(**profile_kw))
    b = IdeaSeeder().seed(_profile(**profile_kw))
    assert [r.model_dump() for r in a] == [r.model_dump() for r in b]
