from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
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
    # Roadmap (sequenced plan) + tree-shape telemetry over the same idea tree.
    try:
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = RoadmapSynthesizer().build(idea_report)
    except Exception:
        roadmap = None
    try:
        from app.engine.idea_tree_shape import analyze_tree_shape

        shape = analyze_tree_shape(idea_report)
    except Exception:
        shape = None
    # Efficient frontier, self-improvement trajectory, and learned memory.
    try:
        from app.engine.idea_pareto import frontier_from_roadmap

        pareto = frontier_from_roadmap(roadmap) if roadmap is not None else []
    except Exception:
        pareto = []
    try:
        from app.engine.evolution import load_history

        trajectory = load_history(project_root)
    except Exception:
        trajectory = []
    try:
        from app.engine.idea_memory import IdeaMemory

        learned = IdeaMemory.load(project_root).summary()
    except Exception:
        learned = None
    reasoning = _run_reasoning(project_root, objective)
    git = _git_info(project_root)
    debug = _run_debug(project_root, profile)

    # What `apex auto` would decide for this project, right now.
    try:
        from app.policies.autonomy_policy import AutonomyPolicy

        tree_clean = bool(git) and int(git.get("dirty", 0) or 0) == 0
        autonomy = AutonomyPolicy().decide(
            executable_steps=action_plan.stats.get("executable_steps", 0),
            working_tree_clean=tree_clean,
        ).to_dict()
        autonomy["executable"] = action_plan.stats.get("executable_steps", 0)
    except Exception:
        autonomy = None

    return _render_html(
        project_root, profile, findings, idea_report, action_plan, reasoning, git, debug,
        roadmap=roadmap, shape=shape, autonomy=autonomy,
        pareto=pareto, trajectory=trajectory, learned=learned,
    )


