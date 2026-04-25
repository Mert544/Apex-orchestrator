from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningNode:
    id: str
    type: str  # claim, evidence, reflection, counter, conclusion
    text: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningEdge:
    source: str
    target: str
    relation: str  # supports, challenges, derives, contradicts
    weight: float = 1.0


@dataclass
class ReasoningGraph:
    nodes: list[ReasoningNode] = field(default_factory=list)
    edges: list[ReasoningEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type,
                    "text": n.text,
                    "confidence": n.confidence,
                    "metadata": n.metadata,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReasoningGraph:
        return cls(
            nodes=[ReasoningNode(**n) for n in data.get("nodes", [])],
            edges=[ReasoningEdge(**e) for e in data.get("edges", [])],
        )


class ReasoningGraphExporter:
    """Export reasoning graphs as Mermaid flowcharts and Markdown.

    Usage:
        graph = ReasoningGraph(nodes=[...], edges=[...])
        exporter = ReasoningGraphExporter()
        mermaid = exporter.to_mermaid(graph)
        md = exporter.to_markdown(graph)
    """

    def to_mermaid(self, graph: ReasoningGraph, direction: str = "TD") -> str:
        lines = [f"flowchart {direction}"]
        node_map = {n.id: n for n in graph.nodes}

        for node in graph.nodes:
            label = node.text.replace('"', "'")[:50]
            wrapped = self._wrap_label(node.type, label)
            color = self._color_for_confidence(node.confidence)
            lines.append(f"    {node.id}{wrapped}")
            if color:
                lines.append(f"    style {node.id} fill:{color}")

        for edge in graph.edges:
            src = node_map.get(edge.source)
            tgt = node_map.get(edge.target)
            if src and tgt:
                line_style = self._line_style(edge.relation)
                lines.append(f"    {edge.source} {line_style}|{edge.relation}| {edge.target}")

        return "\n".join(lines)

    @staticmethod
    def _wrap_label(node_type: str, label: str) -> str:
        if node_type == "claim":
            return f'(("{label}"))'
        if node_type == "evidence":
            return f'(["{label}"])'
        if node_type == "reflection":
            return f'{{"{label}"}}'
        if node_type == "counter":
            return f'(["{label}"])'
        return f'["{label}"]'

    def to_markdown(self, graph: ReasoningGraph) -> str:
        lines = ["## Reasoning Graph", ""]
        if not graph.nodes:
            lines.append("_No reasoning steps recorded._")
            return "\n".join(lines)

        # Group by type
        by_type: dict[str, list[ReasoningNode]] = {}
        for node in graph.nodes:
            by_type.setdefault(node.type, []).append(node)

        for ntype, nodes in by_type.items():
            lines.append(f"### {ntype.capitalize()}s")
            for node in nodes:
                conf_str = f" (confidence: {node.confidence:.0%})" if node.confidence else ""
                lines.append(f"- **{node.id}**: {node.text}{conf_str}")
            lines.append("")

        if graph.edges:
            lines.append("### Relations")
            for edge in graph.edges:
                lines.append(f"- `{edge.source}` → `{edge.target}` ({edge.relation})")
            lines.append("")

        return "\n".join(lines)

    def to_html(self, graph: ReasoningGraph) -> str:
        lines = ['<div style="font-family:system-ui,sans-serif;margin:1rem 0;">']
        lines.append("<h3>Reasoning Graph</h3>")
        if not graph.nodes:
            lines.append("<p><em>No reasoning steps recorded.</em></p>")
            lines.append("</div>")
            return "\n".join(lines)

        for node in graph.nodes:
            color = self._color_for_confidence(node.confidence)
            border = self._border_for_type(node.type)
            lines.append(
                f'<div style="margin:0.5rem 0;padding:0.75rem;border-left:4px solid {border};'
                f'background:{color or "#f9fafb"};border-radius:4px;">'
                f'<div style="font-weight:600;font-size:0.9rem;">{node.id} <span style="color:#666;">({node.type})</span></div>'
                f'<div style="margin-top:0.25rem;">{node.text}</div>'
                f'</div>'
            )

        if graph.edges:
            lines.append("<ul style='margin-top:0.5rem;'>")
            for edge in graph.edges:
                lines.append(
                    f"<li><code>{edge.source}</code> → <code>{edge.target}</code> ({edge.relation})</li>"
                )
            lines.append("</ul>")

        lines.append("</div>")
        return "\n".join(lines)

    @staticmethod
    def _shape_for_type(node_type: str) -> str:
        shapes = {
            "claim": "((",
            "evidence": "[(",
            "reflection": "{{",
            "counter": "[(",
            "conclusion": "[",
        }
        return shapes.get(node_type, "[")

    @staticmethod
    def _color_for_confidence(confidence: float) -> str:
        if confidence >= 0.9:
            return "#fecaca"
        elif confidence >= 0.7:
            return "#fed7aa"
        elif confidence >= 0.5:
            return "#fef08a"
        elif confidence >= 0.3:
            return "#bfdbfe"
        return "#e5e7eb"

    @staticmethod
    def _border_for_type(node_type: str) -> str:
        borders = {
            "claim": "#dc2626",
            "evidence": "#16a34a",
            "reflection": "#2563eb",
            "counter": "#ea580c",
            "conclusion": "#7c3aed",
        }
        return borders.get(node_type, "#9ca3af")

    @staticmethod
    def _line_style(relation: str) -> str:
        if relation in ("challenges", "contradicts"):
            return "-.->"
        if relation == "derives":
            return "==>"
        return "-->"
