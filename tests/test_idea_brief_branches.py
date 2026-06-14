"""Branch-path coverage for work-brief building and markdown rendering.

Targets the partial branches left after the existing edge tests:
  - build_brief when fan_in is absent (the blast-radius done-when is skipped);
  - render_brief_markdown when a brief has no measured stats and no why.
"""

from __future__ import annotations

from app.engine.idea_brief import Brief, build_brief, render_brief_markdown
from app.models.idea import IdeaNode, IdeaTreeReport


def _design_node() -> IdeaNode:
    # operator not in _FACETS and label not in _LABEL_LENS -> lens "extend";
    # a design-level (non-executable) idea so it is a brief candidate.
    return IdeaNode(
        id="n1",
        title="evolve the orphan",
        subject="app/orphan.py",
        rationale="",
        branch_path="extend.orphan",
        operator="root",
        source_facts=["mystery-label: nothing measured here"],
        value=1.0,
    )


def test_build_brief_omits_blast_radius_when_no_fan_in():
    # No fan_in / metrics in stats -> measured stays empty and the
    # "importing module(s)" done-when line is NOT inserted (144->148).
    report = IdeaTreeReport(objective="", ideas=[_design_node()], stats={})
    report.project_root = "/nonexistent"
    brief = build_brief(report)
    assert brief is not None
    assert brief.measured == {}
    assert not any("importing module(s)" in d for d in brief.done_when)
    # The standard three done-when lines remain.
    assert any("--roadmap --diff" in d for d in brief.done_when)


def test_render_brief_markdown_without_measured_or_why():
    # measured falsy -> the Measured line is skipped (256->259);
    # why empty -> the "Why this, why now" section is skipped (260->264).
    brief = Brief(
        branch_path="extend.orphan",
        title="evolve the orphan",
        subject="app/orphan.py",
        operator="extend",
        why=[],
        measured={},
        plan=[("extend", ["new capability"])],
        phased_steps=[],
        done_when=["`pytest -q` stays green."],
        evidence={},
    )
    md = render_brief_markdown(brief)
    assert "**Measured:**" not in md
    assert "## Why this, why now" not in md
    # The work plan and definition-of-done still render.
    assert "## Work plan (the fractal vocabulary as a checklist)" in md
    assert "- **extend**" in md
    assert "- [ ] new capability" in md