def _run_debug(project_root: str, profile) -> dict[str, Any]:
    """Run a lightweight debug trace so the dashboard surfaces anomalies."""
    try:
        from app.engine.debug_engine import DebugEngine

        debug = DebugEngine(project_root, enabled=True)
        debug.trace("dashboard", "debug snapshot for dashboard")
        debug.snapshot(
            branch_map={d: 1 for d in profile.top_directories},
            telemetry={"total_files": profile.total_files},
        )
        report = debug.report()
        return {
            "trace_count": report.get("trace_count", 0),
            "anomalies": report.get("anomalies", []),
            "pattern_issues": report.get("pattern_issues", []),
            "total_time_sec": report.get("total_time_sec", 0),
        }
    except Exception as exc:
        return {"error": str(exc)}


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
    cycles_n = len(getattr(profile, "import_cycles", []) or [])
    cards = [
        _kpi("Files", profile.total_files, "a-blue"),
        _kpi("Security findings", sec_n, "a-red" if sec_n else "a-green"),
        _kpi("Coverage", f"{cov_pct}%" if cov_pct is not None else "—", "a-amber"),
        _kpi("Import cycles", cycles_n, "a-red" if cycles_n else "a-green"),
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


def _debug_section(debug: dict[str, Any]) -> str:
    if not debug:
        return ""
    if "error" in debug:
        return _card("debug", "🐞", "Debug", f"<p class='muted'>unavailable: {_esc(debug['error'])}</p>")
    anomalies = debug.get("anomalies", []) or []
    patterns = debug.get("pattern_issues", []) or []
    chips = "".join(
        [
            _chip("traces", debug.get("trace_count", 0)),
            _chip("anomalies", len(anomalies)),
            _chip("pattern issues", len(patterns)),
            _chip("time (s)", debug.get("total_time_sec", 0)),
        ]
    )
    items = anomalies + patterns
    if items:
        lis = "".join(f"<li>{_esc(i)}</li>" for i in items[:10])
        body = f"<ul class='commits'>{lis}</ul>"
    else:
        body = "<p class='muted'>No anomalies detected 🎉</p>"
    return _card("debug", "🐞", "Debug", f"<div class='chips'>{chips}</div>{body}")


def _chip(label: str, value: Any) -> str:
    return f"<span class='chip'><b>{_esc(value)}</b> {_esc(label)}</span>"


def _profile_section(p: ProjectProfile) -> str:
    churn = getattr(p, "churn_hotspots", []) or []
    debt_ages = getattr(p, "debt_marker_ages", {}) or {}
    chips = "".join(
        [
            _chip("files", p.total_files),
            _chip("entrypoints", len(p.entrypoints)),
            _chip("dependency hubs", len(p.dependency_hubs)),
            _chip("untested modules", len(p.untested_modules)),
            _chip("sensitive paths", len(p.sensitive_paths)),
            _chip("churn hotspots", len(churn)),
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
            _list("Change hotspots (git churn)",
                  [f"{c['module']} · {c['commits']} commits" for c in churn]),
            _list("Stale debt (oldest marker)",
                  [f"{m} · ~{d // 30} months" for m, d in sorted(
                      debt_ages.items(), key=lambda kv: -kv[1]) if d >= 90]),
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


def _findings_section(findings: dict[str, dict[str, Any]], project_root: str = "") -> str:
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
    shown = (sec.get("findings", []) or [])[:12]
    # Exposure context: how long each finding has sat in the code, and whether
    # an entrypoint can reach it — the development context that turns a
    # finding into a decision. Best-effort: absent git/graph renders "—".
    exposures: list[str] = []
    if project_root and shown:
        try:
            from app.engine.exposure import analyze_exposure

            pairs = [(str(f.get("file", "")), int(f.get("line", 0) or 0)) for f in shown]
            exposures = [e.describe() or "—" for e in analyze_exposure(project_root, pairs)]
        except Exception:
            exposures = []
    rows = ""
    for i, f in enumerate(shown):
        issue = (
            f.get("details") or f.get("risk_type") or f.get("issue") or f.get("risk") or ""
        )
        exposure = exposures[i] if i < len(exposures) else "—"
        rows += (
            f"<tr><td><code>{_esc(f.get('file', '?'))}:{_esc(f.get('line', '?'))}</code></td>"
            f"<td>{_esc(issue)}</td><td>{_severity_badge(f.get('severity', ''))}</td>"
            f"<td>{_esc(exposure)}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Location</th><th>Issue</th><th>Severity</th><th>Exposure</th></tr></thead>"
        f"<tbody>{rows or '<tr><td colspan=4 class=empty>No security findings 🎉</td></tr>'}</tbody></table>"
    )
    inner = f"<div class='chips'>{chips}</div>{_coverage_bar(cov)}{table}"
    return _card("findings", "🔍", "Scan findings", inner)


def _architecture_section(p: ProjectProfile) -> str:
    """Surface architectural risks the engine sees: import cycles + fragility."""
    cycles = getattr(p, "import_cycles", []) or []
    fragile = getattr(p, "fragile_modules", []) or []
    if not cycles and not fragile:
        return _card(
            "architecture", "🏛️", "Architecture health",
            "<p class='muted'>No import cycles or fragile hubs detected 🎉</p>",
        )
    chips = "".join(
        [
            _chip("import cycles", len(cycles)),
            _chip("fragile modules", len(fragile)),
            _chip("dependency edges", len(getattr(p, "dependency_edges", []) or [])),
        ]
    )
    body = ""
    if cycles:
        items = "".join(f"<li><code>{_esc(' → '.join(c))}</code></li>" for c in cycles[:5])
        body += f"<h4 style='margin:12px 0 4px'>🔄 Import cycles</h4><ul class='commits'>{items}</ul>"
    if fragile:
        items = "".join(
            f"<li>{_kind_badge_label('fragile')} <code>{_esc(m)}</code> "
            f"<span class='muted'>(high in-degree, thin tests)</span></li>"
            for m in fragile[:5]
        )
        body += f"<h4 style='margin:12px 0 4px'>⚠️ Fragile modules</h4><ul class='commits'>{items}</ul>"
    return _card("architecture", "🏛️", "Architecture health", f"<div class='chips'>{chips}</div>{body}")


def _kind_badge_label(label: str) -> str:
    if label == "fragile":
        return "<span class='ibadge b-frag'>fragile</span>"
    return ""


def _kind_badge(idea) -> str:
    """A small badge marking fragility roots and synthesized/pair ideas."""
    label = idea.source_facts[0].split(":")[0].strip() if idea.source_facts else ""
    if idea.kind == "synthesis":
        return "<span class='ibadge b-synth'>synthesis</span>"
    if idea.kind == "pair":
        return "<span class='ibadge b-pair'>module-pair</span>"
    if label == "fragile":
        return "<span class='ibadge b-frag'>fragile</span>"
    return ""


def _ideas_section(report: IdeaTreeReport) -> str:
    by_parent: dict[str | None, list] = {}
    for idea in report.ideas:
        by_parent.setdefault(idea.parent_id, []).append(idea)

    # Synthesis/pair ideas are parentless; facets are parented (render nested).
    synth = [i for i in report.ideas if i.kind != "permutation" and i.parent_id is None]
    synth_ids = {i.id for i in synth}
    perm_roots = [
        i for i in by_parent.get(None, [])
        if i.kind == "permutation" and i.id not in synth_ids
    ]

    def walk(idea) -> str:
        children = by_parent.get(idea.id, [])
        caveat = f" <span class='caveat'>⚠ {_esc(idea.caveats[0])}</span>" if idea.caveats else ""
        head = (
            f"<span class='op'>{_esc(idea.operator)}</span> {_esc(idea.title)} "
            f"{_kind_badge(idea)}<span class='val'>{_esc(idea.value)}</span>{caveat}"
        )
        if children:
            inner = "".join(f"<li>{walk(c)}</li>" for c in children)
            return f"{head}<ul>{inner}</ul>"
        return head

    roots = "".join(f"<li>{walk(r)}</li>" for r in perm_roots)
    mermaid = render_mermaid(report).replace("```mermaid", "").replace("```", "").strip()

    synth_html = ""
    if synth:
        items = "".join(
            f"<li>{_kind_badge(i)} {_esc(i.title)} "
            f"<span class='val'>{_esc(i.value)}</span></li>"
            for i in sorted(synth, key=lambda n: n.value, reverse=True)
        )
        synth_html = (
            "<h4 style='margin:14px 0 4px'>🔗 Synthesized &amp; module-pair ideas</h4>"
            f"<ul class='commits'>{items}</ul>"
        )

    inner = (
        f"<p class='muted'>{_esc(report.stats.get('total_ideas', 0))} ideas · mean value "
        f"{_esc(report.stats.get('mean_value', 0))} · "
        f"{_esc(report.stats.get('synthesized', 0))} synthesized</p>"
        f"<ul class='tree'>{roots}</ul>"
        f"{synth_html}"
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


_PHASE_TONE = {
    "Stabilize": "ph-stab", "Secure": "ph-sec", "Evolve": "ph-evo", "Refine": "ph-ref",
}


def _roadmap_section(roadmap) -> str:
    """Render the sequenced engineering roadmap (phases + quick wins)."""
    if roadmap is None or not getattr(roadmap, "phases", None):
        return ""
    st = roadmap.stats
    chips = "".join(
        [_chip("ideas sequenced", st.get("total_items", 0)),
         _chip("mean ROI", st.get("mean_roi", 0)),
         _chip("quick wins", st.get("quick_win_count", 0))]
        + [_chip(p.name, len(p.items)) for p in roadmap.phases]
    )

    qw = ""
    if roadmap.quick_wins:
        items = "".join(
            f"<li><span class='ibadge b-qw'>⚡ quick win</span> {_esc(i.title)} "
            f"<span class='val'>ROI {_esc(i.roi)}</span> "
            f"<span class='muted'>impact {_esc(i.impact)} · effort {_esc(i.effort)}</span></li>"
            for i in roadmap.quick_wins
        )
        qw = f"<h4 style='margin:6px 0 4px'>⚡ Quick wins</h4><ul class='commits'>{items}</ul>"

    phases_html = ""
    for n, phase in enumerate(roadmap.phases, start=1):
        tone = _PHASE_TONE.get(phase.name, "")
        rows = ""
        for i in phase.items[:8]:
            roi_pct = max(4, min(100, int(i.roi / 10 * 100)))  # ROI is bounded ~0..10
            measured = []
            if getattr(i, "fan_in", 0):
                measured.append(f"imported by {i.fan_in}")
            if getattr(i, "loc", 0):
                measured.append(f"{i.loc} LOC")
            sub = f"<div class='muted' style='margin:0'>{_esc(' · '.join(measured))}</div>" if measured else ""
            rows += (
                f"<tr><td><code>{_esc(i.branch_path)}</code></td>"
                f"<td>{_esc(i.title)}{sub}</td>"
                f"<td class='num'>{_esc(i.impact)}</td>"
                f"<td class='num'>{_esc(i.effort)}</td>"
                f"<td><div class='roi'><span style='width:{roi_pct}%'></span></div>"
                f"<b>{_esc(i.roi)}</b></td></tr>"
            )
        phases_html += (
            f"<div class='phase'><h4><span class='ibadge {tone}'>Phase {n}</span> "
            f"{_esc(phase.name)} <span class='muted'>— {_esc(phase.theme)}</span></h4>"
            "<table><thead><tr><th>Branch</th><th>Idea</th><th>Impact</th>"
            "<th>Effort</th><th>ROI</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )

    inner = f"<div class='chips'>{chips}</div>{qw}{phases_html}"
    return _card("roadmap", "🗺️", "Engineering roadmap", inner)


def _shape_section(shape) -> str:
    """Render idea-tree shape telemetry + the engine's own observations."""
    if shape is None or shape.total_ideas == 0:
        return ""
    kinds = " · ".join(f"{k} {v}" for k, v in sorted(shape.by_kind.items()))
    depths = " ".join(f"d{d}:{n}" for d, n in shape.depth_distribution.items())
    chip_specs = [
        _chip("ideas", shape.total_ideas),
        _chip("max depth", shape.max_depth),
        _chip("branching", shape.branching_factor),
        _chip("subjects", shape.distinct_subjects),
        _chip("facets", f"{int(shape.facet_penetration * 100)}%"),
        _chip("distinct values", shape.distinct_values),
    ]
    if shape.total_measured_loc > 0:
        chip_specs.append(_chip("heaviest", f"{shape.heaviest_module} ({shape.heaviest_loc} LOC)"))
    chips = "".join(chip_specs)
    obs = "".join(f"<li>{_esc(o)}</li>" for o in shape.observations)
    inner = (
        f"<div class='chips'>{chips}</div>"
        f"<p class='muted'>kinds: {_esc(kinds)} · depth: {_esc(depths)} · "
        f"top subject <code>{_esc(shape.top_subject)}</code> "
        f"({int(shape.top_subject_share * 100)}%)</p>"
        f"<h4 style='margin:6px 0 4px'>Observations</h4><ul class='commits'>{obs}</ul>"
    )
    return _card("shape", "📐", "Idea-tree shape", inner)


def _autonomy_section(autonomy: dict[str, Any] | None) -> str:
    """What `apex auto` would do for this project, and why."""
    if not autonomy:
        return ""
    act = autonomy.get("act")
    verdict = "✅ would apply autonomously" if act else "📋 would recommend only"
    tone = "ph-stab" if act else "ph-ref"
    chips = "".join([
        _chip("decision", "apply" if act else "recommend"),
        _chip("mode", autonomy.get("mode", "—")),
        _chip("safe fixes", autonomy.get("executable", 0)),
    ])
    body = (
        f"<div class='chips'>{chips}</div>"
        f"<p><span class='ibadge {tone}'>{verdict}</span></p>"
        f"<p class='muted'>{_esc(autonomy.get('reason', ''))}</p>"
        "<p class='muted'>Run <code>apex auto</code> to act on this · "
        "<code>apex auto --recommend</code> to keep it read-only.</p>"
    )
    return _card("autonomy", "🤖", "Autonomy", body)


def _pareto_section(points: list[Any], total_ideas: int) -> str:
    """The efficient frontier — ideas not dominated on impact/effort/value."""
    if not points:
        return ""
    dominated = max(0, total_ideas - len(points))
    chips = "".join([
        _chip("on the frontier", len(points)),
        _chip("dominated", dominated),
        _chip("of total", total_ideas),
    ])
    rows = ""
    for p in points[:12]:
        rows += (
            f"<tr><td><code>{_esc(p.branch_path)}</code></td><td>{_esc(p.title)}</td>"
            f"<td>{_esc(', '.join(p.reasons))}</td>"
            f"<td class='num'>{_esc(p.impact)}</td><td class='num'>{_esc(p.effort)}</td>"
            f"<td class='num'>{_esc(p.roi)}</td></tr>"
        )
    body = (
        f"<div class='chips'>{chips}</div>"
        "<p class='muted'>Each is the best choice for some trade-off; everything else is "
        "strictly beaten on impact, effort, and value at once.</p>"
        "<table><thead><tr><th>Branch</th><th>Idea</th><th>Why</th>"
        "<th>Impact</th><th>Effort</th><th>ROI</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _card("frontier", "🎯", "Efficient frontier", body)


def _trajectory_section(history: list[dict[str, Any]]) -> str:
    """The project's self-improvement trajectory across recorded evolve runs."""
    if not history:
        return ""
    first, last = history[0], history[-1]

    def _f(e: dict[str, Any], side: str, key: str) -> Any:
        return (e.get(side) or {}).get(key, "—")

    chips = "".join([
        _chip("runs", len(history)),
        _chip("findings", f"{_f(first, 'before', 'security_findings')} → {_f(last, 'after', 'security_findings')}"),
        _chip("open fixes", f"{_f(first, 'before', 'executable_fixes')} → {_f(last, 'after', 'executable_fixes')}"),
    ])
    rows = "".join(
        f"<tr><td>{_esc(e.get('ts', '?'))}</td><td class='num'>{_esc(e.get('applied', 0))}</td>"
        f"<td>{_esc(_f(e, 'before', 'security_findings'))}→{_esc(_f(e, 'after', 'security_findings'))}</td>"
        f"<td>{_esc(e.get('mode', '?'))}</td></tr>"
        for e in history[-10:]
    )
    body = (
        f"<div class='chips'>{chips}</div>"
        "<table><thead><tr><th>When</th><th>Applied</th><th>Findings</th><th>Mode</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _card("trajectory", "📈", "Self-improvement trajectory", body)


def _learned_section(learned: dict[str, Any] | None) -> str:
    """What the engine has learned about which fixes land on this project."""
    if not learned or not (learned.get("most_reliable") or learned.get("least_reliable")):
        return ""
    def _items(rows: list[dict[str, Any]]) -> str:
        return "".join(
            f"<li><code>{_esc(r['key'])}</code> — {int(r['success_rate'] * 100)}% "
            f"<span class='muted'>({r['samples']} samples)</span></li>" for r in rows
        )
    body = (
        f"<div class='chips'>{_chip('lenses tracked', learned.get('operators_tracked', 0))}"
        f"{_chip('facts tracked', learned.get('labels_tracked', 0))}</div>"
        "<div class='cols'>"
        f"<div class='col'><h4>Most reliable here</h4><ul>{_items(learned.get('most_reliable', []))}</ul></div>"
        f"<div class='col'><h4>Least reliable here</h4><ul>{_items(learned.get('least_reliable', []))}</ul></div>"
        "</div>"
    )
    return _card("learned", "🧠", "What Apex has learned", body)


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
.ibadge{font-size:10px;font-weight:700;border-radius:6px;padding:1px 7px;margin:0 4px;text-transform:uppercase;letter-spacing:.03em}
.b-synth{background:#e8f0fe;color:#2d5fd0}.b-pair{background:#eef9f0;color:#1c7a48}.b-frag{background:#fdecee;color:#c62828}
.b-qw{background:#fff5d9;color:#9a7b14}
.ph-stab{background:#e7f6ee;color:#1c7a48}.ph-sec{background:#fdecee;color:#c62828}
.ph-evo{background:#e8f0fe;color:#2d5fd0}.ph-ref{background:#f3eefe;color:#7c3aed}
.phase{margin:10px 0 16px}.phase h4{margin:0 0 6px;font-size:13px;font-weight:600}
.roi{display:inline-block;width:60px;height:7px;background:#eef1f6;border-radius:5px;overflow:hidden;margin-right:6px;vertical-align:middle}
.roi span{display:block;height:100%;background:linear-gradient(90deg,#5b6cff,#7c5cff)}
.cols{display:flex;flex-wrap:wrap;gap:28px}.col h4{margin:6px 0 4px;color:var(--muted);font-size:13px}
.col ul{margin:0;padding-left:18px;font-size:12px}.commits{margin:8px 0;padding-left:18px;font-size:12px;color:var(--muted)}
details summary{cursor:pointer;color:var(--muted);font-size:13px;margin-top:10px}
pre{background:#0f1117;color:#cdd3e0;padding:14px;border-radius:8px;overflow:auto;font-size:12px;margin-top:8px}
footer{text-align:center;color:var(--muted);font-size:12px;padding:8px 0 36px}
@media(max-width:640px){.nav .links{display:none}.hero{padding-bottom:54px}main{margin-top:-40px}}
"""


def _proof_section(project_root: str) -> str:
    """The last maintenance pass's evidence record — outcomes, verification
    strength and shields, straight from .apex/proof-of-fix.json."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(project_root) / ".apex" / "proof-of-fix.json"
    if not path.exists():
        return ""
    try:
        proof = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    totals = proof.get("totals", {})
    chips = "".join([
        _chip("applied", totals.get("applied", 0)),
        _chip("rolled back", totals.get("rolled_back", 0)),
        _chip("blocked", totals.get("blocked", 0)),
        _chip("committed", totals.get("committed", 0)),
    ])
    outcome_icon = {"applied": "✅", "rolled_back": "↩️", "blocked": "⛔"}
    strength_label = {
        "function": "💪 names the changed function",
        "module": "✔️ suite references the module",
        "none": "⚠️ applied blind (no covering test)",
        "test-change": "🧪 test change",
    }
    rows = ""
    for fix in (proof.get("fixes") or [])[:12]:
        strength = ((fix.get("verification") or {}).get("strength") or {}).get("level", "")
        shield = fix.get("shield_test", "")
        rows += (
            f"<tr><td>{outcome_icon.get(fix.get('outcome', ''), '·')} "
            f"{_esc(fix.get('outcome', ''))}</td>"
            f"<td>{_esc((fix.get('finding') or {}).get('action', ''))}</td>"
            f"<td><code>{_esc((fix.get('finding') or {}).get('target', ''))}</code></td>"
            f"<td>{_esc(strength_label.get(strength, '—'))}</td>"
            f"<td>{('🛡️ <code>' + _esc(shield) + '</code>') if shield else '—'}</td></tr>"
        )
    if not rows:
        return ""
    table = ("<table><thead><tr><th>Outcome</th><th>Action</th><th>Target</th>"
             "<th>Verification strength</th><th>Shield</th></tr></thead>"
             f"<tbody>{rows}</tbody></table>")
    sub = f"<p class='muted'>Generated {_esc(proof.get('generated_at', ''))} · full evidence (diffs, test runs) in <code>.apex/proof-of-fix.json</code></p>"
    return _card("proof", "🧾", "Proof of fix — last maintenance pass",
                 f"<div class='chips'>{chips}</div>{table}{sub}")


def _roadmap_changes_section(project_root: str, roadmap) -> str:
    """Cross-run roadmap story: which signals produced the new work, which
    stopped firing — when a saved snapshot exists to compare against."""
    if roadmap is None or not getattr(roadmap, "phases", None):
        return ""
    try:
        from pathlib import Path as _Path

        from app.engine.roadmap_history import (
            _count_signals,
            _signal_phrase,
            diff_roadmaps,
            load_snapshot,
        )

        snapshot = load_snapshot(_Path(project_root) / ".apex" / "roadmap-snapshot.json")
        if not snapshot:
            return ""
        diff = diff_roadmaps(snapshot, roadmap)
    except Exception:
        return ""
    if not (diff.new or diff.dropped):
        return ""
    parts = [f"<div class='chips'>{_chip('new', len(diff.new))}"
             f"{_chip('no longer surfaced', len(diff.dropped))}"
             f"{_chip('stable', diff.stable_count)}</div>"]
    new_signals = _count_signals(diff.new)
    gone_signals = _count_signals(diff.dropped)
    if new_signals:
        parts.append(f"<p><b>Where the new work comes from:</b> {_esc(_signal_phrase(new_signals))}</p>")
    if gone_signals:
        parts.append(f"<p><b>Signals that stopped firing:</b> {_esc(_signal_phrase(gone_signals))}</p>")
    items = "".join(
        f"<li>🆕 [{_esc(c.curr_phase)}] {_esc(c.title)}"
        + (f" — <code>{_esc(c.grounded_in)}</code>" if c.grounded_in else "") + "</li>"
        for c in diff.new[:6]
    ) + "".join(
        f"<li>✅ {_esc(c.title)}"
        + (f" — its <code>{_esc(c.signal)}</code> signal no longer fires" if c.signal else "")
        + "</li>"
        for c in diff.dropped[:6]
    )
    if items:
        parts.append(f"<ul>{items}</ul>")
    return _card("changes", "📈", "Roadmap changes since last snapshot", "".join(parts))


def _dream_section(project_root: str) -> str:
    """Pin the latest dream: what the organism discovered while you were away —
    the new/resolved flow first, then patterns and open-ended discoveries.
    Best-effort: no digest yet renders nothing."""
    import re as _re
    from pathlib import Path as _Path

    path = _Path(project_root) / ".apex" / "dream-digest.md"
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    # Pull the bullet lines under each section into a compact list, preserving
    # the leading emoji so the new/resolved flow reads at a glance.
    items: list[str] = []
    for line in text.splitlines():
        m = _re.match(r"^- (.+)$", line.strip())
        if m:
            items.append(m.group(1))
    if not items:
        return ""
    lis = "".join(f"<li>{_esc(i)}</li>" for i in items[:14])
    body = (f"<p class='muted'>From <code>.apex/dream-digest.md</code> — "
            f"curated deterministically, zero tokens.</p><ul class='dream'>{lis}</ul>")
    return _card("dream", "💤", "Last dream — discovered while you were away", body)


def _render_html(project_root, profile, findings, idea_report, action_plan, reasoning,
                 git=None, debug=None, roadmap=None, shape=None, autonomy=None,
                 pareto=None, trajectory=None, learned=None) -> str:
    git = git or {}
    debug = debug or {}
    pareto = pareto or []
    trajectory = trajectory or []
    nav_links = [("overview", "Overview"), ("findings", "Findings"),
                 ("architecture", "Architecture"), ("ideas", "Ideas")]
    if shape is not None and getattr(shape, "total_ideas", 0):
        nav_links.append(("shape", "Shape"))
    if roadmap is not None and getattr(roadmap, "phases", None):
        nav_links.append(("roadmap", "Roadmap"))
    if pareto:
        nav_links.append(("frontier", "Frontier"))
    if autonomy:
        nav_links.append(("autonomy", "Autonomy"))
    if trajectory:
        nav_links.append(("trajectory", "Trajectory"))
    if learned and (learned.get("most_reliable") or learned.get("least_reliable")):
        nav_links.append(("learned", "Learned"))
    if (Path(project_root) / ".apex" / "dream-digest.md").exists():
        nav_links.append(("dream", "Dream"))
    nav_links += [("actions", "Actions"), ("reasoning", "Reasoning"), ("profile", "Profile")]
    if debug:
        nav_links.append(("debug", "Debug"))
    if git:
        nav_links.append(("repository", "Repo"))
    links = "".join(f"<a href='#{i}'>{_esc(t)}</a>" for i, t in nav_links)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections = "".join(
        [
            _overview(profile, findings, idea_report, action_plan, git),
            _findings_section(findings, project_root),
            _architecture_section(profile),
            _ideas_section(idea_report),
            _shape_section(shape),
            _roadmap_section(roadmap),
            _roadmap_changes_section(project_root, roadmap),
            _proof_section(project_root),
            _dream_section(project_root),
            _pareto_section(pareto, getattr(idea_report, "stats", {}).get("total_ideas", 0)),
            _autonomy_section(autonomy),
            _trajectory_section(trajectory),
            _learned_section(learned),
            _actions_section(action_plan),
            _reasoning_section(reasoning),
            _debug_section(debug),
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
