from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ReportComposer:
    """Compose human-readable reports from Apex agent results.

    Supports Markdown and HTML output.

    Usage:
        composer = ReportComposer(results)
        composer.to_markdown("report.md")
        composer.to_html("report.html")
    """

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_markdown(self, path: str | Path | None = None) -> str:
        lines = [
            "# Apex Orchestrator Report",
            f"**Generated:** {self.timestamp}",
            f"**Results:** {len(self.results)} agent(s)",
            "",
        ]
        for result in self.results:
            agent_name = result.get("agent", "unknown")
            findings = result.get("findings", [])
            fractal_trees = result.get("fractal_trees", [])
            lines.append(f"## {agent_name}")
            lines.append(f"- **Findings:** {len(findings)}")
            lines.append(f"- **Fractal Analyses:** {len(fractal_trees)}")
            for f in findings:
                sev = f.get("severity", "info")
                icon = "🔴" if sev == "critical" else "🟠" if sev == "high" else "🟡"
                lines.append(f"{icon} **{f.get('issue', 'Unknown')}** — `{f.get('file', '?')}`")
                if "suggestion" in f:
                    lines.append(f"   💡 {f['suggestion']}")
            lines.append("")

            # Fractal 5-Whys trees
            if fractal_trees:
                lines.append("### 🔬 Fractal Deep Analysis")
                for tree in fractal_trees:
                    lines.append(self._render_fractal_tree(tree))
                lines.append("")

            # Reasoning graph
            reasoning_graph = result.get("reasoning_graph")
            if reasoning_graph:
                from app.reporting.reasoning_graph_exporter import ReasoningGraph, ReasoningGraphExporter
                graph = ReasoningGraph.from_dict(reasoning_graph)
                exporter = ReasoningGraphExporter()
                lines.append(exporter.to_markdown(graph))

        md = "\n".join(lines)
        if path:
            Path(path).write_text(md, encoding="utf-8")
        return md

    def _render_fractal_tree(self, tree: dict[str, Any], indent: int = 0) -> str:
        """Render a fractal 5-Whys tree as Markdown."""
        lines = []
        q = tree.get("question", "")
        a = tree.get("answer", "")
        conf = tree.get("confidence", 0.0)
        level = tree.get("level", 1)
        prefix = "  " * indent
        icon = "🔴" if level == 1 else "🟠" if level == 2 else "🟡" if level == 3 else "🔵"
        lines.append(f"{prefix}{icon} **L{level}:** {q}")
        lines.append(f"{prefix}  → {a} (confidence: {conf:.0%})")
        for evidence in tree.get("evidence", []):
            lines.append(f"{prefix}  📎 {evidence}")
        for child in tree.get("children", []):
            lines.append(self._render_fractal_tree(child, indent + 1))
        return "\n".join(lines)

    def _render_fractal_tree_html(self, tree: dict[str, Any], indent: int = 0) -> str:
        """Render a fractal 5-Whys tree as HTML."""
        q = tree.get("question", "")
        a = tree.get("answer", "")
        conf = tree.get("confidence", 0.0)
        level = tree.get("level", 1)
        color = "#dc2626" if level == 1 else "#ea580c" if level == 2 else "#ca8a04" if level == 3 else "#2563eb"
        children_html = ""
        for child in tree.get("children", []):
            children_html += self._render_fractal_tree_html(child, indent + 1)
        evidence_html = ""
        for ev in tree.get("evidence", []):
            evidence_html += f'<div style="color:#666;font-size:0.85rem;margin-left:1rem;">📎 {ev}</div>'
        return f"""
        <div style="margin-left:{indent*1.5}rem;margin-top:0.5rem;padding:0.5rem;border-left:3px solid {color};background:#fafafa;">
            <div style="font-weight:600;color:{color};">L{level}: {q}</div>
            <div style="color:#333;margin-top:0.25rem;">→ {a} (confidence: {conf:.0%})</div>
            {evidence_html}
            {children_html}
        </div>
        """

    def to_html(self, path: str | Path | None = None) -> str:
        findings_html = []
        fractal_html = []
        for result in self.results:
            agent_name = result.get("agent", "unknown")
            findings = result.get("findings", [])
            fractal_trees = result.get("fractal_trees", [])
            for f in findings:
                sev = f.get("severity", "info")
                color = "#dc2626" if sev == "critical" else "#ea580c" if sev == "high" else "#ca8a04"
                findings_html.append(f"""
                <div style="margin:0.5rem 0;padding:0.75rem;border-left:4px solid {color};background:#f9fafb;">
                    <div style="font-weight:600;color:{color};">{f.get('issue', 'Unknown')}</div>
                    <div style="color:#666;font-size:0.9rem;">{f.get('file', '?')}</div>
                    <div style="color:#059669;font-size:0.85rem;margin-top:0.25rem;">{f.get('suggestion', '')}</div>
                </div>
                """)
            for tree in fractal_trees:
                fractal_html.append(self._render_fractal_tree_html(tree))

        fractal_section = ""
        if fractal_html:
            fractal_section = f"""
            <h2 style="margin-top:2rem;">🔬 Fractal Deep Analysis</h2>
            {''.join(fractal_html)}
            """

        reasoning_graph_section = ""
        for result in self.results:
            rg = result.get("reasoning_graph")
            if rg:
                from app.reporting.reasoning_graph_exporter import ReasoningGraph, ReasoningGraphExporter
                graph = ReasoningGraph.from_dict(rg)
                reasoning_graph_section += ReasoningGraphExporter().to_html(graph)

        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Apex Report</title></head>
