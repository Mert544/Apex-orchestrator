from __future__ import annotations

from pathlib import Path

from app.reporting.reasoning_graph_exporter import (
    ReasoningEdge,
    ReasoningGraph,
    ReasoningGraphExporter,
    ReasoningNode,
)


def test_empty_graph_mermaid():
    graph = ReasoningGraph()
    exporter = ReasoningGraphExporter()
    mermaid = exporter.to_mermaid(graph)
    assert mermaid == "flowchart TD"


def test_graph_mermaid_with_nodes_and_edges():
    graph = ReasoningGraph(
        nodes=[
            ReasoningNode(id="c1", type="claim", text="eval() is dangerous", confidence=0.9),
            ReasoningNode(id="e1", type="evidence", text="Found in auth.py", confidence=1.0),
        ],
        edges=[
            ReasoningEdge(source="e1", target="c1", relation="supports"),
        ],
    )
    exporter = ReasoningGraphExporter()
    mermaid = exporter.to_mermaid(graph)
    assert "flowchart TD" in mermaid
    assert "c1((\"eval() is dangerous\"))" in mermaid
    assert "e1([\"Found in auth.py\"])" in mermaid
    assert "e1 -->|supports| c1" in mermaid


def test_graph_markdown():
    graph = ReasoningGraph(
        nodes=[
            ReasoningNode(id="c1", type="claim", text="eval() is dangerous", confidence=0.9),
        ],
        edges=[],
    )
    exporter = ReasoningGraphExporter()
    md = exporter.to_markdown(graph)
    assert "## Reasoning Graph" in md
    assert "eval() is dangerous" in md
    assert "confidence: 90%" in md


def test_graph_html():
    graph = ReasoningGraph(
        nodes=[
            ReasoningNode(id="c1", type="claim", text="eval() is dangerous", confidence=0.9),
            ReasoningNode(id="e1", type="evidence", text="Found in auth.py", confidence=1.0),
        ],
        edges=[
            ReasoningEdge(source="e1", target="c1", relation="supports"),
        ],
    )
    exporter = ReasoningGraphExporter()
    html = exporter.to_html(graph)
    assert "Reasoning Graph" in html
    assert "c1" in html
    assert "e1" in html
    assert "supports" in html


def test_graph_roundtrip_dict():
    graph = ReasoningGraph(
        nodes=[ReasoningNode(id="c1", type="claim", text="x", confidence=0.5)],
        edges=[ReasoningEdge(source="c1", target="c2", relation="derives")],
    )
    data = graph.to_dict()
    restored = ReasoningGraph.from_dict(data)
    assert len(restored.nodes) == 1
    assert restored.nodes[0].text == "x"
    assert len(restored.edges) == 1


def test_line_styles():
    exporter = ReasoningGraphExporter()
    assert exporter._line_style("supports") == "-->"
    assert exporter._line_style("challenges") == "-.->"
    assert exporter._line_style("contradicts") == "-.->"
    assert exporter._line_style("derives") == "==>"


def test_shapes_and_colors():
    exporter = ReasoningGraphExporter()
    assert exporter._shape_for_type("claim") == "(("
    assert exporter._shape_for_type("evidence") == "[("
    assert exporter._color_for_confidence(0.95) == "#fecaca"
    assert exporter._color_for_confidence(0.1) == "#e5e7eb"
    assert exporter._border_for_type("reflection") == "#2563eb"


def test_empty_graph_markdown():
    graph = ReasoningGraph()
    exporter = ReasoningGraphExporter()
    md = exporter.to_markdown(graph)
    assert "No reasoning steps recorded" in md


def test_report_composer_integration(tmp_path: Path):
    from app.reporting.composer import ReportComposer

    results = [
        {
            "agent": "security",
            "findings": [{"issue": "eval()", "severity": "critical", "file": "app/auth.py"}],
            "reasoning_graph": ReasoningGraph(
                nodes=[
                    ReasoningNode(id="c1", type="claim", text="eval() is dangerous", confidence=0.9),
                ],
                edges=[],
            ).to_dict(),
        },
    ]
    composer = ReportComposer(results)
    # ReportComposer does not auto-render reasoning_graphs yet, but data is preserved
    md = composer.to_markdown()
    assert "eval()" in md
