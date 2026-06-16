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
    quality: bool = True,
) -> str:
    """Aggregate profile + scans + ideas/actions + reasoning into one HTML page.

    The code-quality card runs four independent analyzers (type-hint coverage,
    docstring coverage, the complexity profile, and the TODO-debt census), each
    of which re-walks and re-parses the whole tree — the heaviest part of a
    dashboard build on a large repo. ``quality`` (default ``True``: the card is
    rendered, byte-identical to before) lets callers/tests that don't need the
    card opt out with ``quality=False`` and skip that work entirely.
    """
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
        pareto=pareto, trajectory=trajectory, learned=learned, quality=quality,
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
    return (
        f"<section id='overview' class='overview'><div class='kpis'>{''.join(cards)}</div>"
        f"{_health_bars(profile, findings)}</section>"
    )


def _health_bars(profile, findings) -> str:
    """A compact normalized "health bars" read-out beneath the KPI grid.

    Each row is a metric mapped to a 0..1 fraction (more filled = healthier):
      - Coverage: the test-coverage ratio as-is.
      - In scope (Python): ``profile.analyzed_ratio`` — how much of a polyglot repo
        Apex's Python analysis actually covers.
      - Security: ``1 / (1 + findings)`` so 0 findings = a full bar and each extra
        finding shrinks it monotonically (1→0.5→0.33…), with no arbitrary cutoff.
    Rows whose metric is unavailable are omitted; an empty set renders nothing.
    """
    from app.reporting.dashboard_charts import metric_bars

    cov = findings.get("coverage", {}) or {}
    sec = findings.get("security", {}) or {}
    rows: list[tuple[str, float]] = []
    if "coverage_ratio" in cov:
        rows.append(("Test coverage", float(cov.get("coverage_ratio", 0) or 0)))
    analyzed = getattr(profile, "analyzed_ratio", None)
    if isinstance(analyzed, (int, float)):
        rows.append(("In scope (Python)", float(analyzed)))
    sec_n = sec.get("findings_count", 0) or 0
    rows.append(("Security", 1.0 / (1.0 + float(sec_n))))
    if not rows:
        return ""
    return (
        "<div class='healthbars'><h4>Health bars</h4>"
        f"{metric_bars(rows)}</div>"
    )


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


def _coordinator_block(p: ProjectProfile) -> str:
    """Render high-fan-OUT "god-modules" — decoupling candidates.

    Reads ``profile.coordinator_modules`` (a ``list[dict]`` with ``module``,
    ``fan_out`` and the top internal ``imports``). This is the OPPOSITE edge
    direction from the dependency-hub (fan-IN) read-out, so the two never restate
    each other. Gated by construction: a repo with no god-module yields "" and the
    page stays byte-identical. Every codebase-sourced string is HTML-escaped.
    """
    coordinators = getattr(p, "coordinator_modules", []) or []
    if not coordinators:
        return ""
    rows = ""
    for c in coordinators[:5]:
        if not isinstance(c, dict):
            continue
        imports = c.get("imports", []) or []
        wires = " · ".join(f"<code>{_esc(m)}</code>" for m in imports[:3])
        wires_html = f"<span class='muted'>wires {wires}</span>" if wires else ""
        rows += (
            f"<li><code>{_esc(c.get('module', '?'))}</code> "
            f"<span class='val'>fan-out {_esc(c.get('fan_out', 0))}</span> "
            f"{wires_html}</li>"
        )
    if not rows:
        return ""
    return (
        "<h4 style='margin:12px 0 4px'>🕸️ Coordinator modules (high fan-out)</h4>"
        "<p class='muted' style='margin:0 0 6px'>Modules that import many "
        "siblings — decoupling candidates (the opposite of dependency hubs).</p>"
        f"<ul class='commits'>{rows}</ul>"
    )


def _deep_nesting_block(p: ProjectProfile) -> str:
    """Render the deepest control-flow staircases — guard-clause / extract candidates.

    Reads ``profile.deeply_nested_functions`` (a ``list[dict]`` with ``module``,
    ``function`` and ``depth``): top-level functions whose block nesting reaches
    the profiler's floor, so they read as a staircase and invite an
    invert-the-guard / early-return / extract-the-inner-block refactor. This is a
    maintainability read distinct from the fan-out (coordinator) and fan-in
    (fragile) edges. Gated by construction: an all-flat repo yields [] so the page
    stays byte-identical. Every codebase-sourced string is HTML-escaped.
    """
    deep = getattr(p, "deeply_nested_functions", []) or []
    if not deep:
        return ""
    rows = ""
    for d in deep[:5]:
        if not isinstance(d, dict):
            continue
        module = d.get("module", "?")
        function = d.get("function", "?")
        depth = d.get("depth", 0)
        rows += (
            f"<li><code>{_esc(module)}</code> "
            f"<span class='muted'>·</span> <code>{_esc(function)}</code> "
            f"<span class='val'>depth {_esc(depth)}</span></li>"
        )
    if not rows:
        return ""
    return (
        "<h4 style='margin:12px 0 4px'>🪜 Deeply nested functions</h4>"
        "<p class='muted' style='margin:0 0 6px'>Functions whose control flow "
        "nests deeply — guard-clause / extract refactor candidates.</p>"
        f"<ul class='commits'>{rows}</ul>"
    )


