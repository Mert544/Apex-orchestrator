from pathlib import Path

from app.engine.idea_permutation import IdeaPermutationEngine


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp / "app" / "api.py").write_text("import app.main\n\ndef handler():\n    return app.main.main()\n")
    return tmp


def test_engine_builds_a_permutation_tree(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 3}, tmp_path
    ).run()

    assert rep.stats["total_ideas"] > len(rep.roots())  # expanded beyond roots
    assert any(i.depth == 2 for i in rep.ideas)          # reached depth 2
    # Every idea is traceable and well-scored.
    assert all(i.source_facts for i in rep.ideas)
    assert all(0.0 <= i.value <= 1.0 for i in rep.ideas)
    assert all(i.branch_path for i in rep.ideas)


def test_branches_are_unique_operator_permutations(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 3, "breadth": 4}, tmp_path
    ).run()

    titles = [i.title for i in rep.ideas]
    assert len(titles) == len(set(titles))  # no duplicate ideas

    for idea in rep.ideas:
        # An operator never repeats within a single branch path (a permutation).
        assert len(idea.operator_chain) == len(set(idea.operator_chain))
        # A child's chain extends its parent's by exactly one operator.
        if idea.parent_id:
            parent = next(p for p in rep.ideas if p.id == idea.parent_id)
            assert idea.operator_chain[:-1] == parent.operator_chain
            assert idea.depth == parent.depth + 1


def test_budget_is_respected(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 7, "max_idea_depth": 3, "breadth": 4}, tmp_path
    ).run()
    assert rep.stats["total_ideas"] <= 7


def test_objective_relevance_can_prune(tmp_path):
    _project(tmp_path)
    # With a hard relevance floor and an unrelated objective, off-theme
    # permutations are dropped.
    rep = IdeaPermutationEngine(
        {
            "max_total_ideas": 40,
            "max_idea_depth": 2,
            "breadth": 4,
            "min_relevance": 0.5,
        },
        tmp_path,
    ).run(objective="improve database indexing performance")
    assert rep.stats["pruned_relevance"] >= 1
    assert rep.objective == "improve database indexing performance"


def test_deterministic(tmp_path):
    _project(tmp_path)
    cfg = {"max_total_ideas": 25, "max_idea_depth": 2, "breadth": 3}
    a = IdeaPermutationEngine(cfg, tmp_path).run()
    b = IdeaPermutationEngine(cfg, tmp_path).run()
    assert [i.title for i in a.ideas] == [i.title for i in b.ideas]
