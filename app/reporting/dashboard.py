from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaPermutationEngine, render_mermaid
from app.models.idea import IdeaTreeReport
from app.tools.project_profile import ProjectProfile, ProjectProfiler


# --- data gathering ---------------------------------------------------------

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


def _git_info(project_root: str) -> dict[str, Any]:
    """Best-effort local git status (offline). Empty dict if not a repo."""
    import subprocess

    def _run(args: list[str]) -> str:
        try:
            out = subprocess.run(
                ["git", *args], cwd=project_root, capture_output=True, text=True, timeout=5
            )
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception:
            return ""

    if _run(["rev-parse", "--is-inside-work-tree"]) != "true":
        return {}
    porcelain = _run(["status", "--porcelain"])
    return {
        "branch": _run(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commits": [c for c in _run(["log", "--oneline", "-5"]).splitlines() if c],
        "dirty": len([line for line in porcelain.splitlines() if line.strip()]),
        "total_commits": _run(["rev-list", "--count", "HEAD"]),
    }


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
    git = _git_info(project_root)

    return _render_html(project_root, profile, findings, idea_report, action_plan, reasoning, git)


# --- rendering (stdlib only, self-contained, professional) ------------------

def _esc(value: Any) -> str:
    return html.escape(str(value))


def _severity_badge(sev: str) -> str:
    sev = (sev or "").lower()
    cls = {
        "critical": "sev-crit",
        "high": "sev-high",
        "medium": "sev-med",
        "low": "sev-low",
    }.get(sev, "sev-none")
    return f"<span class='badge {cls}'>{_esc(sev or 'n/a')}</span>"


def _kpi(label: str, value: Any, accent: str = "", sub: str = "") -> str:
    sub_html = f"<div class='kpi-sub'>{_esc(sub)}</div>" if sub else ""
    return (
        f"<div class='kpi'><div class='kpi-val {accent}'>{_esc(value)}</div>"
        f"<div class='kpi-label'>{_esc(label)}</div>{sub_html}</div>"
    )


def _card(section_id: str, icon: str, title: str, inner: str) -> str:
    return (
        f"<section id='{section_id}' class='card'>"
        f"<h2><span class='ico'>{icon}</span>{title}</h2>{inner}</section>"
    )


def _overview(profile, findings, idea_report, action_plan, git) -> str:
    sec = findings.get("security", {})
    cov = findings.get("coverage", {})
    doc = findings.get("docstring", {})
    cov_pct = int(cov.get("coverage_ratio", 0) * 100) if "coverage_ratio" in cov else None
    sec_n = sec.get("findings_count", 0) or 0
    cards = [
        _kpi("Files", profile.total_files, "a-blue"),
        _kpi("Security findings", sec_n, "a-red" if sec_n else "a-green"),
        _kpi("Coverage", f"{cov_pct}%" if cov_pct is not None else "—", "a-amber"),
        _kpi("Missing docs", doc.get("gaps_found", "—"), "a-amber"),
        _kpi("Ideas", idea_report.stats.get("total_ideas", 0), "a-violet"),
        _kpi("Action steps", action_plan.stats.get("total_steps", 0), "a-blue",
             sub=f"{action_plan.stats.get('executable_steps', 0)} executable"),
    ]
    if git:
        cards.append(_kpi("Uncommitted", git.get("dirty", 0), "a-amber", sub=f"on {git.get('branch', '?')}"))
    return f"<section id='overview' class='overview'><div class='kpis'>{''.join(cards)}</div></section>"


def _repo_section(git: dict[str, Any]) -> str:
    if not git:
        return ""
    chips = "".join(
        [
            _chip("branch", git.get("branch", "—")),
            _chip("commits", git.get("total_commits", "—")),
            _chip("uncommitted files", git.get("dirty", 0)),
        ]
    )
    commits = "".join(f"<li><code>{_esc(c)}</code></li>" for c in git.get("commits", []))
    body = f"<ul class='commits'>{commits}</ul>" if commits else ""
    return _card("repository", "🌿", "Repository", f"<div class='chips'>{chips}</div>{body}")


def _chip(label: str, value: Any) -> str:
    return f"<span class='chip'><b>{_esc(value)}</b> {_esc(label)}</span>"


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
    return _card("profile", "📦", "Project profile", f"<div class='chips'>{chips}</div><div class='cols'>{cols}</div>")


def _coverage_bar(cov: dict[str, Any]) -> str:
    if "coverage_ratio" not in cov:
        return ""
    pct = int(cov.get("coverage_ratio", 0) * 100)
    tone = "bar-good" if pct >= 70 else "bar-warn" if pct >= 30 else "bar-bad"
    return (
        f"<div class='bar-wrap'><div class='bar-label'>Test coverage "
        f"<b>{pct}%</b></div><div class='bar'><div class='bar-fill {tone}' "
        f"style='width:{pct}%'></div></div></div>"
    )


def _findings_section(findings: dict[str, dict[str, Any]]) -> str:
    sec = findings.get("security", {})
    doc = findings.get("docstring", {})
    cov = findings.get("coverage", {})
    dep = findings.get("dependency", {})
    chips = "".join(
        [
            _chip("security findings", sec.get("findings_count", "—")),
            _chip("missing docstrings", doc.get("gaps_found", "—")),
            _chip("dependency edges", dep.get("total_edges", "—")),
            _chip("circular imports", len(dep.get("circular_imports", []) or [])),
        ]
    )
    rows = ""
    for f in (sec.get("findings", []) or [])[:12]:
        issue = (
            f.get("details") or f.get("risk_type") or f.get("issue") or f.get("risk") or ""
        )
        rows += (
            f"<tr><td><code>{_esc(f.get('file', '?'))}:{_esc(f.get('line', '?'))}</code></td>"
            f"<td>{_esc(issue)}</td><td>{_severity_badge(f.get('severity', ''))}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Location</th><th>Issue</th><th>Severity</th></tr></thead>"
        f"<tbody>{rows or '<tr><td colspan=3 class=empty>No security findings 🎉</td></tr>'}</tbody></table>"
    )
    inner = f"<div class='chips'>{chips}</div>{_coverage_bar(cov)}{table}"
    return _card("findings", "🔍", "Scan findings", inner)


def _ideas_section(report: IdeaTreeReport) -> str:
    by_parent: dict[str | None, list] = {}
    for idea in report.ideas:
        by_parent.setdefault(idea.parent_id, []).append(idea)

    def walk(idea) -> str:
        children = by_parent.get(idea.id, [])
        caveat = f" <span class='caveat'>⚠ {_esc(idea.caveats[0])}</span>" if idea.caveats else ""
        head = (
            f"<span class='op'>{_esc(idea.operator)}</span> {_esc(idea.title)} "
            f"<span class='val'>{_esc(idea.value)}</span>{caveat}"
        )
        if children:
            inner = "".join(f"<li>{walk(c)}</li>" for c in children)
            return f"{head}<ul>{inner}</ul>"
        return head

    roots = "".join(f"<li>{walk(r)}</li>" for r in by_parent.get(None, []))
    mermaid = render_mermaid(report).replace("```mermaid", "").replace("```", "").strip()
    inner = (
        f"<p class='muted'>{_esc(report.stats.get('total_ideas', 0))} ideas · mean value "
        f"{_esc(report.stats.get('mean_value', 0))}</p>"
        f"<ul class='tree'>{roots}</ul>"
        f"<details><summary>Mermaid source</summary><pre>{_esc(mermaid)}</pre></details>"
    )
    return _card("ideas", "💡", "Idea permutation tree", inner)


def _actions_section(plan) -> str:
    rows = ""
    for s in plan.steps[:20]:
        pill = "<span class='pill exec'>executable</span>" if s.executable else "<span class='pill design'>design</span>"
        draft = f" → <code>{_esc(s.patch_preview.get('transform_type'))}</code>" if s.patch_preview else ""
        rows += (
            f"<tr><td>{pill}</td><td><code>{_esc(s.branch_path)}</code></td>"
            f"<td>{_esc(s.action_type)}{draft}</td><td>{_esc(s.description)}</td>"
            f"<td class='num'>{_esc(s.value)}</td></tr>"
        )
    st = plan.stats
    chips = "".join(
        [
            _chip("steps", st.get("total_steps", 0)),
            _chip("executable", st.get("executable_steps", 0)),
            _chip("design tasks", st.get("design_tasks", 0)),
        ]
    )
    inner = (
        "<p class='muted'>Supervised — proposed, never applied.</p>"
        f"<div class='chips'>{chips}</div>"
        "<table><thead><tr><th>Type</th><th>Branch</th><th>Action</th><th>Description</th><th>Value</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _card("actions", "🛠️", "Action plan", inner)


def _reasoning_section(r: dict[str, Any]) -> str:
    if "error" in r:
        return _card("reasoning", "🧠", "Reasoning &amp; telemetry",
                     f"<p class='muted'>unavailable: {_esc(r['error'])}</p>")
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
        f"<tr><td>{_esc(k)}</td><td class='num'>{_esc(round(v, 3))}</td></tr>"
        for k, v in list(r.get("confidence_map", {}).items())[:10]
    )
    table = (
        "<table><thead><tr><th>Claim</th><th>Confidence</th></tr></thead>"
        f"<tbody>{rows or '<tr><td colspan=2 class=empty>No claims.</td></tr>'}</tbody></table>"
    )
    return _card("reasoning", "🧠", "Reasoning &amp; telemetry", f"<div class='chips'>{chips}</div>{table}")


_CSS = """
:root{--bg:#f6f7fb;--card:#fff;--ink:#1c2230;--muted:#6b7280;--line:#e7e9f0;
--accent:#5b6cff;--accent2:#7c5cff;--radius:14px;--shadow:0 1px 3px rgba(20,30,60,.06),0 8px 24px rgba(20,30,60,.05)}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}
a{color:inherit;text-decoration:none}
.nav{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.85);backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);padding:12px 28px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{font-weight:700;font-size:16px;display:flex;align-items:center;gap:8px}
.brand .dot{background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.nav .path{color:var(--muted);font-size:13px;font-family:ui-monospace,monospace}
.nav .links{margin-left:auto;display:flex;gap:14px;flex-wrap:wrap}
.nav .links a{font-size:13px;color:var(--muted);padding:4px 0;border-bottom:2px solid transparent}
.nav .links a:hover{color:var(--accent);border-color:var(--accent)}
.hero{background:linear-gradient(135deg,#5b6cff,#7c5cff);color:#fff;padding:30px 28px 64px}
.hero h1{margin:0 0 4px;font-size:22px}.hero p{margin:0;opacity:.85;font-size:14px}
main{max-width:1080px;margin:-44px auto 48px;padding:0 28px;display:flex;flex-direction:column;gap:20px}
.overview .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
.kpi-val{font-size:28px;font-weight:700;line-height:1}
.kpi-label{color:var(--muted);font-size:13px;margin-top:6px}
.kpi-sub{color:var(--muted);font-size:11px;margin-top:2px}
.a-blue{color:#3b5bff}.a-red{color:#e5484d}.a-green{color:#30a46c}.a-amber{color:#e09b16}.a-violet{color:#8e4ec6}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px;box-shadow:var(--shadow)}
.card h2{margin:0 0 14px;font-size:16px;display:flex;align-items:center;gap:9px}
.card h2 .ico{font-size:18px}
.muted{color:var(--muted);font-size:13px;margin:0 0 12px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.chip{background:#f1f3fb;border:1px solid var(--line);border-radius:20px;padding:5px 12px;font-size:12px;color:var(--muted)}
.chip b{color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
tbody tr:hover{background:#fafbff}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.empty{color:var(--muted);text-align:center;padding:18px}
code{background:#f1f3fb;padding:2px 6px;border-radius:5px;font-size:12px;font-family:ui-monospace,monospace;color:#4250c5}
.badge{font-size:11px;padding:2px 9px;border-radius:20px;font-weight:600;text-transform:capitalize}
.sev-crit{background:#fdecee;color:#c62828}.sev-high{background:#fdf0e6;color:#d2691e}
.sev-med{background:#fbf6e3;color:#9a7b14}.sev-low{background:#eef1f6;color:#5b6472}.sev-none{background:#eef1f6;color:#8a909c}
.pill{font-size:11px;padding:2px 9px;border-radius:20px;font-weight:600}
.pill.exec{background:#e7f6ee;color:#1c7a48}.pill.design{background:#eef1fb;color:#4250c5}
.bar-wrap{margin:4px 0 16px}.bar-label{font-size:13px;color:var(--muted);margin-bottom:5px}
.bar{height:9px;background:#eef1f6;border-radius:6px;overflow:hidden}
.bar-fill{height:100%;border-radius:6px}.bar-good{background:#30a46c}.bar-warn{background:#e09b16}.bar-bad{background:#e5484d}
ul.tree{list-style:none;padding-left:0;margin:0}
ul.tree ul{border-left:2px solid var(--line);margin-left:11px;padding-left:16px}
ul.tree li{margin:5px 0;font-size:13px}
.op{background:linear-gradient(135deg,#eef0ff,#f3eefe);color:#5346c9;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.03em}
.val{color:#30a46c;font-size:12px;font-weight:600}
.caveat{color:#c77d20;font-size:12px}
.cols{display:flex;flex-wrap:wrap;gap:28px}.col h4{margin:6px 0 4px;color:var(--muted);font-size:13px}
.col ul{margin:0;padding-left:18px;font-size:12px}.commits{margin:8px 0;padding-left:18px;font-size:12px;color:var(--muted)}
details summary{cursor:pointer;color:var(--muted);font-size:13px;margin-top:10px}
pre{background:#0f1117;color:#cdd3e0;padding:14px;border-radius:8px;overflow:auto;font-size:12px;margin-top:8px}
footer{text-align:center;color:var(--muted);font-size:12px;padding:8px 0 36px}
@media(max-width:640px){.nav .links{display:none}.hero{padding-bottom:54px}main{margin-top:-40px}}
"""


def _render_html(project_root, profile, findings, idea_report, action_plan, reasoning, git=None) -> str:
    git = git or {}
    nav_links = [("overview", "Overview"), ("findings", "Findings"), ("ideas", "Ideas"),
                 ("actions", "Actions"), ("reasoning", "Reasoning"), ("profile", "Profile")]
    if git:
        nav_links.append(("repository", "Repo"))
    links = "".join(f"<a href='#{i}'>{_esc(t)}</a>" for i, t in nav_links)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections = "".join(
        [
            _overview(profile, findings, idea_report, action_plan, git),
            _findings_section(findings),
            _ideas_section(idea_report),
            _actions_section(action_plan),
            _reasoning_section(reasoning),
            _profile_section(profile),
            _repo_section(git),
        ]
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Apex Dashboard — {_esc(project_root)}</title><style>{_CSS}</style></head><body>"
        f"<nav class='nav'><span class='brand'><span class='dot'>🧠 Apex</span></span>"
        f"<span class='path'>{_esc(project_root)}</span><span class='links'>{links}</span></nav>"
        f"<header class='hero'><h1>Project Dashboard</h1>"
        f"<p>Code intelligence, development ideas &amp; supervised actions · generated {generated}</p></header>"
        f"<main>{sections}</main>"
        "<footer>Generated by Apex Orchestrator — deterministic, offline, self-contained.</footer>"
        "</body></html>"
    )