def _scope_composition(p: ProjectProfile) -> str:
    """Stacked composition bar of analysed (Python) vs out-of-scope source.

    Apex deep-analyses Python only, so a polyglot repo has a genuine "how much
    does our analysis actually cover?" composition read. We surface it as a
    proportional ``stacked_bar`` of ``analyzed_ratio`` vs ``out_of_scope_ratio``.

    Gated: only renders when an out-of-scope remainder genuinely exists
    (``out_of_scope_ratio > 0``). An all-Python repo (ratio 0) is omitted, so
    its page stays byte-identical to before this feature existed.
    """
    out_ratio = getattr(p, "out_of_scope_ratio", 0.0)
    if not isinstance(out_ratio, (int, float)) or out_ratio <= 0.0:
        return ""
    analyzed = getattr(p, "analyzed_ratio", None)
    if not isinstance(analyzed, (int, float)):
        return ""

    from app.reporting.dashboard_charts import stacked_bar

    segments = [
        ("Analysed (Python)", float(analyzed)),
        ("Out of scope", float(out_ratio)),
    ]
    return (
        "<div class='scopecomp'><h4 style='margin:12px 0 4px'>"
        f"{_esc('🌐 Analysis scope composition')}</h4>"
        f"{stacked_bar(segments)}</div>"
    )


