from __future__ import annotations

from app.reporting.reasoning_graph_exporter import (
    ReasoningEdge,
    ReasoningGraph,
    ReasoningGraphExporter,
    ReasoningNode,
)


def test_wrap_label_reflection_uses_rhombus():
    # Covers the reflection branch of _wrap_label (line 97-98).
    assert ReasoningGraphExporter._wrap_label("reflection", "hmm") == '{"hmm"}'


def test_wrap_label_counter_uses_stadium():
    # Covers the counter branch of _wrap_label (line 99-100).
    assert ReasoningGraphExporter._wrap_label("counter", "but") == '(["but"])'


def test_wrap_label_unknown_type_defaults_to_rectangle():
    # Covers the fall-through default of _wrap_label (line 101).
    assert ReasoningGraphExporter._wrap_label("conclusion", "done") == '["done"]'
    assert ReasoningGraphExporter._wrap_label("mystery", "x") == '["x"]'


def test_mermaid_quotes_in_text_are_sanitized():
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text='say "hi"', confidence=0.0)],
    )
    mermaid = ReasoningGraphExporter().to_mermaid(graph)
    # Double quotes replaced with single quotes inside the label.
    assert "say 'hi'" in mermaid
    assert 'say "hi"' not in mermaid


def test_mermaid_edge_with_unknown_endpoints_is_dropped():
    # An edge whose source/target are not in node_map must be skipped (line 85 false).
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text="x")],
        edges=[ReasoningEdge(source="ghost", target="c1", relation="supports")],
    )
    mermaid = ReasoningGraphExporter().to_mermaid(graph)
    assert "ghost" not in mermaid


def test_mermaid_zero_confidence_still_emits_gray_style():
    # _color_for_confidence(0.0) returns "#e5e7eb" which is truthy, so a style is
    # still emitted; assert the gray fill is what we get.
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text="x", confidence=0.0)],
    )
    mermaid = ReasoningGraphExporter().to_mermaid(graph)
    assert "style c1 fill:#e5e7eb" in mermaid


def test_mermaid_direction_is_honored():
    graph = ReasoningGraph()
    assert ReasoningGraphExporter().to_mermaid(graph, direction="LR") == "flowchart LR"


def test_markdown_renders_relations_section():
    # Covers the edges-present branch of to_markdown (lines 121-125).
    graph = ReasoningGraph(
        nodes=[
            ReasoningNode(id="c1", type="claim", text="claim text"),
            ReasoningNode(id="e1", type="evidence", text="evidence text"),
        ],
        edges=[ReasoningEdge(source="e1", target="c1", relation="supports")],
    )
    md = ReasoningGraphExporter().to_markdown(graph)
    assert "### Relations" in md
    assert "`e1` → `c1` (supports)" in md


def test_markdown_node_without_confidence_omits_suffix():
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text="bare", confidence=0.0)],
    )
    md = ReasoningGraphExporter().to_markdown(graph)
    assert "**c1**: bare" in md
    assert "confidence:" not in md


def test_markdown_groups_nodes_by_type():
    graph = ReasoningGraph(
        nodes=[
            ReasoningNode(id="c1", type="claim", text="a"),
            ReasoningNode(id="r1", type="reflection", text="b"),
        ],
    )
    md = ReasoningGraphExporter().to_markdown(graph)
    assert "### Claims" in md
    assert "### Reflections" in md


def test_html_empty_graph_returns_placeholder():
    # Covers the empty-nodes early return of to_html (lines 133-135).
    html = ReasoningGraphExporter().to_html(ReasoningGraph())
    assert "No reasoning steps recorded." in html
    assert html.rstrip().endswith("</div>")


def test_html_renders_relations_list():
    graph = ReasoningGraph(
        nodes=[
            ReasoningNode(id="c1", type="claim", text="a"),
            ReasoningNode(id="e1", type="evidence", text="b"),
        ],
        edges=[ReasoningEdge(source="e1", target="c1", relation="supports")],
    )
    html = ReasoningGraphExporter().to_html(graph)
    assert "<ul" in html
    assert "<code>e1</code>" in html


def test_color_for_confidence_covers_all_bands():
    color = ReasoningGraphExporter._color_for_confidence
    assert color(0.95) == "#fecaca"
    assert color(0.75) == "#fed7aa"   # 0.7 <= c < 0.9 band (line 175)
    assert color(0.55) == "#fef08a"
    assert color(0.35) == "#bfdbfe"   # 0.3 <= c < 0.5 band (line 179)
    assert color(0.1) == "#e5e7eb"


def test_color_for_confidence_band_boundaries():
    color = ReasoningGraphExporter._color_for_confidence
    assert color(0.9) == "#fecaca"
    assert color(0.7) == "#fed7aa"
    assert color(0.5) == "#fef08a"
    assert color(0.3) == "#bfdbfe"


def test_line_style_default_for_unknown_relation():
    assert ReasoningGraphExporter._line_style("whatever") == "-->"
