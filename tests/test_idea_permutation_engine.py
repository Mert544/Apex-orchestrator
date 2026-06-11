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
    # Permutation children carry the lens-path rationale; facet ideas are a
    # separate kind with their own "fractal zoom" rationale.
    deep = [i for i in rep.ideas if i.depth == 2 and i.kind == "permutation"]
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


def test_convergence_idea_when_signals_agree_on_one_subject():
    # A subject flagged by two *different* risk dimensions (sensitive + untested)
    # yields a single high-priority convergence idea naming both.
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore

    profile = ProjectProfile(
        root=".",
        sensitive_paths=["app/auth.py"],
        untested_modules=["app/auth.py", "app/util.py"],   # util only untested -> no convergence
        hotspot_modules=["app/auth.py"],                   # third dimension on auth
    )
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False
    eng._chain_counts, eng._subject_counts = {}, {}
    ideas = eng._convergence_ideas(profile, RelevanceScorer(""), GraphStore())
    assert len(ideas) == 1                                 # only auth.py converges
    idea = ideas[0]
    assert idea.subject == "app/auth.py"
    assert "3 independent analyses converge" in idea.title
    for phrase in ("security-sensitive", "a complexity hotspot", "untested"):
        assert phrase in idea.title
    assert idea.kind == "synthesis"
    assert idea.source_facts[0].startswith("convergence:")
    # More agreeing signals -> higher feasibility than a 2-signal convergence.
    assert idea.feasibility >= 0.9


def test_convergence_needs_two_distinct_dimensions():
    # critically-untested + untested are the SAME dimension (coverage), so a
    # subject carrying only those does NOT converge.
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore

    profile = ProjectProfile(
        root=".",
        untested_modules=["app/x.py"],
        critical_untested_modules=["app/x.py"],
    )
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False
    eng._chain_counts, eng._subject_counts = {}, {}
    assert eng._convergence_ideas(profile, RelevanceScorer(""), GraphStore()) == []


def test_convergence_idea_is_top_impact_tier_in_roadmap(tmp_path):
    # End-to-end: a sensitive + untested module produces a convergence idea the
    # roadmap places in the top-impact tier (its impact equals the plan max).
    # (Impact is feasibility-decoupled, so several high-leverage roots can tie
    # at the ceiling — convergence must be AT that ceiling, not below it.)
    from app.engine.idea_roadmap import RoadmapSynthesizer
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(
        "import os\ndef login(pw):\n    return os.system(pw)\n"   # sensitive name + risky
    )
    (tmp_path / "app" / "calm.py").write_text("def calm():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 1, "breadth": 4}, tmp_path
    ).run()
    conv = [i for i in rep.ideas if i.source_facts and i.source_facts[0].startswith("convergence:")]
    assert conv, "expected a convergence idea for the sensitive+untested module"
    roadmap = RoadmapSynthesizer().build(rep)
    all_items = [it for ph in roadmap.phases for it in ph.items]
    max_impact = max(it.impact for it in all_items)
    conv_items = [it for it in all_items if it.subject == "app/auth.py"
                  and "converge" in it.title]
    assert conv_items and conv_items[0].impact == max_impact


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
    eng.run()
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


def test_fractal_facets_zoom_leaves_into_subideas(tmp_path):
    # With facets enabled, the strongest permutation leaves open into
    # self-similar sub-ideas (kind="facet"), parented under their leaf.
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 2, "breadth": 4, "fractal_facets": True},
        tmp_path,
    ).run()
    facets = [i for i in rep.ideas if i.kind == "facet"]
    assert facets, "expected fractal facet ideas when enabled"
    assert rep.stats.get("faceted", 0) == len(facets)
    by_id = {i.id: i for i in rep.ideas}
    for f in facets:
        # Parented under a real permutation idea (the fractal zoom).
        assert f.parent_id in by_id
        assert by_id[f.parent_id].kind == "permutation"
        # Self-similar: subject is refined, facet is traceable.
        assert " :: " in f.subject
        assert any(fact.startswith("facet:") for fact in f.source_facts)
        assert 0.0 <= f.value <= 1.0


