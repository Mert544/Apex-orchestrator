from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaPermutationEngine, render_mermaid
from app.models.idea import IdeaTreeReport
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _run_scanners(project_root: str) -> dict[str, dict[str, Any]]:
    """Run the read-only scanner agents and collect their results."""
    from app.agents.skills import (
        DependencyAgent,
        DocstringAgent,
        SecurityAgent,
        TestStubAgent,
    )

    out: dict[str, dict[str, Any]] = {}
    for key, agent in (
        ("security", SecurityAgent()),
        ("docstring", DocstringAgent()),
        ("coverage", TestStubAgent()),
        ("dependency", DependencyAgent()),
    ):
        try:
            out[key] = agent.run(project_root=project_root)
        except Exception as exc:  # a failing scanner must not break the dashboard
            out[key] = {"error": str(exc)}
    return out


def _run_reasoning(project_root: str, objective: str | None) -> dict[str, Any]:
    """Run a small fractal reasoning pass to surface confidence + telemetry."""
    try:
        from app.orchestrator import FractalResearchOrchestrator
        from app.skills.decomposer import Decomposer
        from app.skills.synthesizer import Synthesizer
        from app.skills.validator import Validator

        orch = FractalResearchOrchestrator(
            config={
                "max_depth": 2,
                "max_total_nodes": 12,
                "top_k_questions": 2,
                "min_security": 0.8,
                "min_quality": 0.6,
                "min_novelty": 0.2,
            },
            decomposer=Decomposer(project_root),
            validator=Validator(),
            synthesizer=Synthesizer(),
        )
        report = orch.run(
            objective or "Scan the target project and extract implementation claims."
        )
        return {
            "confidence_map": report.confidence_map,
            "main_findings": report.main_findings,
            "debug_stats": report.debug_stats,
            "estimated_total_tokens": report.estimated_total_tokens,
            "mode": report.mode,
        }
    except Exception as exc:
        return {"error": str(exc)}


def build_dashboard(
    project_root: str,
    objective: str | None = None,
    max_ideas: int = 24,
    idea_depth: int = 2,
    breadth: int = 3,
) -> str:
    """Aggregate profile + scans + ideas/actions + reasoning into one HTML page."""
    profile = ProjectProfiler(project_root).profile()
    findings = _run_scanners(project_root)

    # Plugin-contributed operators widen the idea alphabet (best-effort).
    try:
        from app.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.load_all()
        extra_ops = registry.idea_operators()
    except Exception:
        extra_ops = []

    idea_report = IdeaPermutationEngine(
        {"max_total_ideas": max_ideas, "max_idea_depth": idea_depth, "breadth": breadth},
        project_root,
        extra_operators=extra_ops,
    ).run(objective=objective or None)
    action_plan = IdeaActionBridge().plan_tree(idea_report, top=15)
    reasoning = _run_reasoning(project_root, objective)

    return _render_html(project_root, profile, findings, idea_report, action_plan, reasoning)


# --- rendering (stdlib only, self-contained) --------------------------------

def _esc(value: Any) -> str:
    return html.escape(str(value))


def _chip(label: str, value: Any) -> str:
    return f'<span class="chip"><b>{_esc(value)}</b> {_esc(label)}</span>'


def _profile_section(p: ProjectProfile) -> str:
    chips = "".join(
        [
            _chip("files", p.total_files),
            _chip("entrypoints", len(p.entrypoints)),
            _chip("dependency hubs", len(p.dependency_hubs)),
            _chip("untested modules", len(p.untested_modules)),
            _chip("sensitive paths", len(p.sensitive_paths)),
            _chip("CI files", len(p.ci_files)),
        ]
    )

    def _list(title: str, items: list[str]) -> str:
        if not items:
            return ""
        lis = "".join(f"<li><code>{_esc(i)}</code></li>" for i in items[:8])
        return f"<div class='col'><h4>{_esc(title)}</h4><ul>{lis}</ul></div>"

    cols = "".join(
        [
            _list("Entrypoints", p.entrypoints),
            _list("Dependency hubs", p.dependency_hubs),
            _list("Untested modules", p.untested_modules),
            _list("Sensitive paths", p.sensitive_paths),
        ]
    )
    return f"<section><h2>Project profile</h2><div class='chips'>{chips}</div><div class='cols'>{cols}</div></section>"


