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


def test_render_markdown_and_mermaid(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 2}, tmp_path).run()
    from app.engine.idea_permutation import render_markdown, render_mermaid

    md = render_markdown(rep)
    assert "# Development Ideas" in md
    assert any(r.title in md for r in rep.roots())
    assert "value" in md

    mer = render_mermaid(rep)
    assert "flowchart TD" in mer
    assert "-->" in mer  # has at least one parent->child edge


def test_cli_ideate_smoke(tmp_path, capsys):
    _project(tmp_path)
    import argparse
    from app.cli import cmd_ideate

    args = argparse.Namespace(
        target=str(tmp_path), objective="", depth=2, breadth=3, max_ideas=10,
        min_relevance=0.0, mermaid=True, json=False, out="",
    )
    rc = cmd_ideate(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Development Ideas" in out
    assert "flowchart TD" in out


def test_caveats_are_operator_relevant(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 1, "breadth": 4}, tmp_path).run()
    harden = next(i for i in rep.ideas if i.operator == "harden")
    # Hardening caveats should reference input/validation/security, not the
    # generic "holds after refactoring" fallback.
    joined = " ".join(harden.caveats).lower()
    assert "input" in joined or "attacker" in joined or "validation" in joined


def test_novelty_decreases_with_depth_and_repetition(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 3, "breadth": 4}, tmp_path
    ).run()
    roots = [i for i in rep.ideas if i.operator == "root"]
    deep = [i for i in rep.ideas if i.depth >= 2]
    assert all(r.novelty == 1.0 for r in roots)
    assert deep and all(d.novelty < 1.0 for d in deep)
    assert all(0.2 <= i.novelty <= 1.0 for i in rep.ideas)
    assert all(0.0 <= i.value <= 1.0 for i in rep.ideas)
    # Values now spread out: more distinct values than there are roots.
    assert len({i.value for i in rep.ideas}) > len(roots)


def test_deep_rationale_references_prior_lenses(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4}, tmp_path
    ).run()
    deep = [i for i in rep.ideas if i.depth == 2]
    assert deep and all("building on:" in i.rationale for i in deep)
