"""The roadmap renders a per-item "why" line (reasoned plan, not a ranking).

The grounded `rationale` (and seeding fact) already exists on every idea but was
never rendered. The roadmap now surfaces it plus an expected-payoff phrase,
worded to avoid the "imported by"/"LOC" literals so the zero-metric render stays
byte-identical for the negative test.
"""

from __future__ import annotations

from app.engine.idea_roadmap import RoadmapSynthesizer, render_roadmap_markdown
from app.models.idea import IdeaNode, IdeaTreeReport


def _md(node: IdeaNode, stats: dict | None = None) -> str:
    rep = IdeaTreeReport(ideas=[node], stats=stats or {})
    return render_roadmap_markdown(RoadmapSynthesizer().build(rep))


def test_why_line_surfaces_rationale_and_payoff():
    node = IdeaNode(
        id="i", title="Untangle app/x.py", subject="app/x.py", value=0.8,
        rationale="4 independent pressures converge (co-change, hub)",
        source_facts=["confluence: app/x.py"],
    )
    md = _md(node, {"fan_in": {"app/x.py": 9}})
    assert "↳ why: 4 independent pressures converge (co-change, hub)" in md
    assert "protects the 9 module(s) that depend on it" in md
    # The payoff avoids the "imported by" literal (that lives only in the metric).
    assert "depend on it" in md.split("↳ why:")[1]


def test_why_line_falls_back_to_seeding_fact():
    node = IdeaNode(
        id="i", title="Develop app/y.py", subject="app/y.py", value=0.6,
        rationale="", source_facts=["dependency-hub: app/y.py"],
    )
    md = _md(node)
    assert "↳ why: dependency-hub: app/y.py" in md


def test_no_rationale_no_fact_no_payoff_yields_no_why_line():
    node = IdeaNode(id="i", title="Develop app/z.py", subject="app/z.py",
                    value=0.5, rationale="", source_facts=[])
    md = _md(node)
    assert "↳ why:" not in md


def test_why_line_is_deterministic():
    node = IdeaNode(id="i", title="t", subject="app/x.py", value=0.7,
                    rationale="grounded reason", source_facts=["fragile: app/x.py"])
    assert _md(node, {"fan_in": {"app/x.py": 3}}) == _md(node, {"fan_in": {"app/x.py": 3}})