<body style="font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem;">
<h1>Apex Orchestrator Report</h1>
<p style="color:#666;">Generated: {self.timestamp} | Agents: {len(self.results)}</p>
{''.join(findings_html) if findings_html else '<p style="color:#666;">No findings.</p>'}
{fractal_section}
{reasoning_graph_section}
</body></html>"""

        if path:
            Path(path).write_text(html, encoding="utf-8")
        return html

    def to_sarif(self, path: str | Path | None = None) -> dict[str, Any]:
        """Export as SARIF for GitHub Code Scanning integration."""
        rules = []
        results_sarif = []
        rule_index = {}

        for result in self.results:
            for f in result.get("findings", []):
                rule_id = f.get("issue", "unknown").replace(" ", "_").lower()[:40]
                if rule_id not in rule_index:
                    rule_index[rule_id] = len(rules)
                    rules.append({
                        "id": rule_id,
                        "name": f.get("issue", "Unknown"),
                        "shortDescription": {"text": f.get("issue", "Unknown")},
                    })
                results_sarif.append({
                    "ruleId": rule_id,
                    "level": "error" if f.get("severity") in ("critical", "high") else "warning",
                    "message": {"text": f.get("suggestion", f.get("issue", ""))},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.get("file", "unknown")},
                        }
                    }],
                })

        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "Apex Orchestrator"}},
                "results": results_sarif,
                "rules": rules,
            }],
        }
        if path:
            Path(path).write_text(json.dumps(sarif, indent=2), encoding="utf-8")
        return sarif

    def to_mermaid(self, path: str | Path | None = None) -> str:
        """Export fractal trees as Mermaid flowchart."""
        from app.reporting.mermaid_exporter import FractalMermaidExporter
        exporter = FractalMermaidExporter()
        all_trees: list[dict[str, Any]] = []
        for result in self.results:
            all_trees.extend(result.get("fractal_trees", []))
        if not all_trees:
            return ""
        # Reconstruct FractalNode trees from dicts
        from app.engine.fractal_5whys import FractalNode
        def rebuild(data: dict[str, Any]) -> FractalNode:
            node = FractalNode(
                level=data["level"],
                question=data["question"],
                answer=data["answer"],
                confidence=data["confidence"],
                evidence=data.get("evidence", []),
                counter_evidence=data.get("counter_evidence", []),
                rebuttal=data.get("rebuttal", ""),
                metadata=data.get("metadata", {}),
            )
            for child in data.get("children", []):
                node.children.append(rebuild(child))
            return node
        nodes = [rebuild(t) for t in all_trees]
        mermaid = exporter.export_batch(nodes)
        if path:
            Path(path).write_text(mermaid, encoding="utf-8")
        return mermaid