def _findings_section(findings: dict[str, dict[str, Any]]) -> str:
    sec = findings.get("security", {})
    doc = findings.get("docstring", {})
    cov = findings.get("coverage", {})
    dep = findings.get("dependency", {})
    chips = "".join(
        [
            _chip("security findings", sec.get("findings_count", "—")),
            _chip("missing docstrings", doc.get("gaps_found", "—")),
            _chip("coverage", f"{int(cov.get('coverage_ratio', 0) * 100)}%" if "coverage_ratio" in cov else "—"),
            _chip("dependency edges", dep.get("total_edges", "—")),
            _chip("circular imports", len(dep.get("circular_imports", []) or [])),
        ]
    )
    rows = ""
    for f in (sec.get("findings", []) or [])[:12]:
        issue = (
            f.get("details")
            or f.get("risk_type")
            or f.get("issue")
            or f.get("risk")
            or ""
        )
        rows += (
            f"<tr><td><code>{_esc(f.get('file', '?'))}:{_esc(f.get('line', '?'))}</code></td>"
            f"<td>{_esc(issue)}</td>"
            f"<td>{_esc(f.get('severity', ''))}</td></tr>"
        )
    table = (
        f"<table><thead><tr><th>Location</th><th>Issue</th><th>Severity</th></tr></thead>"
        f"<tbody>{rows or '<tr><td colspan=3>No security findings.</td></tr>'}</tbody></table>"
    )
    return f"<section><h2>Scan findings</h2><div class='chips'>{chips}</div>{table}</section>"


def _ideas_section(report: IdeaTreeReport) -> str:
    by_parent: dict[str | None, list] = {}
    for idea in report.ideas:
        by_parent.setdefault(idea.parent_id, []).append(idea)

    def walk(idea) -> str:
        children = by_parent.get(idea.id, [])
        caveat = f" <span class='caveat'>⚠ {_esc(idea.caveats[0])}</span>" if idea.caveats else ""
        head = (
            f"<span class='op'>{_esc(idea.operator)}</span> {_esc(idea.title)} "
            f"<span class='val'>v{_esc(idea.value)}</span>{caveat}"
        )
        if children:
            inner = "".join(f"<li>{walk(c)}</li>" for c in children)
            return f"{head}<ul>{inner}</ul>"
        return head

    roots = "".join(f"<li>{walk(r)}</li>" for r in by_parent.get(None, []))
    mermaid = render_mermaid(report).replace("```mermaid", "").replace("```", "").strip()
    return (
        f"<section><h2>Idea permutation tree</h2>"
        f"<p class='muted'>{_esc(report.stats.get('total_ideas', 0))} ideas · mean value "
        f"{_esc(report.stats.get('mean_value', 0))}</p>"
        f"<ul class='tree'>{roots}</ul>"
        f"<details><summary>Mermaid source</summary><pre class='mermaid'>{_esc(mermaid)}</pre></details>"
        f"</section>"
    )


