"""Branch / edge coverage for app.engine.idea_roadmap.

These tests close the gaps left by the existing roadmap suites: the synthesis
theme-with-unrecognised-lens fallback, the harden-on-a-secure-label override
inside the test-first branch, the outcome-rate entry that lacks a key, and the
markdown rendering of quick wins and per-item measured metrics (fan-in / LOC).

All inputs are constructed explicitly (small IdeaNode / IdeaTreeReport / a fake
memory); no time, randomness, or order-dependent assertions.
"""

from __future__ import annotations


from app.engine.idea_roadmap import (
    EVOLVE,
    SECURE,
    RoadmapSynthesizer,
    _outcome_rates,
    classify_phase,
    render_roadmap_markdown,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _node(**kw) -> IdeaNode:
    # Mirror tests/test_idea_roadmap.py: realistic sub-1.0 structural axes so the
    # impact seed isn't saturated by the model defaults.
    base = dict(id="i", title="t", subject="s", relevance=0.5, novelty=0.5,
                value=0.6, feasibility=0.6, depth=1)
    base.update(kw)
    return IdeaNode(**base)


# --- classify_phase: synthesis-theme + override branches ----------------------

def test_synthesis_theme_unknown_lens_falls_back_to_evolve():
    # A synthesis theme whose lens is none of test/harden/refine drops through to
    # the catch-all EVOLVE (line 241).
    node = _node(kind="synthesis", operator="synthesis",
                 operator_chain=["extend"],
                 source_facts=["theme: capability-theme (4 modules)"])
    assert classify_phase(node) == EVOLVE


def test_synthesis_theme_empty_chain_falls_back_to_evolve():
    # No operator_chain -> lens is "" -> still routes to the EVOLVE fallback.
    node = _node(kind="synthesis", operator="synthesis",
                 operator_chain=[],
                 source_facts=["theme: misc-theme (2 modules)"])
    assert classify_phase(node) == EVOLVE


def test_harden_on_sensitive_path_classifies_secure():
    # A harden lens whose first fact is a sensitive-path (secure) label is a
    # Secure action. The secure and stabilize label sets are disjoint, so it
    # bypasses the stabilize-first block and is classified by the `op=='harden'`
    # rule. (This previously had a dead duplicate override inside the stabilize
    # block, since removed.)
    node = _node(operator="harden",
                 source_facts=["sensitive-path: app/auth.py",
                               "untested: app/auth.py"])
    assert classify_phase(node) == SECURE


# --- _outcome_rates: entry missing a key --------------------------------------

def test_outcome_rates_skips_entry_without_key():
    # A summary whose reliability tracks contain an entry lacking "key" must be
    # skipped, not crash (line 287). The keyed entry still lands in the map.
    class _Mem:
        def summary(self):
            return {
                "most_reliable": [
                    {"success_rate": 0.9, "samples": 5},          # no key -> skipped
                    {"key": "extend", "success_rate": 0.8, "samples": 4},
                ],
                "least_reliable": [],
            }

    rates = _outcome_rates(_Mem())
    assert "extend" in rates
    assert rates["extend"] == {"success_rate": 0.8, "samples": 4}
    # The keyless entry contributed nothing.
    assert len(rates) == 1


# --- render_roadmap_markdown: quick wins + measured metrics -------------------

def test_render_markdown_renders_quick_wins_section():
    # A high-ROI idea (cheap + structurally impactful) clears the quick-win floor,
    # so the markdown emits the quick-wins block (lines 419-425).
    ideas = [
        _node(id="qw", branch_path="x.qw", title="add tests", operator="test",
              subject="app/m.py", value=0.9, feasibility=0.95,
              source_facts=["fragile: app/m.py (high in-degree, thin tests)"]),
    ]
    rm = RoadmapSynthesizer(quick_win_min_roi=1.0).build(IdeaTreeReport(ideas=ideas))
    assert rm.quick_wins, "fixture must yield at least one quick win"
    md = render_roadmap_markdown(rm)
    assert "Quick wins" in md
    qw = rm.quick_wins[0]
    assert f"`{qw.branch_path}`" in md
    assert qw.title in md
    assert f"ROI {qw.roi}" in md


def test_render_markdown_shows_measured_fan_in_and_loc():
    # When the engine supplied fan_in and metrics.loc, the per-item line surfaces
    # the measured clauses "imported by N" (line 434) and "N LOC" (line 436).
    ideas = [
        _node(id="hub", branch_path="x.hub", title="harden core",
              operator="harden", subject="app/core.py", value=0.6, feasibility=0.6,
              source_facts=["sensitive-path: app/core.py"]),
    ]
    rep = IdeaTreeReport(ideas=ideas, stats={
        "fan_in": {"app/core.py": 7},
        "metrics": {"app/core.py": {"loc": 320, "complexity": 12}},
    })
    rm = RoadmapSynthesizer().build(rep)
    md = render_roadmap_markdown(rm)
    assert "imported by 7" in md
    assert "320 LOC" in md


def test_render_markdown_omits_measured_clauses_when_absent():
    # With no fan_in / loc the measured suffix is empty: neither clause appears.
    ideas = [
        _node(id="plain", branch_path="x.plain", title="document config",
              operator="document", subject="app/conf.py", value=0.4, feasibility=0.85,
              source_facts=["config: app/conf.py"]),
    ]
    rm = RoadmapSynthesizer().build(IdeaTreeReport(ideas=ideas))
    md = render_roadmap_markdown(rm)
    assert "imported by" not in md
    assert "LOC" not in md
