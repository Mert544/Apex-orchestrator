"""Branch / edge coverage for app.engine.idea_permutation scoring + render.

The end-to-end engine suite already drives the tree build; this file pins the
pure scoring helpers and the markdown / mermaid render arms that a bounded run
doesn't reliably exercise:

  - ``_magnitude_bonus``: each measured-quantity pattern (months, single-author
    share, confidence, commits, complexity) and the no-match floor.
  - ``_context_weight``: the security upweight (with pressure), the
    integrate/generalize downweight, and the neutral default.
  - ``_caveat_hint``: the synthesis/pair kind path, the operator path, the root
    fact-label path, and the unknown-label floor.
  - ``convergence_labels`` / ``convergence_plan``: label extraction and the
    phased, action-deduped mini-roadmap.
  - ``render_markdown``: a permutation root with anchors (focus line), a nested
    facet (zoom + evidence), and the synthesized-ideas section with a
    convergence plan.
  - ``render_mermaid``: a facet node label and a dangling parent_id edge.

All inputs are constructed explicitly; no time, randomness, or order-dependent
assertions.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_permutation import (
    IdeaPermutationEngine,
    _caveat_hint,
    _context_weight,
    _compose_title,
    _join_phrase,
    _magnitude_bonus,
    convergence_labels,
    convergence_plan,
    render_markdown,
    render_mermaid,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _node(**kw) -> IdeaNode:
    base = dict(id="i", title="t", subject="s", value=0.5, feasibility=0.5)
    base.update(kw)
    return IdeaNode(**base)


# --- _magnitude_bonus: each measured pattern ----------------------------------

def test_magnitude_bonus_months_pattern():
    # ~16 months saturates the bonus; ~8 months earns roughly half.
    full = _magnitude_bonus(_node(source_facts=["sensitive-path: m.py (~16 months exposed)"]))
    half = _magnitude_bonus(_node(source_facts=["sensitive-path: m.py (~8 months exposed)"]))
    assert full > half > 0.0
    assert full <= 0.08


def test_magnitude_bonus_single_author_share_wins_over_commits():
    # A knowledge-risk fact mentions both a single-author % and commits; the
    # share pattern is ordered first, so it governs the bonus.
    bonus = _magnitude_bonus(_node(
        source_facts=["knowledge-risk: m.py 100% single-author across 40 commits"]))
    assert bonus == 0.08  # 100/100 saturates


def test_magnitude_bonus_confidence_pattern():
    bonus = _magnitude_bonus(_node(source_facts=["dream-insight: 100% confidence pattern"]))
    assert bonus == 0.08


def test_magnitude_bonus_commits_pattern():
    full = _magnitude_bonus(_node(source_facts=["churn-hotspot: m.py 50 commits"]))
    half = _magnitude_bonus(_node(source_facts=["churn-hotspot: m.py 25 commits"]))
    assert full > half > 0.0


def test_magnitude_bonus_complexity_pattern():
    bonus = _magnitude_bonus(_node(source_facts=["complexity-hotspot: m.py complexity 24"]))
    assert bonus == 0.08


def test_magnitude_bonus_no_measured_quantity_is_zero():
    assert _magnitude_bonus(_node(source_facts=["entrypoint: cli.py"])) == 0.0
    assert _magnitude_bonus(_node(source_facts=[])) == 0.0


# --- _context_weight: security routing ----------------------------------------

def test_context_weight_security_upweights_harden_and_test():
    node = _node(source_facts=["security-finding: m.py eval"])
    assert _context_weight(node, "harden") == 1.1
    assert _context_weight(node, "test") == 1.1


def test_context_weight_security_pressure_amplifies_and_caps():
    node = _node(source_facts=["security-finding: m.py eval"])
    # Pressure amplifies the 1.1 boost, capped at 1.3.
    assert _context_weight(node, "harden", security_pressure=1.1) > 1.1
    assert _context_weight(node, "harden", security_pressure=5.0) == 1.3


def test_context_weight_security_downweights_integrate_generalize():
    node = _node(source_facts=["sensitive-path: m.py"])
    assert _context_weight(node, "integrate") == 0.9
    assert _context_weight(node, "generalize") == 0.9


def test_context_weight_security_label_other_op_is_neutral():
    node = _node(source_facts=["fragile: m.py"])
    assert _context_weight(node, "document") == 1.0


def test_context_weight_non_security_label_is_neutral():
    node = _node(source_facts=["config: c.toml"])
    assert _context_weight(node, "harden") == 1.0
    assert _context_weight(node, "integrate") == 1.0


def test_context_weight_no_facts_is_neutral():
    assert _context_weight(_node(source_facts=[]), "harden") == 1.0


# --- _caveat_hint: every key path ---------------------------------------------

def test_caveat_hint_synthesis_kind():
    assert _caveat_hint(_node(kind="synthesis")) == "check validation edge cases security"


def test_caveat_hint_pair_kind():
    assert _caveat_hint(_node(kind="pair")) == "interface boundary coupling refactor"


def test_caveat_hint_unknown_kind_falls_back():
    assert _caveat_hint(_node(kind="facet")) == "interface boundary"


def test_caveat_hint_permutation_operator():
    assert _caveat_hint(_node(kind="permutation", operator="harden")) == \
        "guard validation check sanitize secret"


def test_caveat_hint_permutation_unknown_operator_is_empty():
    assert _caveat_hint(_node(kind="permutation", operator="nonsense")) == ""


def test_caveat_hint_root_uses_fact_label():
    node = _node(kind="permutation", operator="root",
                 source_facts=["untested: m.py"])
    assert _caveat_hint(node) == "check validation edge cases"


def test_caveat_hint_root_unknown_label_is_empty():
    node = _node(kind="permutation", operator="root", source_facts=["mystery: m.py"])
    assert _caveat_hint(node) == ""


# --- convergence helpers ------------------------------------------------------

def test_convergence_labels_extracts_signals():
    node = _node(source_facts=["convergence: untested+security-sensitive+high-churn"])
    assert convergence_labels(node) == ["untested", "security-sensitive", "high-churn"]


def test_convergence_labels_none_when_absent():
    assert convergence_labels(_node(source_facts=["fragile: m.py"])) == []


def test_convergence_plan_orders_and_dedups_by_action():
    # Two coverage labels collapse to one test step (same action); steps come
    # back in phase order: Stabilize before Secure.
    plan = convergence_plan(["untested", "only shallowly tested", "security-sensitive"])
    phases = [step["phase"] for step in plan]
    assert phases == ["Stabilize", "Secure"]
    assert all("step" in s and "action_type" in s for s in plan)


def test_convergence_plan_skips_unknown_labels():
    assert convergence_plan(["totally-unknown"]) == []


def test_join_phrase_variants():
    assert _join_phrase([]) == ""
    assert _join_phrase(["a"]) == "a"
    assert _join_phrase(["a", "b", "c"]) == "a, b and c"


def test_compose_title_capitalizes_chain():
    assert _compose_title("mod.py", ["harden", "test"]) == "Harden → Test: mod.py"


# --- render_markdown: anchors, facets, synth section --------------------------

def _report(ideas: list[IdeaNode]) -> IdeaTreeReport:
    return IdeaTreeReport(
        objective="harden the core",
        project_root="/proj",
        ideas=ideas,
        stats={"total_ideas": len(ideas), "mean_value": 0.5},
    )


def test_render_markdown_root_with_anchors_shows_focus_line():
    root = _node(
        id="r0", title="Harden m.py", branch_path="0", depth=0, operator="root",
        kind="permutation", source_facts=["fragile: m.py"], value=0.7,
        anchors=[{"module": "m.py", "symbol": "m.do_thing", "line": 12,
                  "metric": "cyclomatic 18"}],
    )
    out = render_markdown(_report([root]))
    assert "## 0 — Harden m.py" in out
    assert "_facts: fragile: m.py_" in out
    assert "→ focus:" in out
    assert "`do_thing`" in out
    assert "cyclomatic 18" in out


def test_render_markdown_root_without_anchors_has_no_focus_line():
    root = _node(id="r0", title="Plain", branch_path="0", depth=0, operator="root",
                 kind="permutation", source_facts=["entrypoint: cli.py"], value=0.4)
    out = render_markdown(_report([root]))
    assert "→ focus:" not in out


def test_render_markdown_nested_facet_shows_zoom_and_evidence():
    root = _node(id="r0", title="Harden m.py", branch_path="0", depth=0,
                 operator="root", kind="permutation",
                 source_facts=["fragile: m.py"], value=0.7)
    facet = _node(
        id="f0", title="Harden m.py :: input boundary", branch_path="0.f0",
        depth=1, parent_id="r0", kind="facet", value=0.6,
        operator="harden",
        source_facts=["facet: input boundary", "evidence: 3 unchecked inputs"],
        caveats=["What if the input is empty?"],
    )
    out = render_markdown(_report([root, facet]))
    assert "🔍" in out
    assert "input boundary" in out
    assert "📌 3 unchecked inputs" in out
    assert "⚠ What if the input is empty?" in out


def test_render_markdown_permutation_child_shows_operator_and_caveat():
    root = _node(id="r0", title="Root", branch_path="0", depth=0, operator="root",
                 kind="permutation", source_facts=["fragile: m.py"], value=0.7)
    child = _node(id="c0", title="Harden: m.py", branch_path="0.0", depth=1,
                  parent_id="r0", kind="permutation", operator="harden",
                  source_facts=["fragile: m.py"], value=0.5,
                  caveats=["What if validation is bypassed?"])
    out = render_markdown(_report([root, child]))
    assert "[harden] Harden: m.py" in out
    assert "⚠ What if validation is bypassed?" in out


def test_render_markdown_synth_section_with_convergence_plan():
    conv = _node(
        id="x0", title="Prioritize m.py — 2 independent analyses converge",
        branch_path="x.c0", depth=1, parent_id=None, kind="synthesis",
        operator="synthesis",
        source_facts=["convergence: untested+security-sensitive"], value=0.8,
    )
    out = render_markdown(_report([conv]))
    assert "🔗 Synthesized ideas" in out
    assert "[synthesis]" in out
    # The convergence plan auto-expands into numbered, phase-tagged steps.
    assert "[Stabilize]" in out
    assert "[Secure]" in out
    # Executable steps get a gear, design steps get a hand.
    assert "⚙️" in out


def test_render_markdown_pair_idea_tagged_module_pair():
    pair = _node(id="p0", title="Break the import cycle a → b → a",
                 branch_path="x.p0", depth=1, parent_id=None, kind="pair",
                 operator="synthesis", source_facts=["dependency-cycle"], value=0.6)
    out = render_markdown(_report([pair]))
    assert "[module-pair]" in out


def test_render_markdown_objective_appears_in_meta():
    root = _node(id="r0", title="Root", branch_path="0", depth=0, operator="root",
                 kind="permutation", source_facts=["fragile: m.py"], value=0.5)
    out = render_markdown(_report([root]))
    assert "objective: _harden the core_" in out


# --- render_mermaid: facet label + dangling parent ----------------------------

def test_render_mermaid_facet_node_shows_subconcern():
    facet = _node(id="f0", title="Harden m.py :: input boundary",
                  branch_path="0.f0", depth=1, parent_id="r0", kind="facet",
                  source_facts=["facet: input boundary"], value=0.5)
    out = render_mermaid(_report([facet]))
    assert "flowchart TD" in out
    assert "🔍 input boundary" in out


def test_render_mermaid_dangling_parent_id_draws_no_edge():
    # A child whose parent_id points at no node in the report: the edge is
    # skipped (the parent lookup returns None), but the node still renders.
    orphan = _node(id="c0", title="Orphan", branch_path="0.0", depth=1,
                   parent_id="missing", kind="permutation", operator="harden",
                   source_facts=["fragile: m.py"], value=0.5)
    out = render_mermaid(_report([orphan]))
    assert "Orphan" in out
    assert "-->" not in out  # no edge drawn for the dangling parent


def test_render_mermaid_escapes_quotes_in_title():
    root = _node(id="r0", title='Harden "core"', branch_path="0", depth=0,
                 operator="root", kind="permutation",
                 source_facts=["fragile: m.py"], value=0.5)
    out = render_mermaid(_report([root]))
    assert '"core"' not in out  # double quotes are replaced with single quotes
    assert "'core'" in out


# --- live fractal run: facet-specific caveat path -----------------------------

def _tiny_project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp / "app" / "api.py").write_text(
        "import app.main\n\ndef handler():\n    return app.main.main()\n"
    )
    return tmp


def test_fractal_run_emits_facets_with_specific_caveats(tmp_path):
    # A fractal-facets run zooms the strongest permutation leaves into facet
    # ideas; the facet-scoring path leads each facet's caveat with a stress-test
    # of its own sub-concern (the facet-caveat block), then a lens caveat.
    _tiny_project(tmp_path)
    rep = IdeaPermutationEngine(
        {
            "max_total_ideas": 40,
            "max_idea_depth": 2,
            "breadth": 4,
            "fractal_facets": True,
            "facet_depth": 2,
            "security_aware": False,
        },
        tmp_path,
    ).run()
    facets = [i for i in rep.ideas if i.kind == "facet"]
    assert facets, "expected at least one facet idea from the fractal zoom"
    # Every facet carries a grounded sub-concern fact and a non-empty caveat.
    assert all(any(f.startswith("facet:") for f in fc.source_facts) for fc in facets)
    assert all(fc.caveats for fc in facets)
    # Facets render via the markdown zoom path without error.
    out = render_markdown(rep)
    assert "🔍" in out


def test_run_with_learning_disabled_skips_memory_load(tmp_path):
    # learning=False short-circuits the IdeaMemory.load branch (the False arm of
    # the `if self.learning` guard) — the run still produces a scored tree.
    _tiny_project(tmp_path)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 20, "max_idea_depth": 2, "breadth": 3,
         "learning": False, "security_aware": False},
        tmp_path,
    ).run()
    assert rep.ideas
    assert all(0.0 <= i.value <= 1.0 for i in rep.ideas)


def test_fractal_run_is_deterministic(tmp_path):
    _tiny_project(tmp_path)
    cfg = {
        "max_total_ideas": 30,
        "max_idea_depth": 2,
        "breadth": 3,
        "fractal_facets": True,
        "facet_depth": 2,
        "security_aware": False,
    }
    a = IdeaPermutationEngine(dict(cfg), tmp_path).run()
    b = IdeaPermutationEngine(dict(cfg), tmp_path).run()
    assert [i.title for i in a.ideas] == [i.title for i in b.ideas]
    assert [i.value for i in a.ideas] == [i.value for i in b.ideas]
