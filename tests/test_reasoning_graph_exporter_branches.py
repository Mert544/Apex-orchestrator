"""Branch-path coverage for the reasoning graph exporter.

Targets the partial branches left after the existing edge tests:
  - to_html with nodes but no edges (the relations <ul> is skipped, 148->156);
  - to_mermaid's color-skip branch (79->74), which is unreachable because
    _color_for_confidence never returns an empty string -> xfail, see below.
"""

from __future__ import annotations

import pytest

from app.reporting.reasoning_graph_exporter import (
    ReasoningGraph,
    ReasoningGraphExporter,
    ReasoningNode,
)


def test_html_nodes_without_edges_skips_relations_list():
    # Nodes present, no edges -> the <ul> relations block is not emitted.
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text="lone", confidence=0.5)],
        edges=[],
    )
    html = ReasoningGraphExporter().to_html(graph)
    assert "<ul" not in html
    assert "c1" in html
    assert html.strip().endswith("</div>")


@pytest.mark.xfail(
    reason="Unreachable branch: to_mermaid line 79 'if color:' can never be "
    "false because _color_for_confidence always returns a non-empty hex "
    "string (default '#e5e7eb'), so the style line is always emitted.",
    strict=True,
)
def test_mermaid_node_with_no_color_skips_style_line():
    # Every node, regardless of confidence, gets a fill style -> there is no
    # input that exercises the color-falsy path. Asserting its absence fails.
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text="x", confidence=0.0)],
        edges=[],
    )
    mermaid = ReasoningGraphExporter().to_mermaid(graph)
    assert "style c1 fill:" not in mermaid
