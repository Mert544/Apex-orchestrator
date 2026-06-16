from __future__ import annotations

from app.engine.fractal_5whys import FractalNode
from app.reporting.mermaid_exporter import FractalMermaidExporter


def test_color_for_confidence_mid_band_is_yellow():
    # 0.5 <= confidence < 0.7 returns yellow-200 (mermaid_exporter line 60),
    # the band the existing tests skip over.
    exporter = FractalMermaidExporter()
    assert exporter._color_for_confidence(0.6) == "#fef08a"
    assert exporter._color_for_confidence(0.5) == "#fef08a"


def test_color_for_confidence_full_band_table():
    exporter = FractalMermaidExporter()
    assert exporter._color_for_confidence(0.9) == "#fecaca"
    assert exporter._color_for_confidence(0.7) == "#fed7aa"
    assert exporter._color_for_confidence(0.3) == "#bfdbfe"


def test_walk_sanitizes_double_quotes_in_answer():
    exporter = FractalMermaidExporter()
    node = FractalNode(level=1, question="Q?", answer='he said "no"', confidence=1.0)
    mermaid = exporter.export(node)
    assert "he said 'no'" in mermaid
    assert 'he said "no"' not in mermaid


def test_walk_emits_style_line_for_confident_node():
    exporter = FractalMermaidExporter()
    node = FractalNode(level=1, question="Q?", answer="A", confidence=1.0)
    mermaid = exporter.export(node)
    assert "style " in mermaid
    assert "fill:#fecaca" in mermaid


def test_export_uses_requested_direction():
    exporter = FractalMermaidExporter()
    node = FractalNode(level=1, question="Q?", answer="A", confidence=1.0)
    assert exporter.export(node, direction="LR").startswith("flowchart LR")


def test_walk_links_parent_to_child_at_each_level():
    # Three nested levels exercise the parent --> child edge emission and the
    # level-3 stadium shape.
    exporter = FractalMermaidExporter()
    root = FractalNode(level=1, question="Q1?", answer="A1", confidence=1.0)
    mid = FractalNode(level=2, question="Q2?", answer="A2", confidence=0.8)
    leaf = FractalNode(level=3, question="Q3?", answer="A3", confidence=0.4)
    mid.children.append(leaf)
    root.children.append(mid)
    mermaid = exporter.export(root)
    # Two parent->child edges for three nested nodes.
    assert mermaid.count("-->") == 2
    assert "[(" in mermaid  # level-3 stadium shape


def test_export_batch_uses_question_as_subgraph_title():
    exporter = FractalMermaidExporter()
    trees = [FractalNode(level=1, question="Root cause?", answer="A1", confidence=1.0)]
    mermaid = exporter.export_batch(trees, direction="LR")
    assert mermaid.startswith("flowchart LR")
    assert "subgraph Finding_0 [Root cause?]" in mermaid
    assert mermaid.rstrip().endswith("end")
