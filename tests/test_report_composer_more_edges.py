from __future__ import annotations

from pathlib import Path

from app.reporting.composer import ReportComposer


def _reasoning_graph() -> dict:
    """A minimal but valid reasoning-graph dict (nodes + edges)."""
    return {
        "nodes": [
            {"id": "n1", "type": "claim", "text": "Root claim", "confidence": 0.9},
            {"id": "n2", "type": "evidence", "text": "Supporting fact", "confidence": 0.8},
        ],
        "edges": [
            {"source": "n2", "target": "n1", "relation": "supports", "weight": 1.0},
        ],
    }


def test_markdown_includes_reasoning_graph_section(tmp_path: Path):
    # Exercises the reasoning_graph branch in to_markdown (lines 56-59).
    results = [
        {"agent": "reasoner", "findings": [], "reasoning_graph": _reasoning_graph()},
    ]
    md = ReportComposer(results).to_markdown(tmp_path / "r.md")
    # The exporter's markdown text is appended verbatim; node text should appear.
    assert "Root claim" in md
    assert "Supporting fact" in md


def test_html_includes_reasoning_graph_section(tmp_path: Path):
    # Exercises the reasoning_graph branch in to_html (lines 136-138).
    results = [
        {"agent": "reasoner", "findings": [], "reasoning_graph": _reasoning_graph()},
    ]
    html = ReportComposer(results).to_html(tmp_path / "r.html")
    assert "Root claim" in html
    assert "Supporting fact" in html


def test_html_fractal_tree_renders_nested_children(tmp_path: Path):
    # Exercises _render_fractal_tree_html child recursion (line 92) and the
    # level>3 (blue) color branch.
    results = [
        {"agent": "fractal", "findings": [], "fractal_trees": [
            {"level": 1, "question": "Q1", "answer": "A1", "confidence": 1.0,
             "evidence": ["top-ev"], "children": [
                {"level": 4, "question": "Q4", "answer": "A4", "confidence": 0.5,
                 "evidence": [], "children": []},
            ]},
        ]},
    ]
    html = ReportComposer(results).to_html(tmp_path / "r.html")
    assert "L1: Q1" in html
    assert "L4: Q4" in html
    # The deep (level 4) node uses the blue color.
    assert "#2563eb" in html


def test_to_mermaid_returns_empty_when_no_trees():
    # Exercises the early-return guard in to_mermaid (line 202).
    composer = ReportComposer([{"agent": "x", "findings": []}])
    assert composer.to_mermaid() == ""


def test_to_mermaid_returns_empty_for_empty_results():
    assert ReportComposer([]).to_mermaid() == ""
