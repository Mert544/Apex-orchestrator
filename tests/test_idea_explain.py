from __future__ import annotations

from app.engine.idea_explain import (
    IdeaExplanation,
    explain_idea,
    render_explanation_markdown,
)
from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode, IdeaTreeReport


def _report(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "app" / "user.py").write_text("import app.core\ndef u():\n    return app.core.run('1')\n")
    return IdeaPermutationEngine(
        {"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 4}, tmp_path
    ).run()


def test_explain_returns_full_reasoning(tmp_path):
    rep = _report(tmp_path)
    top = max(rep.ideas, key=lambda i: i.value)
    exp = explain_idea(rep, top.branch_path)
    assert isinstance(exp, IdeaExplanation)
    assert exp.branch_path == top.branch_path
    assert exp.source_facts  # provenance present
    assert "value =" in exp.value_formula
    assert 0.0 <= exp.value <= 1.0
    assert exp.action_type  # mapped to an action


def test_explain_unknown_branch_returns_none(tmp_path):
    rep = _report(tmp_path)
    assert explain_idea(rep, "x.does.not.exist") is None


def test_explain_root_novelty_message(tmp_path):
    rep = _report(tmp_path)
    root = next(i for i in rep.ideas if i.operator == "root")
    exp = explain_idea(rep, root.branch_path)
    assert "maximally novel" in exp.novelty_explanation
    assert exp.novelty == 1.0


def test_explain_formula_reflects_objective_presence(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run(
        objective="improve security"
    )
    top = max(rep.ideas, key=lambda i: i.value)
    exp = explain_idea(rep, top.branch_path)
    assert "0.4·relevance" in exp.value_formula  # objective present -> 0.4 weight


def test_explain_includes_measured_signals(tmp_path):
    rep = _report(tmp_path)
    # core.py is imported by user.py -> fan-in surfaces in the impact explanation.
    core = next((i for i in rep.ideas if i.subject == "app/core.py"), None)
    assert core is not None
    exp = explain_idea(rep, core.branch_path)
    assert "blast radius" in exp.impact_explanation
    assert "LOC" in exp.effort_explanation


def test_render_explanation_markdown_sections(tmp_path):
    rep = _report(tmp_path)
    top = max(rep.ideas, key=lambda i: i.value)
    md = render_explanation_markdown(explain_idea(rep, top.branch_path))
    for heading in ("Provenance", "Score breakdown", "Roadmap placement", "Acting on it"):
        assert heading in md


def test_explain_to_dict_roundtrips():
    ideas = [IdeaNode(id="i", title="t", subject="app/x.py", branch_path="x.a",
                      operator="test", operator_chain=["test"], value=0.5,
                      source_facts=["untested: app/x.py"])]
    rep = IdeaTreeReport(ideas=ideas)
    exp = explain_idea(rep, "x.a")
    d = exp.to_dict()
    assert d["branch_path"] == "x.a" and "value_formula" in d