def _actions_section(plan) -> str:
    rows = ""
    for s in plan.steps[:20]:
        tag = "🛠️" if s.executable else "📐"
        draft = ""
        if s.patch_preview:
            draft = f" → <code>{_esc(s.patch_preview.get('transform_type'))}</code>"
        rows += (
            f"<tr><td>{tag}</td><td><code>{_esc(s.branch_path)}</code></td>"
            f"<td>{_esc(s.action_type)}{draft}</td><td>{_esc(s.description)}</td>"
            f"<td>{_esc(s.value)}</td></tr>"
        )
    st = plan.stats
    chips = "".join(
        [
            _chip("steps", st.get("total_steps", 0)),
            _chip("executable", st.get("executable_steps", 0)),
            _chip("design tasks", st.get("design_tasks", 0)),
        ]
    )
    return (
        f"<section><h2>Action plan <span class='muted'>(supervised — not applied)</span></h2>"
        f"<div class='chips'>{chips}</div>"
        f"<table><thead><tr><th></th><th>Branch</th><th>Action</th><th>Description</th><th>Value</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _reasoning_section(r: dict[str, Any]) -> str:
    if "error" in r:
        return f"<section><h2>Reasoning &amp; telemetry</h2><p class='muted'>unavailable: {_esc(r['error'])}</p></section>"
    ds = r.get("debug_stats", {}) or {}
    chips = "".join(
        [
            _chip("mode", r.get("mode", "—")),
            _chip("claims", len(r.get("confidence_map", {}))),
            _chip("mean relevance", ds.get("mean_relevance", "—")),
            _chip("counterfactuals", ds.get("counterfactuals_generated", "—")),
            _chip("drift pruned", ds.get("focus_drift_pruned", "—")),
            _chip("est. tokens", r.get("estimated_total_tokens", "—")),
        ]
    )
    rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(round(v, 3))}</td></tr>"
        for k, v in list(r.get("confidence_map", {}).items())[:10]
    )
    table = (
        f"<table><thead><tr><th>Claim</th><th>Confidence</th></tr></thead>"
        f"<tbody>{rows or '<tr><td colspan=2>No claims.</td></tr>'}</tbody></table>"
    )
    return f"<section><h2>Reasoning &amp; telemetry</h2><div class='chips'>{chips}</div>{table}</section>"


_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}
header{padding:24px 32px;background:#161a23;border-bottom:1px solid #2a2f3a}
h1{margin:0;font-size:20px} h2{font-size:16px;border-bottom:1px solid #2a2f3a;padding-bottom:6px}
.muted{color:#8b93a7;font-weight:normal;font-size:13px}
main{max-width:1000px;margin:0 auto;padding:24px 32px}
section{margin:28px 0}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.chip{background:#1d2230;border:1px solid #2a2f3a;border-radius:14px;padding:4px 10px;font-size:12px}
.chip b{color:#6ea8fe}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #20242e;vertical-align:top}
th{color:#8b93a7;font-weight:600}
code{background:#1d2230;padding:1px 5px;border-radius:4px;font-size:12px;color:#9ad}
ul.tree{list-style:none;padding-left:0} ul.tree ul{border-left:1px solid #2a2f3a;margin-left:10px;padding-left:14px}
ul.tree li{margin:3px 0}
.op{background:#26314a;color:#9cc4ff;border-radius:4px;padding:0 6px;font-size:11px;text-transform:uppercase}
.val{color:#7bd88f;font-size:12px}
.caveat{color:#e0a85e;font-size:12px}
.cols{display:flex;flex-wrap:wrap;gap:24px}.col h4{margin:8px 0 4px;color:#8b93a7;font-size:13px}
.col ul{margin:0;padding-left:18px;font-size:12px}
details summary{cursor:pointer;color:#8b93a7;font-size:13px;margin-top:8px}
pre{background:#1d2230;padding:12px;border-radius:6px;overflow:auto;font-size:12px}
"""


def _render_html(project_root, profile, findings, idea_report, action_plan, reasoning) -> str:
    body = "".join(
        [
            _profile_section(profile),
            _findings_section(findings),
            _ideas_section(idea_report),
            _actions_section(action_plan),
            _reasoning_section(reasoning),
        ]
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Apex Dashboard — {_esc(project_root)}</title><style>{_CSS}</style></head>"
        f"<body><header><h1>🧠 Apex Dashboard</h1>"
        f"<div class='muted'>{_esc(project_root)}</div></header>"
        f"<main>{body}</main></body></html>"
    )