def _architecture_section(p: ProjectProfile) -> str:
    """Surface architectural risks the engine sees: import cycles + fragility."""
    cycles = getattr(p, "import_cycles", []) or []
    fragile = getattr(p, "fragile_modules", []) or []
    coordinators = getattr(p, "coordinator_modules", []) or []
    deep_nesting = _deep_nesting_block(p)
    scope = _scope_composition(p)
    if not cycles and not fragile and not coordinators:
        if deep_nesting:
            return _card("architecture", "🏛️", "Architecture health", deep_nesting + scope)
        inner = "<p class='muted'>No import cycles or fragile hubs detected 🎉</p>"
        return _card("architecture", "🏛️", "Architecture health", inner + scope)
    chips = "".join(
        [
            _chip("import cycles", len(cycles)),
            _chip("fragile modules", len(fragile)),
            _chip("coordinators", len(coordinators)),
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
    body += _coordinator_block(p)
    body += deep_nesting
    return _card(
        "architecture", "🏛️", "Architecture health",
        f"<div class='chips'>{chips}</div>{body}{scope}",
    )


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


def _anchor_focus(idea) -> str:
    """Render an idea's concrete loci (function + line + metric) defensively.

    Returns "" when the idea carries no anchors, so ideas without function-grain
    data render byte-identically to before this feature existed. Anchors are read
    via getattr (older idea payloads / SimpleNamespace stand-ins may omit them)
    and every codebase-sourced string is HTML-escaped.
    """
    anchors = getattr(idea, "anchors", None)
    if not anchors:
        return ""
    parts = []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        symbol = str(a.get("symbol", "")).strip()
        if not symbol:
            continue
        module = str(a.get("module", "")).strip()
        line = a.get("line")
        metric = str(a.get("metric", "")).strip()
        loc = _esc(module)
        if line not in (None, ""):
            loc = f"{loc}:{_esc(line)}" if loc else _esc(line)
        detail = ", ".join(p for p in (loc, _esc(metric) if metric else "") if p)
        suffix = f" <span class='muted'>({detail})</span>" if detail else ""
        parts.append(f"<code>{_esc(symbol)}</code>{suffix}")
    if not parts:
        return ""
    return f"<div class='focus muted' style='margin:2px 0 0'>focus: {' · '.join(parts)}</div>"


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
            f"{_anchor_focus(idea)}"
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
    depths = " ".join(f"d{d}:{n}" for d, n in sorted(shape.depth_distribution.items()))
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
    # Grounding read-out: how many ideas tie to concrete code facts. Read via
    # getattr so a shape object from a worktree without these fields renders
    # byte-identically (the line is simply omitted).
    grounding_html = ""
    grounding_ratio = getattr(shape, "grounding_ratio", None)
    if isinstance(grounding_ratio, (int, float)) and grounding_ratio > 0:
        grounded = getattr(shape, "grounded_count", 0)
        grounding_html = (
            f"<p class='muted'>grounding: <b>{int(grounding_ratio * 100)}%</b> of ideas "
            f"tied to concrete code facts "
            f"({_esc(grounded)}/{_esc(shape.total_ideas)})</p>"
        )
    inner = (
        f"<div class='chips'>{chips}</div>"
        f"<p class='muted'>kinds: {_esc(kinds)} · depth: {_esc(depths)} · "
        f"top subject <code>{_esc(shape.top_subject)}</code> "
        f"({int(shape.top_subject_share * 100)}%)</p>"
        f"{grounding_html}"
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

    # A tiny inline trend of the security-finding count after each recorded run —
    # the shape of the project getting healthier (fewer findings) over time.
    from app.reporting.dashboard_charts import sparkline

    series: list[float] = []
    for e in history:
        v = (e.get("after") or {}).get("security_findings")
        if isinstance(v, (int, float)):
            series.append(float(v))
    spark = (
        f"<div class='trend'><span class='trend-label'>findings trend</span>{sparkline(series)}</div>"
        if len(series) >= 2 else ""
    )

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
        f"{spark}"
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


def _proof_applied_count(project_root: str) -> int:
    """The number of test-verified fixes Apex has landed here, from
    ``.apex/proof-of-fix.json``. Defensive: missing/corrupt → 0 (no scan)."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(project_root) / ".apex" / "proof-of-fix.json"
    if not path.exists():
        return 0
    try:
        proof = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    try:
        return int((proof.get("totals") or {}).get("applied", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _trackrecord_section(learned: dict[str, Any] | None, project_root: str) -> str:
    """Apex's PROVEN track record on *this* project — the evidence-backed
    "proven over time" story an LLM cannot offer.

    Combines two deterministic sources the dashboard already has access to:
    the per-fix-type landing rates learned in ``.apex/idea-memory.json`` and the
    count of test-verified, auto-rollback-guarded fixes recorded in
    ``.apex/proof-of-fix.json``. Gated by construction: with no learned rates AND
    no landed fixes the section returns "" (byte-identical to before this panel
    existed). Every codebase-sourced string is HTML-escaped; no timestamp.
    """
    learned = learned or {}
    # Landing rates per fix type: most/least reliable operators carry
    # {"key","success_rate","samples"}. De-dup by key (an operator can appear in
    # both lists when only one is tracked) and sort by rate desc, then key.
    by_key: dict[str, dict[str, Any]] = {}
    for row in (learned.get("most_reliable") or []) + (learned.get("least_reliable") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        if not key or key in by_key:
            continue
        by_key[key] = row
    rates = sorted(
        by_key.values(),
        key=lambda r: (-float(r.get("success_rate", 0.0) or 0.0), str(r.get("key", ""))),
    )
    landed = _proof_applied_count(project_root)
    if not rates and not landed:
        return ""

    chips = "".join([
        _chip("verified fixes landed", landed),
        _chip("fix types tracked", len(rates)),
    ])
    intro = (
        "<p class='muted'>Every landed fix was test-verified with automatic "
        "rollback on failure — an evidence record, not a promise.</p>"
    )
    rows = "".join(
        f"<tr><td><code>{_esc(r.get('key', ''))}</code></td>"
        f"<td class='num'>{int(float(r.get('success_rate', 0.0) or 0.0) * 100)}%</td>"
        f"<td class='num'>{_esc(r.get('samples', 0))}</td></tr>"
        for r in rates
    )
    table = ""
    if rows:
        table = (
            "<table><thead><tr><th>Fix type</th><th>Landing rate</th>"
            "<th>Samples</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    return _card("trackrecord", "🏆", "Track record",
                 f"<div class='chips'>{chips}</div>{intro}{table}")


def _outscope_test_corpus(project_root: str) -> list[str]:
    """The lowercased text of every test file in the repo.

    A non-Python source file counts as "tested" only when its basename literally
    appears inside one of these — the honest, language-agnostic signal Apex can
    read without a non-Python parser (``scan_polyglot_facts``' FileFact carries no
    test flag here). Deterministic and pure: one ``is_skipped``-respecting
    filesystem walk over test files, reading each locally; any unreadable file is
    skipped (never raises). No git pass.
    """
    from app.engine.skip_dirs import is_skipped as _is_skipped

    root = Path(project_root)
    if not root.exists():
        return []
    corpus: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_skipped(rel):
            continue
        name_lower = path.name.lower()
        rel_lower = rel.as_posix().lower()
        is_test = (
            name_lower.startswith("test_")
            or name_lower.endswith("_test.py")
            or "/tests/" in f"/{rel_lower}"
            or rel_lower.startswith("tests/")
        )
        if not is_test:
            continue
        try:
            corpus.append(path.read_text(encoding="utf-8", errors="ignore").lower())
        except OSError:
            continue
    return corpus


def _outscope_section(project_root: str) -> str:
    """Apex's honest "outside analysis scope" awareness as a dashboard panel.

    Names the biggest / most-active NON-Python source files (from
    ``scan_polyglot_facts(root, limit=5)`` — a SINGLE git pass), each with its
    language, LOC, churn, and a "(no test found)" flag for files no test file
    references. Apex deep-analyses Python only and has no non-Python transform, so
    this panel surfaces the blind spot honestly rather than over-promising.

    Gated by construction: an all-Python repo has no out-of-scope files, so the
    section returns "" and the page stays byte-identical. Every codebase-sourced
    string is HTML-escaped; no timestamp (the page stamps once).
    """
    try:
        from app.tools.polyglot_facts import scan_polyglot_facts

        facts = scan_polyglot_facts(project_root, limit=5)
    except Exception:
        return ""
    if not facts:
        return ""

    corpus = _outscope_test_corpus(project_root)

    def _has_test(fact_path: str) -> bool:
        base = Path(fact_path).name.lower()
        return any(base in text for text in corpus)

    rows = ""
    for f in facts:
        commit_word = "commit" if f.churn == 1 else "commits"
        flag = (
            "" if _has_test(f.path)
            else " <span class='caveat'>(no test found)</span>"
        )
        rows += (
            f"<tr><td><code>{_esc(f.path)}</code>{flag}</td>"
            f"<td>{_esc(f.language)}</td>"
            f"<td class='num'>{_esc(f.loc)}</td>"
            f"<td class='num'>{_esc(f.churn)} {commit_word}</td></tr>"
        )
    caption = (
        "<p class='muted'>Apex deep-analyses Python; these are the largest "
        "active non-Python files — where the rest of the risk concentrates.</p>"
    )
    table = (
        "<table><thead><tr><th>File</th><th>Language</th><th>LOC</th>"
        "<th>Churn</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _card("outscope", "🌐", "Outside analysis scope", f"{caption}{table}")


def _quality_pct_bar(label: str, ratio: float, detail: str = "") -> str:
    """A labelled 0..100% progress bar reusing the dark-theme ``.bar`` styling.

    ``ratio`` is clamped to [0,1] and tone-bucketed (good >=70% / warn >=30% /
    bad). ``detail`` is an optional escaped suffix (e.g. ``"482/600 functions"``).
    """
    pct = max(0, min(100, int(round(float(ratio) * 100))))
    tone = "bar-good" if pct >= 70 else "bar-warn" if pct >= 30 else "bar-bad"
    detail_html = f" <span class='muted'>{_esc(detail)}</span>" if detail else ""
    return (
        f"<div class='bar-wrap'><div class='bar-label'>{_esc(label)} "
        f"<b>{pct}%</b>{detail_html}</div><div class='bar'><div class='bar-fill {tone}' "
        f"style='width:{pct}%'></div></div></div>"
    )


def _quality_section(project_root: str) -> str:
    """Surface the deterministic code-quality analyzers as one dashboard card.

    Runs four pure analyzers from ``app.tools`` over ``project_root`` — type-hint
    coverage, public docstring coverage, the cyclomatic-complexity profile, and
    the inline TODO/FIXME debt census — and renders whichever produced data as
    chips + bars + a hotspots list. Each analyzer is wrapped independently so a
    single failure (or an absent module) degrades to "omitted" rather than
    breaking the card; the whole section returns "" when none yields data, so the
    page stays byte-identical for repos where nothing is measurable. Every
    codebase-sourced string is HTML-escaped; deterministic, no timestamp.
    """
    chips: list[str] = []
    blocks: list[str] = []

    try:
        from app.tools.type_hint_coverage import analyze_type_hint_coverage

        th = analyze_type_hint_coverage(project_root)
    except Exception:
        th = None
    if th is not None and th.total_functions > 0:
        chips.append(_chip("type hints", f"{int(round(th.overall_ratio * 100))}%"))
        blocks.append(_quality_pct_bar(
            "Type-hint coverage", th.overall_ratio,
            f"{th.annotated_functions}/{th.total_functions} functions fully annotated",
        ))
        worst = [m for m in th.worst_modules if m.get("ratio", 1.0) < 1.0][:5]
        if worst:
            lis = "".join(
                f"<li><code>{_esc(m.get('module', '?'))}</code> "
                f"<span class='val'>{int(round(float(m.get('ratio', 0)) * 100))}%</span> "
                f"<span class='muted'>({_esc(m.get('annotated', 0))}/"
                f"{_esc(m.get('total', 0))})</span></li>"
                for m in worst
            )
            blocks.append(
                "<h4 style='margin:8px 0 4px'>Thinnest-typed modules</h4>"
                f"<ul class='commits'>{lis}</ul>"
            )

    try:
        from app.tools.docstring_coverage import analyze_docstring_coverage

        dc = analyze_docstring_coverage(project_root)
    except Exception:
        dc = None
    if dc is not None and dc.total_public > 0:
        chips.append(_chip("public docs", f"{int(round(dc.overall_public_ratio * 100))}%"))
        blocks.append(_quality_pct_bar(
            "Public docstring coverage", dc.overall_public_ratio,
            f"{dc.documented_public}/{dc.total_public} public symbols documented",
        ))

    try:
        from app.tools.complexity_profile import analyze_complexity

        cx = analyze_complexity(project_root)
    except Exception:
        cx = None
    if cx is not None and cx.total > 0:
        chips.append(_chip(f"complexity > {cx.threshold}", cx.over_threshold))
        chips.append(_chip("max complexity", cx.max))
        blocks.append(
            "<p class='muted' style='margin:6px 0 4px'>"
            f"{_esc(cx.over_threshold)} of {_esc(cx.total)} functions exceed "
            f"complexity {_esc(cx.threshold)} "
            f"(mean {_esc(cx.mean)} · median {_esc(cx.median)} · max {_esc(cx.max)}).</p>"
        )
        hot = cx.hotspots[:5]
        if hot:
            lis = "".join(
                f"<li><code>{_esc(h.get('module', '?'))}</code>"
                f"<span class='muted'>·</span><code>{_esc(h.get('function', '?'))}</code> "
                f"<span class='val'>{_esc(h.get('complexity', 0))}</span></li>"
                for h in hot
            )
            blocks.append(
                "<h4 style='margin:8px 0 4px'>Complexity hotspots</h4>"
                f"<ul class='commits'>{lis}</ul>"
            )

    try:
        from app.tools.todo_debt import analyze_todo_debt

        td = analyze_todo_debt(project_root)
    except Exception:
        td = None
    if td is not None and td.total > 0:
        chips.append(_chip("debt markers", td.total))
        by = " · ".join(
            f"{_esc(k)} {_esc(v)}" for k, v in td.by_marker.items() if v
        )
        blocks.append(
            f"<p class='muted' style='margin:6px 0 4px'>{_esc(td.total)} inline "
            f"debt markers — {by}</p>"
        )
        items = td.items[:5]
        if items:
            lis = "".join(
                f"<li><code>{_esc(i.get('module', '?'))}:{_esc(i.get('line', '?'))}</code> "
                f"<span class='op'>{_esc(i.get('marker', ''))}</span> "
                f"<span class='muted'>{_esc(i.get('text', ''))}</span></li>"
                for i in items
            )
            blocks.append(
                "<h4 style='margin:8px 0 4px'>Recent markers</h4>"
                f"<ul class='commits'>{lis}</ul>"
            )

    if not chips and not blocks:
        return ""
    inner = f"<div class='chips'>{''.join(chips)}</div>{''.join(blocks)}"
    return _card("quality", "📊", "Code quality metrics", inner)


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
:root{
--bg:#070b14;--bg2:#0b1220;--card:#0e1626;--card2:#111c30;--ink:#e7edf7;
--ink2:#aeb9cf;--muted:#7b8aa6;--line:#1d2942;--line2:#27375a;
--accent:#3de2c4;--accent2:#5b8cff;--accent3:#9b7bff;
--glow:rgba(61,226,196,.16);--radius:16px;
--shadow:0 1px 0 rgba(255,255,255,.02) inset,0 18px 40px -20px rgba(0,0,0,.75),0 2px 8px rgba(0,0,0,.4);
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
background:radial-gradient(1200px 600px at 15% -10%,#13243f 0%,transparent 55%),
radial-gradient(1000px 700px at 100% 0%,#1a1330 0%,transparent 50%),var(--bg);
color:var(--ink);line-height:1.55;-webkit-font-smoothing:antialiased;letter-spacing:.01em}
a{color:inherit;text-decoration:none}
::selection{background:var(--glow);color:#fff}
.nav{position:sticky;top:0;z-index:30;background:rgba(8,13,22,.72);backdrop-filter:saturate(140%) blur(14px);
-webkit-backdrop-filter:saturate(140%) blur(14px);
border-bottom:1px solid var(--line);padding:13px 30px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.brand{font-weight:700;font-size:16px;display:flex;align-items:center;gap:10px;letter-spacing:.02em}
.brand .mark{width:22px;height:22px;flex:none}
.brand .dot{background:linear-gradient(120deg,var(--accent),var(--accent2) 60%,var(--accent3));
-webkit-background-clip:text;background-clip:text;color:transparent}
.nav .path{color:var(--muted);font-size:12.5px;font-family:var(--mono);
padding:3px 10px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.02)}
.nav .links{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.nav .links a{font-size:12.5px;color:var(--ink2);padding:5px 11px;border-radius:999px;border:1px solid transparent;transition:.16s}
.nav .links a:hover{color:#fff;background:rgba(61,226,196,.08);border-color:var(--line2)}
.hero{position:relative;overflow:hidden;color:#fff;padding:46px 30px 80px;
border-bottom:1px solid var(--line);
background:linear-gradient(135deg,rgba(61,226,196,.10),rgba(91,140,255,.08) 45%,rgba(155,123,255,.10))}
.hero::before{content:"";position:absolute;inset:0;z-index:0;opacity:.5;
background:radial-gradient(420px 220px at 12% 30%,var(--glow),transparent 70%),
radial-gradient(520px 280px at 88% 20%,rgba(91,140,255,.16),transparent 70%)}
.hero>*{position:relative;z-index:1}
.hero .eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:11.5px;font-weight:600;
letter-spacing:.14em;text-transform:uppercase;color:var(--accent);
padding:5px 12px;border:1px solid var(--line2);border-radius:999px;background:rgba(61,226,196,.06)}
.hero .eyebrow .pulse{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px var(--glow)}
.hero h1{margin:16px 0 8px;font-size:30px;font-weight:750;letter-spacing:-.01em;
background:linear-gradient(120deg,#fff,#cfe6ff 60%,#dccbff);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{margin:0;color:var(--ink2);font-size:14px;max-width:62ch}
.hero .stamp{font-family:var(--mono);font-size:12px;color:var(--muted)}
.hero-vitals{display:flex;flex-wrap:wrap;align-items:center;gap:24px;margin:24px 0 4px}
.vitals{display:flex;flex-wrap:wrap;gap:12px}
.vital{display:flex;flex-direction:column;gap:4px;min-width:82px;padding:12px 16px;
border:1px solid var(--line2);border-radius:14px;background:rgba(255,255,255,.035);
box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}
.vital-num{font-size:24px;font-weight:770;line-height:1;font-variant-numeric:tabular-nums;
background:linear-gradient(120deg,var(--accent),var(--accent2) 70%);
-webkit-background-clip:text;background-clip:text;color:transparent}
.vital-label{font-size:11px;color:var(--ink2);font-weight:500;letter-spacing:.02em}
.hero-charts{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.hero-charts svg{background:rgba(245,248,252,.95);border-radius:12px;padding:7px;
border:1px solid var(--line2);box-shadow:var(--shadow)}
.vital-top-move{margin:14px 0 0;font-size:13.5px;color:var(--ink2)}
.vital-top-move::before{content:"➜ next move: ";color:var(--accent);font-weight:650}
.healthbars{margin:16px 0 2px}
.healthbars h4{margin:0 0 8px;font-size:12.5px;font-weight:600;color:var(--ink2);letter-spacing:.02em}
.healthbars svg{background:rgba(245,248,252,.95);border-radius:12px;padding:8px 10px;
border:1px solid var(--line2);box-shadow:var(--shadow);max-width:100%}
.trend{display:flex;align-items:center;gap:12px;margin:0 0 14px}
.trend-label{font-size:11.5px;color:var(--muted);letter-spacing:.02em}
.trend svg{background:rgba(245,248,252,.95);border-radius:10px;padding:5px 8px;border:1px solid var(--line2)}
main{max-width:1120px;margin:-52px auto 64px;padding:0 30px;display:flex;flex-direction:column;gap:22px}
.overview .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}
.kpi{position:relative;background:linear-gradient(180deg,var(--card2),var(--card));
border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow);overflow:hidden}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
background:linear-gradient(var(--accent),var(--accent2));opacity:.85}
.kpi-val{font-size:30px;font-weight:760;line-height:1;font-variant-numeric:tabular-nums}
.kpi-label{color:var(--ink2);font-size:13px;margin-top:8px;font-weight:500}
.kpi-sub{color:var(--muted);font-size:11px;margin-top:3px}
.a-blue{color:#6ba0ff}.a-red{color:#ff6b72}.a-green{color:#37d39b}.a-amber{color:#f2b53a}.a-violet{color:#b794ff}
.card{position:relative;background:linear-gradient(180deg,var(--card2),var(--card));
border:1px solid var(--line);border-radius:var(--radius);padding:24px 26px;box-shadow:var(--shadow);
scroll-margin-top:78px}
.card::after{content:"";position:absolute;inset:0;border-radius:var(--radius);pointer-events:none;
border:1px solid rgba(255,255,255,.02)}
.card h2{margin:0 0 16px;font-size:16.5px;font-weight:680;display:flex;align-items:center;gap:11px;letter-spacing:-.01em}
.card h2 .ico{font-size:17px;width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center;
border-radius:11px;background:linear-gradient(160deg,rgba(61,226,196,.14),rgba(91,140,255,.12));
border:1px solid var(--line2);flex:none}
.muted{color:var(--muted);font-size:13px;margin:0 0 12px}
.chips{display:flex;flex-wrap:wrap;gap:9px;margin:0 0 16px}
.chip{background:rgba(255,255,255,.025);border:1px solid var(--line);border-radius:999px;
padding:5px 13px;font-size:12px;color:var(--ink2)}
.chip b{color:var(--ink);font-weight:680;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{color:var(--muted);font-weight:650;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
border-bottom:1px solid var(--line2)}
tbody tr{transition:background .12s}
tbody tr:hover{background:rgba(91,140,255,.06)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.empty{color:var(--muted);text-align:center;padding:20px}
code{background:rgba(91,140,255,.10);padding:2px 7px;border-radius:6px;font-size:12px;font-family:var(--mono);
color:#9fc1ff;border:1px solid rgba(91,140,255,.14)}
.badge{font-size:11px;padding:3px 10px;border-radius:999px;font-weight:650;text-transform:capitalize;border:1px solid transparent}
.sev-crit{background:rgba(255,107,114,.14);color:#ff8a8f;border-color:rgba(255,107,114,.3)}
.sev-high{background:rgba(242,150,58,.14);color:#f6b269;border-color:rgba(242,150,58,.28)}
.sev-med{background:rgba(242,181,58,.13);color:#f1c659;border-color:rgba(242,181,58,.26)}
.sev-low{background:rgba(123,138,166,.16);color:#aab6cd;border-color:var(--line2)}
.sev-none{background:rgba(123,138,166,.12);color:#8a96ad;border-color:var(--line)}
.pill{font-size:11px;padding:3px 10px;border-radius:999px;font-weight:650;border:1px solid transparent}
.pill.exec{background:rgba(55,211,155,.14);color:#5ce0b0;border-color:rgba(55,211,155,.28)}
.pill.design{background:rgba(91,140,255,.14);color:#8fb3ff;border-color:rgba(91,140,255,.28)}
.bar-wrap{margin:6px 0 18px}.bar-label{font-size:13px;color:var(--ink2);margin-bottom:6px}
.bar{height:10px;background:rgba(255,255,255,.05);border-radius:999px;overflow:hidden;border:1px solid var(--line)}
.bar-fill{height:100%;border-radius:999px}
.bar-good{background:linear-gradient(90deg,#2fb98a,#37d39b)}
.bar-warn{background:linear-gradient(90deg,#d89a26,#f2b53a)}
.bar-bad{background:linear-gradient(90deg,#e5535a,#ff6b72)}
ul.tree{list-style:none;padding-left:0;margin:0}
ul.tree ul{border-left:1px solid var(--line2);margin-left:11px;padding-left:18px}
ul.tree li{margin:6px 0;font-size:13px}
.op{background:linear-gradient(135deg,rgba(61,226,196,.16),rgba(155,123,255,.16));color:#bfeede;
border:1px solid var(--line2);border-radius:7px;padding:1px 8px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.val{color:#5ce0b0;font-size:12px;font-weight:650;font-variant-numeric:tabular-nums}
.caveat{color:#f2b53a;font-size:12px}
.ibadge{font-size:10px;font-weight:700;border-radius:7px;padding:1px 8px;margin:0 4px;text-transform:uppercase;letter-spacing:.04em;border:1px solid transparent}
.b-synth{background:rgba(91,140,255,.16);color:#8fb3ff;border-color:rgba(91,140,255,.3)}
.b-pair{background:rgba(55,211,155,.16);color:#5ce0b0;border-color:rgba(55,211,155,.3)}
.b-frag{background:rgba(255,107,114,.16);color:#ff8a8f;border-color:rgba(255,107,114,.3)}
.b-qw{background:rgba(242,181,58,.16);color:#f1c659;border-color:rgba(242,181,58,.3)}
.ph-stab{background:rgba(55,211,155,.16);color:#5ce0b0;border-color:rgba(55,211,155,.3)}
.ph-sec{background:rgba(255,107,114,.16);color:#ff8a8f;border-color:rgba(255,107,114,.3)}
.ph-evo{background:rgba(91,140,255,.16);color:#8fb3ff;border-color:rgba(91,140,255,.3)}
.ph-ref{background:rgba(155,123,255,.16);color:#b794ff;border-color:rgba(155,123,255,.3)}
.phase{margin:12px 0 18px}.phase h4{margin:0 0 7px;font-size:13px;font-weight:650;color:var(--ink)}
.roi{display:inline-block;width:64px;height:8px;background:rgba(255,255,255,.06);border:1px solid var(--line);
border-radius:999px;overflow:hidden;margin-right:7px;vertical-align:middle}
.roi span{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent3))}
.cols{display:flex;flex-wrap:wrap;gap:30px}.col h4{margin:8px 0 5px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.col ul{margin:0;padding-left:18px;font-size:12.5px;color:var(--ink2)}
.commits{margin:8px 0;padding-left:18px;font-size:12.5px;color:var(--ink2)}
.commits li,.col li,ul.dream li{margin:4px 0}
details summary{cursor:pointer;color:var(--ink2);font-size:13px;margin-top:12px;
padding:6px 0;list-style:none;display:inline-flex;align-items:center;gap:6px}
details summary::before{content:"\\25B8";color:var(--accent);transition:transform .15s}
details[open] summary::before{transform:rotate(90deg)}
pre{background:#060a12;color:#cdd9ee;padding:16px;border-radius:12px;overflow:auto;font-size:12px;
margin-top:10px;border:1px solid var(--line);font-family:var(--mono)}
p{color:var(--ink2)}p b{color:var(--ink)}
footer{text-align:center;color:var(--muted);font-size:12px;padding:24px 20px 48px;border-top:1px solid var(--line);margin-top:8px}
footer .sig{color:var(--accent2)}
@media(max-width:680px){.nav{padding:11px 18px}.nav .links{display:none}.hero{padding:34px 20px 64px}
.hero h1{font-size:24px}main{margin-top:-44px;padding:0 18px}.card{padding:20px}}
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


def _hero_vitals(project_root, profile, findings, idea_report, action_plan) -> str:
    """Build the hero "vital signs" banner: stat tiles + grade gauge + scope bar.

    Every input is data already computed for the page; the only extra work is one
    deterministic health-grade pass (light profile, no clock, no network). Each
    metric degrades gracefully to "omitted" when it is not available, so the banner
    never crashes and stays byte-identical for identical inputs.
    """
    from app.reporting.dashboard_charts import grade_gauge, scope_bar
    from app.reporting.dashboard_hero import render_vitals

    sec = findings.get("security", {}) or {}
    cov = findings.get("coverage", {}) or {}
    cov_pct = int(cov.get("coverage_ratio", 0) * 100) if "coverage_ratio" in cov else -1
    sec_n = sec.get("findings_count", 0) or 0
    scope_pct = int(round(float(getattr(profile, "analyzed_ratio", 1.0) or 0.0) * 100))
    idea_count = idea_report.stats.get("total_ideas", 0)
    runnable = len(action_plan.executable_steps())
    steps = getattr(action_plan, "steps", None) or []
    top_move = steps[0].title if steps else ""

    # The single source of the grade — same light profile + detector pass as
    # `apex review`/`apex ascend`. Best-effort: a degraded grade just omits the tile.
    grade_letter, grade_score = "", None
    try:
        from app.engine.health_score import grade as _grade

        g = _grade(project_root)
        grade_letter, grade_score = g.letter, g.score
    except Exception:
        grade_letter, grade_score = "", None

    vitals = render_vitals(
        grade_letter=grade_letter,
        grade_score=grade_score,
        coverage_pct=cov_pct,
        security_findings=sec_n,
        scope_pct=scope_pct,
        idea_count=idea_count,
        runnable_actions=runnable,
        top_move="",  # rendered separately below so it sits on its own line
    )
    gauge = grade_gauge(grade_score, grade_letter) if isinstance(grade_score, int) and grade_score >= 0 else ""
    scope_svg = scope_bar(scope_pct) if scope_pct >= 0 else ""
    charts = f"<div class='hero-charts'>{gauge}{scope_svg}</div>" if (gauge or scope_svg) else ""
    top_html = f"<p class='vital-top-move'>{_esc(top_move)}</p>" if top_move else ""
    return f"<div class='hero-vitals'>{vitals}{charts}</div>{top_html}"


# An inline SVG cell/organism glyph — the brand mark. Deterministic, no fetch.
_BRAND_MARK = (
    "<svg class='mark' viewBox='0 0 24 24' fill='none' aria-hidden='true'>"
    "<circle cx='12' cy='12' r='10' stroke='url(#ag)' stroke-width='1.6'/>"
    "<circle cx='12' cy='12' r='3.4' fill='url(#ag)'/>"
    "<circle cx='12' cy='12' r='5.4' stroke='url(#ag)' stroke-width='1' opacity='.55'/>"
    "<circle cx='17.4' cy='8.2' r='1.2' fill='#5b8cff'/>"
    "<circle cx='6.8' cy='15.6' r='1' fill='#9b7bff'/>"
    "<defs><linearGradient id='ag' x1='2' y1='2' x2='22' y2='22' "
    "gradientUnits='userSpaceOnUse'><stop stop-color='#3de2c4'/>"
    "<stop offset='.6' stop-color='#5b8cff'/><stop offset='1' stop-color='#9b7bff'/>"
    "</linearGradient></defs></svg>"
)


def _nav_links(
    project_root, git, debug, roadmap, shape, autonomy, pareto, trajectory,
    learned, *, outscope_html: str, trackrecord_html: str, quality_html: str,
) -> str:
    """Build the sticky-nav anchor list, gating optional sections in page order.

    Mirrors the section assembly below: each conditional appends a link only when
    the matching section will render, so the nav never points at an empty anchor.
    """
    nav_links = [("overview", "Overview"), ("findings", "Findings"),
                 ("architecture", "Architecture"), ("ideas", "Ideas")]
    if quality_html:
        nav_links.append(("quality", "Quality"))
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
    if trackrecord_html:
        nav_links.append(("trackrecord", "Track record"))
    if outscope_html:
        nav_links.append(("outscope", "Out of scope"))
    if (Path(project_root) / ".apex" / "dream-digest.md").exists():
        nav_links.append(("dream", "Dream"))
    nav_links += [("actions", "Actions"), ("reasoning", "Reasoning"), ("profile", "Profile")]
    if debug:
        nav_links.append(("debug", "Debug"))
    if git:
        nav_links.append(("repository", "Repo"))
    return "".join(f"<a href='#{i}'>{_esc(t)}</a>" for i, t in nav_links)


def _page_sections(
    project_root, profile, findings, idea_report, action_plan, reasoning,
    git, debug, roadmap, shape, autonomy, pareto, trajectory, learned,
    *, outscope_html: str, trackrecord_html: str, quality_html: str,
) -> str:
    """Concatenate every section renderer in page order.

    ``outscope_html``/``trackrecord_html``/``quality_html`` are passed in
    pre-rendered so the work is done exactly once (it also drives nav gating)
    rather than recomputed here.
    """
    return "".join(
        [
            _overview(profile, findings, idea_report, action_plan, git),
            _findings_section(findings, project_root),
            _architecture_section(profile),
            _ideas_section(idea_report),
            quality_html,
            _shape_section(shape),
            _roadmap_section(roadmap),
            _roadmap_changes_section(project_root, roadmap),
            _proof_section(project_root),
            _dream_section(project_root),
            _pareto_section(pareto, getattr(idea_report, "stats", {}).get("total_ideas", 0)),
            _autonomy_section(autonomy),
            _trajectory_section(trajectory),
            _learned_section(learned),
            trackrecord_html,
            outscope_html,
            _actions_section(action_plan),
            _reasoning_section(reasoning),
            _debug_section(debug),
            _profile_section(profile),
            _repo_section(git),
        ]
    )


def _render_html(project_root, profile, findings, idea_report, action_plan, reasoning,
                 git=None, debug=None, roadmap=None, shape=None, autonomy=None,
                 pareto=None, trajectory=None, learned=None, quality=True) -> str:
    git = git or {}
    debug = debug or {}
    pareto = pareto or []
    trajectory = trajectory or []
    outscope_html = _outscope_section(project_root)
    trackrecord_html = _trackrecord_section(learned, project_root)
    # The quality card is the heaviest part of a build (4 full-tree re-parses);
    # ``quality=False`` skips it entirely. Default stays byte-identical.
    quality_html = _quality_section(project_root) if quality else ""
    links = _nav_links(
        project_root, git, debug, roadmap, shape, autonomy, pareto, trajectory,
        learned, outscope_html=outscope_html, trackrecord_html=trackrecord_html,
        quality_html=quality_html,
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hero_vitals = _hero_vitals(project_root, profile, findings, idea_report, action_plan)

    sections = _page_sections(
        project_root, profile, findings, idea_report, action_plan, reasoning,
        git, debug, roadmap, shape, autonomy, pareto, trajectory, learned,
        outscope_html=outscope_html, trackrecord_html=trackrecord_html,
        quality_html=quality_html,
    )
    mark = _BRAND_MARK
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Apex Dashboard — {_esc(project_root)}</title><style>{_CSS}</style></head><body>"
        f"<nav class='nav'><span class='brand'>{mark}<span class='dot'>Apex</span></span>"
        f"<span class='path'>{_esc(project_root)}</span><span class='links'>{links}</span></nav>"
        "<header class='hero'>"
        "<span class='eyebrow'><span class='pulse'></span>Deterministic &middot; zero-token &middot; LLM-free</span>"
        "<h1>Project Development Dashboard</h1>"
        "<p>A living read-out of the codebase organism — code intelligence, development ideas "
        "and supervised actions, computed offline with no model in the loop.</p>"
        f"{hero_vitals}"
        f"<p class='stamp'>generated {generated}</p></header>"
        f"<main>{sections}</main>"
        "<footer>Generated by Apex Orchestrator — deterministic, offline, self-contained."
        " &#10022; signed by <span class='sig'>barzeuss</span></footer>"
        "</body></html>"
    )
