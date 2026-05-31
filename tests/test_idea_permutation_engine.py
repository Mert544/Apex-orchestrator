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

    # Permutation invariants apply only to permutation-kind ideas; synthesis
    # and module-pair ideas are a separate emit path by design.
    perm = [i for i in rep.ideas if i.kind == "permutation"]
    for idea in perm:
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


def test_synthesis_creates_security_test_suite_idea(tmp_path):
    # A subject that gets both test and harden lenses should yield a synthesized
    # security-test-suite idea (kind="synthesis").
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 2, "breadth": 8}, tmp_path
    ).run()
    synth = [i for i in rep.ideas if i.kind == "synthesis"]
    assert synth, "expected at least one synthesized idea"
    assert any("security-focused test suite" in i.title for i in synth)
    assert "synthesized" in rep.stats


def test_module_pair_ideas_from_dependency_edges(tmp_path):
    # app/b.py imports app/a.py -> a dependency edge -> a "standardize interface" pair idea.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "app" / "b.py").write_text("import app.a\ndef b():\n    return app.a.a()\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 1, "breadth": 4}, tmp_path
    ).run()
    pairs = [i for i in rep.ideas if i.kind == "pair"]
    assert pairs, "expected at least one module-pair idea"
    assert any("interface between" in i.title or "import cycle" in i.title for i in pairs)


def test_diversity_spreads_ideas_across_subjects(tmp_path):
    # Several modules so the tree has multiple candidate subjects.
    (tmp_path / "app").mkdir()
    for name in ("a", "b", "c", "d"):
        (tmp_path / "app" / f"{name}.py").write_text(f"def {name}():\n    return 1\n")
    from collections import Counter
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4}, tmp_path
    ).run()
    child_subjects = Counter(
        i.subject for i in rep.ideas if i.kind == "permutation" and i.depth > 0
    )
    # Diversity-aware selection should touch more than one subject.
    assert len(child_subjects) >= 2


def test_render_markdown_shows_synthesized_section(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 2, "breadth": 8}, tmp_path
    ).run()
    from app.engine.idea_permutation import render_markdown

    md = render_markdown(rep)
    synth = [i for i in rep.ideas if i.kind != "permutation"]
    if synth:
        assert "Synthesized ideas" in md
        assert any(i.title in md for i in synth)


def test_security_pressure_amplifies_harden_test(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("import os\ndef r(c):\n    return eval(c)\n")
    eng = IdeaPermutationEngine(
        {"max_total_ideas": 30, "max_idea_depth": 1, "breadth": 6}, tmp_path
    )
    rep = eng.run()
    # Real findings raise the pressure above the neutral 1.0.
    assert eng._security_pressure > 1.0
    # Clean project stays neutral.
    (tmp_path / "app" / "clean.py").write_text("def ok(x):\n    return x + 1\n")
    clean = tmp_path / "clean_proj"
    clean.mkdir()
    (clean / "m.py").write_text("def ok(x):\n    return x + 1\n")
    eng2 = IdeaPermutationEngine({"max_total_ideas": 20}, clean)
    eng2.run()
    assert eng2._security_pressure == 1.0


def test_value_weights_calibrate_to_objective_presence(tmp_path):
    # Without an objective, relevance is constant 1.0, so the engine shifts
    # weight to novelty/feasibility — the signals that actually vary — and the
    # value distribution should remain discriminating (not flat).
    (tmp_path / "app").mkdir()
    for n in ("a", "b", "c", "d", "e"):
        (tmp_path / "app" / f"{n}.py").write_text(f"def {n}():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 3, "breadth": 4}, tmp_path
    ).run()
    vals = [i.value for i in rep.ideas]
    # Discriminating: clearly more than a couple of distinct score levels.
    assert len(set(vals)) >= max(5, len(vals) // 3)
    assert max(vals) - min(vals) > 0.1


def test_ideate_kind_filter(tmp_path, capsys):
    import argparse
    from app.cli import cmd_ideate
    _project(tmp_path)
    args = argparse.Namespace(
        target=str(tmp_path), objective="", depth=2, breadth=8, max_ideas=60,
        min_relevance=0.0, mermaid=False, json=False, out="", kind="synthesis",
    )
    assert cmd_ideate(args) == 0
    out = capsys.readouterr().out
    assert "synthesis ideas for" in out


def test_detects_indirect_import_cycle(tmp_path):
    # A -> B -> C -> A is an indirect cycle the old mutual-edge check missed.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import app.b\ndef a():\n    return app.b.b()\n")
    (tmp_path / "app" / "b.py").write_text("import app.c\ndef b():\n    return app.c.c()\n")
    (tmp_path / "app" / "c.py").write_text("import app.a\ndef c():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 1}, tmp_path
    ).run()
    pairs = [i for i in rep.ideas if i.kind == "pair"]
    assert any("import cycle" in i.title for i in pairs)
    # The cycle idea references all three modules.
    cyc = next(i for i in pairs if "import cycle" in i.title)
    assert "a.py" in cyc.title and "b.py" in cyc.title and "c.py" in cyc.title