def test_facets_recurse_to_requested_depth(tmp_path):
    # facet_depth>1 drills the top leaves into self-similar sub-facets: a level-2
    # facet's branch path contains two ".f" hops and its chain of facet labels
    # is strictly nested (no case repeats on a branch).
    _project(tmp_path)
    rep = IdeaPermutationEngine(
        {
            "max_total_ideas": 80,
            "max_idea_depth": 2,
            "breadth": 4,
            "fractal_facets": True,
            "facet_depth": 3,
        },
        tmp_path,
    ).run()
    facets = [i for i in rep.ideas if i.kind == "facet"]
    levels = [f.branch_path.count(".f") for f in facets]
    assert max(levels) >= 2, "expected facets nested at least two zoom levels deep"
    # A deep facet's case labels never repeat along its branch.
    deep = max(facets, key=lambda f: f.branch_path.count(".f"))
    facet_labels = [s.split("facet:", 1)[1].strip() for s in deep.source_facts if s.startswith("facet:")]
    assert len(facet_labels) == len(set(facet_labels))
    by_id = {i.id: i for i in rep.ideas}
    # The whole zoom chain is connected back to a permutation leaf.
    cur = deep
    while cur.parent_id in by_id and by_id[cur.parent_id].kind == "facet":
        cur = by_id[cur.parent_id]
    assert by_id[cur.parent_id].kind == "permutation"


def test_adaptive_depth_deepens_high_value_branches(tmp_path):
    # Several modules + room in the budget: adaptive mode pushes the strongest
    # branches past the base max_depth, concentrating the fractal where value is.
    (tmp_path / "app").mkdir()
    for n in ("a", "b", "c", "d"):
        (tmp_path / "app" / f"{n}.py").write_text(f"def {n}():\n    return 1\n")
    cfg = {"max_total_ideas": 200, "max_idea_depth": 2, "breadth": 3}
    base = IdeaPermutationEngine(cfg, tmp_path).run()
    adapt = IdeaPermutationEngine({**cfg, "adaptive_depth": True}, tmp_path).run()
    assert max(i.depth for i in base.ideas) == 2          # base respects the cap
    assert max(i.depth for i in adapt.ideas) >= 3         # adaptive goes deeper
    # Each extra-depth node exists because its parent cleared the value bar.
    by_id = {i.id: i for i in adapt.ideas}
    for deep in (i for i in adapt.ideas if i.depth > 2):
        parent = by_id.get(deep.parent_id)
        assert parent is not None and parent.value >= 0.6


def test_adaptive_depth_off_by_default(tmp_path):
    (tmp_path / "app").mkdir()
    for n in ("a", "b", "c", "d"):
        (tmp_path / "app" / f"{n}.py").write_text(f"def {n}():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 200, "max_idea_depth": 2, "breadth": 3}, tmp_path
    ).run()
    assert max(i.depth for i in rep.ideas) == 2  # no deepening without opt-in


def test_adaptive_depth_is_deterministic(tmp_path):
    (tmp_path / "app").mkdir()
    for n in ("a", "b", "c"):
        (tmp_path / "app" / f"{n}.py").write_text(f"def {n}():\n    return 1\n")
    cfg = {"max_total_ideas": 150, "max_idea_depth": 2, "breadth": 3, "adaptive_depth": True}
    a = IdeaPermutationEngine(cfg, tmp_path).run()
    b = IdeaPermutationEngine(cfg, tmp_path).run()
    assert [i.title for i in a.ideas] == [i.title for i in b.ideas]


def test_facets_off_by_default(tmp_path):
    _project(tmp_path)
    rep = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 2}, tmp_path).run()
    assert not any(i.kind == "facet" for i in rep.ideas)


def test_facets_are_deterministic(tmp_path):
    _project(tmp_path)
    cfg = {"max_total_ideas": 50, "max_idea_depth": 2, "breadth": 4, "fractal_facets": True}
    a = IdeaPermutationEngine(cfg, tmp_path).run()
    b = IdeaPermutationEngine(cfg, tmp_path).run()
    assert [i.title for i in a.ideas] == [i.title for i in b.ideas]


