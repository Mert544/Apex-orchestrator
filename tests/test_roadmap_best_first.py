"""The roadmap surfaces a single "best first move" callout at the top.

The callout is the roadmap-local analogue of the pareto knee: the highest
value-per-effort phased item, biased toward acting early. It is computed only
from the roadmap's own phases (no ``idea_pareto`` import, so no circular-import
risk) and is gated on a real pick, so an empty roadmap renders exactly as before.
"""

from __future__ import annotations

from app.engine.idea_roadmap import (
    RoadmapSynthesizer,
    best_first_move,
    render_roadmap_markdown,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _roadmap(nodes: list[IdeaNode], stats: dict | None = None):
    rep = IdeaTreeReport(ideas=nodes, stats=stats or {})
    return RoadmapSynthesizer().build(rep)


def test_best_first_callout_surfaces_top_value_per_effort_item():
    # A clearly dominant item: high value, very feasible (low effort).
    winner = IdeaNode(
        id="w", title="Cover app/core.py", subject="app/core.py", value=0.95,
        feasibility=0.95, operator="test", source_facts=["critical-untested: app/core.py"],
    )
    loser = IdeaNode(
        id="l", title="Develop app/side.py", subject="app/side.py", value=0.4,
        feasibility=0.3, operator="extend", source_facts=["dependency-hub: app/side.py"],
    )
    rm = _roadmap([winner, loser])
    best = best_first_move(rm)
    assert best is not None
    assert best.branch_path == winner.branch_path

    md = render_roadmap_markdown(rm)
    assert "Best first move" in md
    # The winner's branch path is named in the callout block.
    callout = md.split("Best first move", 1)[1].split("##", 1)[0]
    assert winner.branch_path in callout
    assert "value-per-effort" in callout


def test_best_first_is_picked_from_phased_nodes_not_pareto():
    # best_first_move only looks at roadmap.phases (no idea_pareto coupling).
    node = IdeaNode(
        id="i", title="t", subject="app/x.py", value=0.7, feasibility=0.8,
        operator="test", source_facts=["fragile: app/x.py"],
    )
    rm = _roadmap([node])
    best = best_first_move(rm)
    assert best is not None
    assert best is rm.phases[0].items[0]


def test_ties_break_deterministically_toward_earlier_phase():
    # Two items with identical value/effort ratio but different phases: the
    # earlier phase (Stabilize) must win the tie over a later one (Evolve).
    stabilize = IdeaNode(
        id="s", title="Cover app/a.py", subject="app/a.py", value=0.8,
        feasibility=0.6, operator="test", source_facts=["untested: app/a.py"],
    )
    evolve = IdeaNode(
        id="e", title="Extend app/b.py", subject="app/b.py", value=0.8,
        feasibility=0.6, operator="extend", source_facts=["dependency-hub: app/b.py"],
    )
    # Same feasibility/depth/loc -> same effort; same value -> identical ratio.
    rm = _roadmap([evolve, stabilize])
    best = best_first_move(rm)
    assert best is not None
    assert best.phase == "Stabilize"
    assert best.branch_path == stabilize.branch_path
    # Stable regardless of input order.
    rm2 = _roadmap([stabilize, evolve])
    assert best_first_move(rm2).branch_path == stabilize.branch_path


def test_empty_roadmap_has_no_callout_and_is_unchanged():
    rm = _roadmap([])
    assert best_first_move(rm) is None
    md = render_roadmap_markdown(rm)
    assert "Best first move" not in md
    # Byte-identical to a freshly rendered empty roadmap (no hidden state).
    assert md == render_roadmap_markdown(_roadmap([]))


def test_callout_render_is_deterministic():
    node = IdeaNode(
        id="i", title="Cover app/x.py", subject="app/x.py", value=0.9,
        feasibility=0.9, operator="test", source_facts=["critical-untested: app/x.py"],
    )
    stats = {"fan_in": {"app/x.py": 4}}
    assert render_roadmap_markdown(_roadmap([node], stats)) == \
        render_roadmap_markdown(_roadmap([node], stats))


def test_callout_avoids_magnitude_literals():
    # Wording must stay free of literal magnitude tokens so byte-stable /
    # negative render tests elsewhere keep holding.
    node = IdeaNode(
        id="i", title="Cover app/x.py", subject="app/x.py", value=0.9,
        feasibility=0.9, operator="test", source_facts=["critical-untested: app/x.py"],
    )
    md = render_roadmap_markdown(_roadmap([node], {"fan_in": {"app/x.py": 7}}))
    callout = md.split("Best first move", 1)[1].split("##", 1)[0]
    assert "imported by" not in callout
    assert "LOC" not in callout
    assert "untested" not in callout
