from __future__ import annotations

from app.engine.idea_explain import (
    explain_idea,
    render_explanation_markdown,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _report(node: IdeaNode) -> IdeaTreeReport:
    return IdeaTreeReport(ideas=[node])


def _base_node(**overrides) -> IdeaNode:
    data = dict(
        id="i",
        title="Reduce churn in scanner",
        subject="app/tools/project_profile.py",
        branch_path="x.a",
        operator="refactor",
        operator_chain=["refactor"],
        value=0.5,
        source_facts=["churn-hot: app/tools/project_profile.py"],
    )
    data.update(overrides)
    return IdeaNode(**data)


def _with_anchors(node: IdeaNode, anchors: list[dict]) -> IdeaNode:
    # anchors is a not-yet-present field on IdeaNode; attach it on the object so
    # explain_idea reads it via getattr, exercising the defensive path.
    object.__setattr__(node, "anchors", anchors)
    return node


def test_focus_line_names_symbol_line_and_metric():
    node = _with_anchors(
        _base_node(),
        [{"module": "app/tools/project_profile.py", "symbol": "_scan_churn",
          "line": 550, "metric": "cyclomatic 18"}],
    )
    md = render_explanation_markdown(explain_idea(_report(node), "x.a"))
    assert "## Where (the concrete locus)" in md
    assert "**Focus:** `_scan_churn` (app/tools/project_profile.py:550, cyclomatic 18)" in md


def test_rationale_woven_in_when_present():
    node = _base_node(rationale="hottest file by commit count over the last quarter")
    md = render_explanation_markdown(explain_idea(_report(node), "x.a"))
    assert "## Where (the concrete locus)" in md
    assert "hottest file by commit count over the last quarter" in md


def test_anchors_and_rationale_together():
    node = _with_anchors(
        _base_node(rationale="hottest file by commit count"),
        [{"module": "app/tools/project_profile.py", "symbol": "_scan_churn",
          "line": 550, "metric": "cyclomatic 18"}],
    )
    md = render_explanation_markdown(explain_idea(_report(node), "x.a"))
    assert "`_scan_churn` (app/tools/project_profile.py:550, cyclomatic 18)" in md
    assert "hottest file by commit count" in md


def test_multiple_anchors_preserve_order():
    node = _with_anchors(
        _base_node(),
        [
            {"module": "app/a.py", "symbol": "first", "line": 1, "metric": "loc 10"},
            {"module": "app/b.py", "symbol": "second", "line": 2, "metric": "loc 20"},
        ],
    )
    md = render_explanation_markdown(explain_idea(_report(node), "x.a"))
    assert "**Focus:** `first` (app/a.py:1, loc 10)" in md
    assert "- also: `second` (app/b.py:2, loc 20)" in md
    assert md.index("first") < md.index("second")


def test_no_anchors_no_rationale_is_byte_identical_to_legacy():
    node = _base_node()
    exp = explain_idea(_report(node), "x.a")
    md = render_explanation_markdown(exp)
    # The "Where" section must be entirely absent.
    assert "## Where" not in md
    assert "Focus:" not in md

    # Reconstruct the exact legacy render (the body without the Where block) and
    # assert equality, proving byte-identical output when no locus is available.
    legacy = _legacy_render(exp)
    assert md == legacy


def test_empty_anchor_entries_are_dropped():
    node = _with_anchors(
        _base_node(),
        [{"module": "", "symbol": "", "line": None, "metric": ""}, "junk", 42],
    )
    exp = explain_idea(_report(node), "x.a")
    assert exp.anchors == []
    md = render_explanation_markdown(exp)
    assert "## Where" not in md


def test_anchor_with_only_metric_renders():
    node = _with_anchors(
        _base_node(),
        [{"module": "", "symbol": "", "line": None, "metric": "duplication 4 clones"}],
    )
    md = render_explanation_markdown(explain_idea(_report(node), "x.a"))
    assert "**Focus:** (duplication 4 clones)" in md


def test_anchor_with_symbol_only_omits_parens():
    node = _with_anchors(
        _base_node(),
        [{"symbol": "lonely_fn"}],
    )
    md = render_explanation_markdown(explain_idea(_report(node), "x.a"))
    assert "**Focus:** `lonely_fn`" in md
    assert "`lonely_fn` (" not in md


def test_determinism_same_input_same_output():
    def build():
        return _with_anchors(
            _base_node(rationale="churn"),
            [{"module": "app/x.py", "symbol": "f", "line": 9, "metric": "cc 7"}],
        )

    a = render_explanation_markdown(explain_idea(_report(build()), "x.a"))
    b = render_explanation_markdown(explain_idea(_report(build()), "x.a"))
    assert a == b


def _legacy_render(exp) -> str:
    """The pre-anchors render: identical to render_explanation_markdown minus the
    Where block. Used to prove byte-identical output when no locus is present."""
    lines = [f"# Why `{exp.branch_path}` — {exp.title}", ""]
    lines.append(f"**Subject:** `{exp.subject}`  ·  **kind:** {exp.kind}  ·  **depth:** {exp.depth}")
    if exp.operator_chain:
        lines.append(f"**Lens chain:** {' → '.join(exp.operator_chain)}")
    lines.append("")
    lines.append("## Provenance (what grounds this idea)")
    for fact in exp.source_facts:
        lines.append(f"- {fact}")
    lines.append("")
    lines.append("## Score breakdown")
    lines.append(f"- **Relevance:** {exp.relevance}")
    lines.append(f"- **Novelty:** {exp.novelty} — {exp.novelty_explanation}")
    lines.append(f"- **Feasibility:** {exp.feasibility} — {exp.feasibility_explanation}")
    lines.append(f"- **Value:** `{exp.value_formula}`")
    lines.append("")
    lines.append("## Roadmap placement")
    lines.append(f"- **Phase:** {exp.phase or '—'}")
    lines.append(f"- **Impact:** {exp.impact} — {exp.impact_explanation}")
    lines.append(f"- **Effort:** {exp.effort} — {exp.effort_explanation}")
    lines.append(f"- **ROI:** {exp.roi}  (impact ÷ effort)")
    lines.append("")
    lines.append("## Acting on it")
    kind = "executable by Apex" if exp.executable else "a design task for a human"
    lines.append(f"- **{exp.action_type}** ({kind}) — {exp.action_description}")
    lines.append("")
    if exp.caveats:
        lines.append("## Caveats (counterfactual stress-tests)")
        for c in exp.caveats:
            lines.append(f"- ⚠ {c}")
        lines.append("")
    return "\n".join(lines)