def test_facets_render_nested_not_in_synth_section(tmp_path):
    _project(tmp_path)
    from app.engine.idea_permutation import render_markdown
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 2, "breadth": 4, "fractal_facets": True},
        tmp_path,
    ).run()
    md = render_markdown(rep)
    facets = [i for i in rep.ideas if i.kind == "facet"]
    # Facet titles appear (nested under their leaf), e.g. "— input validation".
    assert facets and any(f.title in md for f in facets)


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


def test_convergence_renders_nested_mini_roadmap(tmp_path):
    # A sensitive + untested module's convergence idea renders with an ordered,
    # phased mini-roadmap (Stabilize step before Secure step).
    from app.engine.idea_permutation import render_markdown
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text("import os\ndef login(pw):\n    return os.system(pw)\n")
    (tmp_path / "app" / "calm.py").write_text("def calm():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 1, "breadth": 4}, tmp_path
    ).run()
    md = render_markdown(rep)
    assert "independent analyses converge" in md
    assert "[Stabilize]" in md and "[Secure]" in md
    # Stabilize must be listed before Secure (safety net before hardening).
    assert md.index("[Stabilize]") < md.index("[Secure]")


def test_content_security_finding_adds_a_convergence_dimension():
    # A file flagged ONLY by a content security finding (not by name) plus an
    # untested signal should converge with a "security-sensitive" dimension.
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/report.py"],   # eval inside, bland name
        untested_modules=["app/report.py"],
    )
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False
    eng._chain_counts, eng._subject_counts = {}, {}
    ideas = eng._convergence_ideas(profile, RelevanceScorer(""), GraphStore())
    assert len(ideas) == 1
    assert "security-sensitive" in ideas[0].title


def test_name_and_content_security_are_one_dimension_not_two():
    # Same file matched by BOTH sensitive name and content finding must not fake
    # a 2-dimension convergence on the security axis alone.
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore
    profile = ProjectProfile(
        root=".",
        sensitive_paths=["app/auth.py"],
        security_finding_modules=["app/auth.py"],
    )
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False
    eng._chain_counts, eng._subject_counts = {}, {}
    assert eng._convergence_ideas(profile, RelevanceScorer(""), GraphStore()) == []  # only 1 distinct dim


def test_convergence_value_bonus_makes_it_lead():
    # The convergence value gains a bonus per agreeing signal, so a 3-signal
    # convergence outscores a 2-signal one (the prose-vs-number fix).
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False

    def conv_value(**lists):
        eng._chain_counts, eng._subject_counts = {}, {}
        ideas = eng._convergence_ideas(ProjectProfile(root=".", **lists),
                                       RelevanceScorer(""), GraphStore())
        return ideas[0].value

    three = conv_value(sensitive_paths=["app/a.py"], hotspot_modules=["app/a.py"],
                       untested_modules=["app/a.py"])
    two = conv_value(sensitive_paths=["app/b.py"], untested_modules=["app/b.py"])
    assert three > two


def test_thematic_idea_when_one_signal_spans_many_modules():
    # The horizontal complement to convergence: a single signal (untested)
    # across enough modules yields ONE systemic theme naming the count.
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore
    profile = ProjectProfile(
        root=".",
        untested_modules=[f"app/m{i}.py" for i in range(6)],
    )
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False
    eng._chain_counts, eng._subject_counts = {}, {}
    ideas = eng._thematic_ideas(profile, RelevanceScorer(""), GraphStore())
    themes = [i for i in ideas if i.source_facts[0].startswith("theme: coverage-theme")]
    assert len(themes) == 1
    assert "6 modules" in themes[0].title
    assert themes[0].kind == "synthesis"


def test_thematic_idea_needs_enough_modules():
    from app.tools.project_profile import ProjectProfile
    from app.skills.relevance_scorer import RelevanceScorer
    from app.memory.graph_store import GraphStore
    # Only 2 untested modules — below the coverage-theme threshold of 4.
    profile = ProjectProfile(root=".", untested_modules=["app/a.py", "app/b.py"])
    eng = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3}, ".")
    eng._has_objective = False
    eng._chain_counts, eng._subject_counts = {}, {}
    assert eng._thematic_ideas(profile, RelevanceScorer(""), GraphStore()) == []
