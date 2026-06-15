"""Targeted coverage for the idea-permutation engine's remaining gaps.

These tests drive the few branches the happy-path and existing edge tests
leave uncovered: the fragile-modules seed loop, the partial-coverage seed
loop, the mid-expansion budget break, the import-cycle synthesis cap, and
the objective branch of render_markdown.

Deterministic, hermetic — constructed ProjectProfiles / tmp projects only,
no network and no wall-clock.
"""

from app.engine.idea_permutation import (
    IdeaPermutationEngine,
    IdeaSeeder,
    render_markdown,
)
from app.models.idea import IdeaTreeReport
from app.tools.project_profile import ProjectProfile


# ---------------------------------------------------------------------------
# IdeaSeeder.seed — fragile-modules branch (line 99)
# ---------------------------------------------------------------------------

def test_seed_emits_fragile_module_root(tmp_path):
    # fragile_modules are seeded first, highest priority, with a fragile fact.
    profile = ProjectProfile(root=str(tmp_path), fragile_modules=["app/core.py"])
    roots = IdeaSeeder().seed(profile)
    fragile = [r for r in roots if r.subject == "app/core.py"]
    assert fragile, "expected a root seeded from the fragile module"
    node = fragile[0]
    assert node.operator == "root"
    assert node.source_facts == ["fragile: app/core.py (high in-degree, thin tests)"]
    assert "Reduce fragility" in node.title


def test_seed_fragile_caps_at_three(tmp_path):
    # Only the first three fragile modules become roots.
    mods = [f"app/m{i}.py" for i in range(6)]
    profile = ProjectProfile(root=str(tmp_path), fragile_modules=mods)
    roots = IdeaSeeder().seed(profile)
    fragile_subjects = [r.subject for r in roots if r.source_facts[0].startswith("fragile")]
    assert fragile_subjects == mods[:3]


# ---------------------------------------------------------------------------
# IdeaSeeder.seed — shallow-coverage depth signal
# ---------------------------------------------------------------------------
# NB: the old "1 linked test file = thin" heuristic was intentionally dropped
# (it only produced noise — idea_seeder.py "Coverage DEPTH is handled by the
# substance-based shallow-coverage signal"). Depth is now driven by
# ``shallow_tested_modules`` (modules covered only by smoke/type stubs).

def test_seed_emits_shallow_coverage_root(tmp_path):
    # A module covered only by characterization stubs gets a "deepen the shallow
    # tests" root asking for real behavioural assertions.
    profile = ProjectProfile(
        root=str(tmp_path),
        shallow_tested_modules=["app/thin.py"],
    )
    roots = IdeaSeeder().seed(profile)
    shallow = [r for r in roots if r.subject == "app/thin.py"]
    assert shallow, "expected a shallow-coverage deepen root"
    node = shallow[0]
    assert node.source_facts[0].startswith("shallow-coverage: app/thin.py")
    assert "Deepen the shallow tests" in node.title


def test_seed_shallow_coverage_caps_at_three(tmp_path):
    # The shallow-coverage signal is capped (top 3) like the other depth signals.
    mods = [f"app/m{i}.py" for i in range(6)]
    profile = ProjectProfile(root=str(tmp_path), shallow_tested_modules=mods)
    roots = IdeaSeeder().seed(profile)
    shallow_subjects = [
        r.subject for r in roots if r.source_facts[0].startswith("shallow-coverage")
    ]
    assert shallow_subjects == mods[:3]


# ---------------------------------------------------------------------------
# Mid-expansion budget break (line 275)
# ---------------------------------------------------------------------------

def test_budget_caps_total_ideas_during_expansion(tmp_path):
    # A budget that leaves room for some permutation children still never emits
    # more ideas than the cap; the reserve slice keeps perm_cap <= max_total so
    # expansion stops cleanly at the cap.
    (tmp_path / "app").mkdir()
    for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
        (tmp_path / "app" / f"{name}.py").write_text(f"def {name}():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 10, "max_idea_depth": 3, "breadth": 8}, tmp_path
    ).run()
    assert rep.stats["total_ideas"] <= 10
    # Some children were expanded beyond the roots.
    assert any(i.depth > 0 for i in rep.ideas)


def test_budget_exactly_root_count_skips_expansion(tmp_path):
    # When the budget is consumed entirely by roots, no children can be emitted.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "only.py").write_text("def only():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 1, "max_idea_depth": 2, "breadth": 4}, tmp_path
    ).run()
    assert rep.stats["total_ideas"] == 1
    assert all(i.depth == 0 for i in rep.ideas)


# ---------------------------------------------------------------------------
# Import-cycle synthesis cap (line 370: pidx >= 4 break)
# ---------------------------------------------------------------------------

def test_synthesis_import_cycles_capped(tmp_path):
    # Only the first three cycles are considered ([:3]); the pidx>=4 guard is a
    # defensive cap. Build three distinct cycles and confirm we get <= 3 cycle
    # ideas, each a "pair"-kind synthesized node.
    cycles = [
        ["app/a.py", "app/b.py", "app/a.py"],
        ["app/c.py", "app/d.py", "app/c.py"],
        ["app/e.py", "app/f.py", "app/e.py"],
    ]
    profile = ProjectProfile(root=str(tmp_path), import_cycles=cycles)
    eng = IdeaPermutationEngine({}, tmp_path)
    # Prime the per-run scoring state the way run() does.
    eng.run()  # establishes novelty/graph scaffolding on the instance

    from app.memory.graph_store import GraphStore
    from app.skills.relevance_scorer import RelevanceScorer

    graph = GraphStore()
    rel = RelevanceScorer("")
    eng._chain_counts = {}
    eng._subject_counts = {}
    eng._has_objective = False
    eng._security_pressure = 1.0
    synth = eng._synthesize([], profile, rel, graph)
    cycle_ideas = [n for n in synth if "Break the import cycle" in n.title]
    assert 1 <= len(cycle_ideas) <= 4
    assert all(n.kind == "pair" for n in cycle_ideas)


# ---------------------------------------------------------------------------
# render_markdown objective branch (line 574)
# ---------------------------------------------------------------------------

def test_render_markdown_includes_objective(tmp_path):
    # When the report carries an objective, the meta line surfaces it.
    rep = IdeaTreeReport(
        objective="reduce flakiness",
        project_root=str(tmp_path),
        ideas=[],
        branch_map={},
        stats={"total_ideas": 0, "mean_value": 0.0},
    )
    md = render_markdown(rep)
    assert "objective: _reduce flakiness_" in md


def test_render_markdown_omits_objective_when_empty(tmp_path):
    # An empty objective leaves the meta line free of an objective prefix.
    rep = IdeaTreeReport(
        objective="",
        project_root=str(tmp_path),
        ideas=[],
        branch_map={},
        stats={"total_ideas": 0, "mean_value": 0.0},
    )
    md = render_markdown(rep)
    assert "objective:" not in md


# ---------------------------------------------------------------------------
# Engine invariants on a real tiny project (value bounds, root novelty)
# ---------------------------------------------------------------------------

def test_engine_invariants_value_bounds_and_root_novelty(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text(
        "import app.helper\n\ndef svc():\n    return app.helper.help()\n"
    )
    (tmp_path / "app" / "helper.py").write_text("def help():\n    return 2\n")
    rep = IdeaPermutationEngine({"max_idea_depth": 2}, tmp_path).run()
    assert rep.ideas, "expected at least one idea from a real project"
    for idea in rep.ideas:
        assert 0.0 <= idea.value <= 1.0
    for root in (i for i in rep.ideas if i.operator == "root"):
        assert root.novelty == 1.0
