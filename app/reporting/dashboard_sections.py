"""Pure section renderers for the Apex development dashboard.

This module holds the cohesive cluster of ``_<section>_section(...)`` builders
(plus their private block helpers and the shared markup primitives ``_esc`` /
``_chip`` / ``_card`` / ``_kpi`` / ``_severity_badge``) that turn already-computed
project data — profile, scan findings, the idea tree, roadmap, telemetry — into
self-contained HTML fragments. It was carved out of ``dashboard.py`` (which had
grown into a 1700-line god-module) as a pure move: every function here is the
same function, byte-for-byte, that previously lived in ``dashboard.py``; the page
assembler imports them unchanged.

Everything here is deterministic and stdlib-only: every codebase-sourced string
is HTML-escaped via :func:`html.escape`, no function carries a timestamp (the
page stamps once in ``dashboard.py``), and no network or remote resource is ever
touched. The same inputs always yield byte-identical fragments.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.engine.idea_permutation import render_mermaid
from app.models.idea import IdeaTreeReport
from app.tools.project_profile import ProjectProfile


@dataclass(frozen=True)
class RenderedSections:
    """The handful of section fragments that are rendered once, up front, in
    ``_render_html`` because they BOTH gate a nav link AND appear in the page
    body (so re-rendering would duplicate work and risk divergence).

    Bundling them into one small value object lets ``_nav_links`` and
    ``_page_sections`` take a single ``sections`` argument instead of three
    parallel keyword strings each — collapsing their signatures without changing
    a byte of the output (each field is the exact same pre-rendered HTML as
    before). All fields default to ``""`` so an omitted/absent section simply
    contributes nothing, exactly as the prior ``"" `` sentinels did.
    """

    quality_html: str = ""
    trackrecord_html: str = ""
    outscope_html: str = ""


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


def _is_fixture_path(path: str) -> bool:
    """True for example/test/fixture files, which may carry intentional risks.

    Mirrors ``health_score._is_fixture_path`` / ``ProjectProfiler._is_fixture_path``:
    the GRADE already excludes these from its security score (an
    ``examples/legacy_bank/...`` demo vulnerability is not a real risk in this
    project's own shipped code). ``SecurityAgent`` (which feeds this dashboard)
    does not apply that exclusion — it deliberately keeps fixture findings in
    the raw scan so nothing is silently dropped — so the dashboard must
    instead DISCLOSE which findings are excluded-from-grade fixtures rather
    than let them read as undifferentiated real risk.
    """
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _findings_chips(findings: dict[str, dict[str, Any]]) -> str:
    sec = findings.get("security", {})
    doc = findings.get("docstring", {})
    dep = findings.get("dependency", {})
    chips = [
        _chip("security findings", sec.get("findings_count", "—")),
        _chip("missing docstrings", doc.get("gaps_found", "—")),
        _chip("dependency edges", dep.get("total_edges", "—")),
        _chip("circular imports", len(dep.get("circular_imports", []) or [])),
    ]
    fixture_n = sum(1 for f in (sec.get("findings", []) or []) if _is_fixture_path(str(f.get("file", ""))))
    if fixture_n:
        chips.append(_chip("intentional fixtures (excluded from grade)", fixture_n))
    return "".join(chips)


def _findings_exposures(shown: list[dict[str, Any]], project_root: str) -> list[str]:
    # Exposure context: how long each finding has sat in the code, and whether
    # an entrypoint can reach it — the development context that turns a
    # finding into a decision. Best-effort: absent git/graph renders "—".
    if not (project_root and shown):
        return []
    try:
        from app.engine.exposure import analyze_exposure

        pairs = [(str(f.get("file", "")), int(f.get("line", 0) or 0)) for f in shown]
        return [e.describe() or "—" for e in analyze_exposure(project_root, pairs)]
    except Exception:
        return []


def _findings_row(f: dict[str, Any], exposure: str) -> str:
    issue = (
        f.get("details") or f.get("risk_type") or f.get("issue") or f.get("risk") or ""
    )
    # Disclose, never silently drop: a finding inside an example/test/fixture
    # file is excluded from the GRADE (health_score._is_fixture_path) because
    # it is often an intentional demo vulnerability, not a real one — but
    # hiding it here entirely would be the opposite failure (a security scan
    # that quietly under-reports). Label it in place instead.
    note = (
        " <em class='fixture-note'>(intentional fixture — excluded from grade)</em>"
        if _is_fixture_path(str(f.get("file", ""))) else ""
    )
    return (
        f"<tr><td><code>{_esc(f.get('file', '?'))}:{_esc(f.get('line', '?'))}</code></td>"
        f"<td>{_esc(issue)}{note}</td><td>{_severity_badge(f.get('severity', ''))}</td>"
        f"<td>{_esc(exposure)}</td></tr>"
    )


def _findings_table(shown: list[dict[str, Any]], exposures: list[str]) -> str:
    rows = ""
    for i, f in enumerate(shown):
        exposure = exposures[i] if i < len(exposures) else "—"
        rows += _findings_row(f, exposure)
    return (
        "<table><thead><tr><th>Location</th><th>Issue</th><th>Severity</th><th>Exposure</th></tr></thead>"
        f"<tbody>{rows or '<tr><td colspan=4 class=empty>No security findings 🎉</td></tr>'}</tbody></table>"
    )


def _findings_section(findings: dict[str, dict[str, Any]], project_root: str = "") -> str:
    sec = findings.get("security", {})
    cov = findings.get("coverage", {})
    chips = _findings_chips(findings)
    shown = (sec.get("findings", []) or [])[:12]
    exposures = _findings_exposures(shown, project_root)
    table = _findings_table(shown, exposures)
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
    from app.tools.project_profile import (
        honest_analyzed_ratio,
        honest_unanalyzed_count,
    )

    out_ratio = getattr(p, "out_of_scope_ratio", 0.0)
    if not isinstance(out_ratio, (int, float)):
        return ""
    # Render whenever a genuine analysed-vs-rest split exists: a polyglot
    # remainder (out-of-scope languages) OR in-language files that were counted
    # but NOT analysed (parse-failures / ``.pyi`` / over-cap). An all-analysed
    # all-Python repo (both zero) is omitted, so its page stays byte-identical.
    unanalyzed = honest_unanalyzed_count(p)
    if out_ratio <= 0.0 and unanalyzed <= 0:
        return ""
    analyzed = getattr(p, "analyzed_ratio", None)
    if not isinstance(analyzed, (int, float)):
        return ""

    from app.reporting.dashboard_charts import stacked_bar

    # The HONEST analysed fraction (single-sourced), so the bar reports the SAME
    # split as scope/pulse/readiness. The remainder is everything NOT truly
    # analysed (out-of-scope languages + unanalysed in-language files), derived as
    # ``1 - honest`` so the two segments always sum to 1. Equals the language
    # ratio when nothing was dropped, so the polyglot common case is unchanged.
    honest = honest_analyzed_ratio(p)
    segments = [
        ("Analysed (Python)", float(honest)),
        ("Out of scope", float(1.0 - honest)),
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


def _trackrecord_rates(learned: dict[str, Any] | None) -> list[dict[str, Any]]:
    """De-dup the learned per-fix-type rows by key and sort by rate desc, then key.

    Pure: most/least reliable operators carry ``{"key","success_rate","samples"}``
    and an operator can appear in both lists when only one is tracked, so the first
    occurrence per key wins (the most/least order is preserved by the caller).
    """
    learned = learned or {}
    by_key: dict[str, dict[str, Any]] = {}
    for row in (learned.get("most_reliable") or []) + (learned.get("least_reliable") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        if not key or key in by_key:
            continue
        by_key[key] = row
    return sorted(
        by_key.values(),
        key=lambda r: (-float(r.get("success_rate", 0.0) or 0.0), str(r.get("key", ""))),
    )


def _trackrecord_table(rates: list[dict[str, Any]]) -> str:
    """Render the landing-rate table, or "" when no rates are tracked. Pure."""
    rows = "".join(
        f"<tr><td><code>{_esc(r.get('key', ''))}</code></td>"
        f"<td class='num'>{int(float(r.get('success_rate', 0.0) or 0.0) * 100)}%</td>"
        f"<td class='num'>{_esc(r.get('samples', 0))}</td></tr>"
        for r in rates
    )
    if not rows:
        return ""
    return (
        "<table><thead><tr><th>Fix type</th><th>Landing rate</th>"
        "<th>Samples</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


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
    rates = _trackrecord_rates(learned)
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
    table = _trackrecord_table(rates)
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


def _quality_hotspots(heading: str, rows: list[str]) -> list[str]:
    """Wrap pre-rendered ``<li>`` ``rows`` in a titled ``.commits`` list block.

    Returns a one-element ``blocks`` fragment, or ``[]`` when there are no rows,
    so callers can ``+=`` unconditionally without an inline guard.
    """
    if not rows:
        return []
    return [
        f"<h4 style='margin:8px 0 4px'>{heading}</h4>"
        f"<ul class='commits'>{''.join(rows)}</ul>"
    ]


def _quality_type_hints(th: Any) -> tuple[list[str], list[str]]:
    """Render the type-hint-coverage analyzer (chip + bar + thinnest modules)."""
    if th is None or th.total_functions <= 0:
        return [], []
    chips = [_chip("type hints", f"{int(round(th.overall_ratio * 100))}%")]
    blocks = [_quality_pct_bar(
        "Type-hint coverage", th.overall_ratio,
        f"{th.annotated_functions}/{th.total_functions} functions fully annotated",
    )]
    worst = [m for m in th.worst_modules if m.get("ratio", 1.0) < 1.0][:5]
    rows = [
        f"<li><code>{_esc(m.get('module', '?'))}</code> "
        f"<span class='val'>{int(round(float(m.get('ratio', 0)) * 100))}%</span> "
        f"<span class='muted'>({_esc(m.get('annotated', 0))}/"
        f"{_esc(m.get('total', 0))})</span></li>"
        for m in worst
    ]
    blocks += _quality_hotspots("Thinnest-typed modules", rows)
    return chips, blocks


def _quality_docstrings(dc: Any) -> tuple[list[str], list[str]]:
    """Render the public-docstring-coverage analyzer (chip + bar)."""
    if dc is None or dc.total_public <= 0:
        return [], []
    chips = [_chip("public docs", f"{int(round(dc.overall_public_ratio * 100))}%")]
    blocks = [_quality_pct_bar(
        "Public docstring coverage", dc.overall_public_ratio,
        f"{dc.documented_public}/{dc.total_public} public symbols documented",
    )]
    return chips, blocks


def _quality_complexity(cx: Any) -> tuple[list[str], list[str]]:
    """Render the cyclomatic-complexity analyzer (chips + summary + hotspots)."""
    if cx is None or cx.total <= 0:
        return [], []
    chips = [
        _chip(f"complexity > {cx.threshold}", cx.over_threshold),
        _chip("max complexity", cx.max),
    ]
    blocks = [
        "<p class='muted' style='margin:6px 0 4px'>"
        f"{_esc(cx.over_threshold)} of {_esc(cx.total)} functions exceed "
        f"complexity {_esc(cx.threshold)} "
        f"(mean {_esc(cx.mean)} · median {_esc(cx.median)} · max {_esc(cx.max)}).</p>"
    ]
    rows = [
        f"<li><code>{_esc(h.get('module', '?'))}</code>"
        f"<span class='muted'>·</span><code>{_esc(h.get('function', '?'))}</code> "
        f"<span class='val'>{_esc(h.get('complexity', 0))}</span></li>"
        for h in cx.hotspots[:5]
    ]
    blocks += _quality_hotspots("Complexity hotspots", rows)
    return chips, blocks


def _quality_todo_debt(td: Any) -> tuple[list[str], list[str]]:
    """Render the inline TODO/FIXME debt census (chip + summary + recent markers)."""
    if td is None or td.total <= 0:
        return [], []
    chips = [_chip("debt markers", td.total)]
    by = " · ".join(
        f"{_esc(k)} {_esc(v)}" for k, v in td.by_marker.items() if v
    )
    blocks = [
        f"<p class='muted' style='margin:6px 0 4px'>{_esc(td.total)} inline "
        f"debt markers — {by}</p>"
    ]
    rows = [
        f"<li><code>{_esc(i.get('module', '?'))}:{_esc(i.get('line', '?'))}</code> "
        f"<span class='op'>{_esc(i.get('marker', ''))}</span> "
        f"<span class='muted'>{_esc(i.get('text', ''))}</span></li>"
        for i in td.items[:5]
    ]
    blocks += _quality_hotspots("Recent markers", rows)
    return chips, blocks


def _quality_run(project_root: str, module: str, func: str) -> Any:
    """Import ``func`` from ``app.tools.<module>`` and run it over ``project_root``.

    Returns ``None`` if the module is absent or the analyzer raises, so a single
    analyzer failure degrades to "omitted" rather than breaking the card.
    """
    try:
        mod = __import__(f"app.tools.{module}", fromlist=[func])
        return getattr(mod, func)(project_root)
    except Exception:
        return None


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
    renderers = (
        (_quality_type_hints, "type_hint_coverage", "analyze_type_hint_coverage"),
        (_quality_docstrings, "docstring_coverage", "analyze_docstring_coverage"),
        (_quality_complexity, "complexity_profile", "analyze_complexity"),
        (_quality_todo_debt, "todo_debt", "analyze_todo_debt"),
    )
    for render, module, func in renderers:
        c, b = render(_quality_run(project_root, module, func))
        chips += c
        blocks += b

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


_PROOF_OUTCOME_ICON = {"applied": "✅", "rolled_back": "↩️", "blocked": "⛔",
                       "applied & withheld": "🚧"}
_PROOF_STRENGTH_LABEL = {
    "function": "💪 names the changed function",
    "module": "✔️ suite references the module",
    "none": "⚠️ applied blind (no covering test)",
    "test-change": "🧪 test change",
}


def _proof_row_why(fix: dict, outcome: str, withheld: bool) -> str:
    """The WHY sub-blocks (impact line + collapsed diff) for one proof row.

    A CLEAN applied fix (outcome ``applied``, not withheld) returns ``""`` — its
    diff/impact are DELIBERATELY suppressed so the row stays byte-identical to
    the pre-WHY renderer (a clean apply's diff is not a "why", and rendering it
    on every applied row would bloat the page; the full diff of every move
    always remains in ``.apex/proof-of-fix.json`` and ``apex proof``). Only a
    NON-clean move (rolled-back / blocked / withheld / applied-and-withheld)
    surfaces them, where they EXPLAIN the outcome. Both fields are read with the
    same defensive ``.get(...) or ''`` and appended ONLY when truthy; the diff is
    ``html.escape``d (XSS guard: a failing-test line or a filename with
    HTML-special chars can never inject markup)."""
    if outcome == "applied" and not withheld:
        return ""
    impact = fix.get("impact") or ""
    impact_html = f"<div class='muted'>{_esc(impact)}</div>" if impact else ""
    diff = fix.get("diff") or ""
    diff_html = (f"<details><summary>diff</summary><pre>{_esc(diff)}</pre></details>"
                 if diff else "")
    return impact_html + diff_html


def _proof_row(fix: dict) -> str:
    """One ``<tr>`` of the proof-of-fix table for a stored ``fixes[]`` record.

    Surfaces the WHY behind a non-clean move — the honest disposition (an
    applied-but-withheld fix is its own state, with the gate that fired), the one
    honest reason, the measured impact, and the full diff (:func:`_proof_row_why`)
    — reusing the SAME helpers ``apex proof`` ships so the two renderers can never
    diverge. A CLEAN applied fix renders exactly the outcome/action/target/
    strength/shield it always did — its ``reason`` is empty (``—`` cell) and its
    WHY block is empty — so its row is byte-identical to before but for that one
    ``—`` reason cell.
    """
    from app.cli_insight import _proof_disposition, _proof_reason

    finding = fix.get("finding") or {}
    strength = ((fix.get("verification") or {}).get("strength") or {}).get("level", "")
    shield = fix.get("shield_test", "")
    outcome = str(fix.get("outcome") or "")
    withheld = bool(fix.get("commit_withheld"))
    display_outcome, _committed = _proof_disposition(fix, outcome, withheld)
    reason = _proof_reason(fix, outcome, withheld) or ""
    why_html = _proof_row_why(fix, outcome, withheld)
    return (
        f"<tr><td>{_PROOF_OUTCOME_ICON.get(display_outcome, '·')} "
        f"{_esc(display_outcome)}</td>"
        f"<td>{_esc(finding.get('action', ''))}{why_html}</td>"
        f"<td><code>{_esc(finding.get('target', ''))}</code></td>"
        f"<td>{_esc(_PROOF_STRENGTH_LABEL.get(strength, '—'))}</td>"
        f"<td>{('🛡️ <code>' + _esc(shield) + '</code>') if shield else '—'}</td>"
        f"<td>{_esc(reason) if reason else '—'}</td></tr>"
    )


def _proof_section(project_root: str) -> str:
    """The last maintenance pass's evidence record — outcomes, verification
    strength, shields, and (additively) the WHY a move rolled back / was
    blocked / was withheld, straight from .apex/proof-of-fix.json."""
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
    rows = "".join(_proof_row(fix) for fix in (proof.get("fixes") or [])[:12])
    if not rows:
        return ""
    table = ("<table><thead><tr><th>Outcome</th><th>Action</th><th>Target</th>"
             "<th>Verification strength</th><th>Shield</th><th>Reason</th></tr></thead>"
             f"<tbody>{rows}</tbody></table>")
    sub = f"<p class='muted'>Generated {_esc(proof.get('generated_at', ''))} · full evidence (diffs, test runs) in <code>.apex/proof-of-fix.json</code></p>"
    return _card("proof", "🧾", "Proof of fix — last maintenance pass",
                 f"<div class='chips'>{chips}</div>{table}{sub}")


def _roadmap_changes_diff(project_root: str, roadmap):
    """Load the saved roadmap snapshot and diff ``roadmap`` against it.

    Returns the ``RoadmapDiff`` (best-effort), or ``None`` when there is no
    roadmap/phases, no snapshot to compare against, or any load/diff step raises —
    so the caller gates to "" in every absent case, byte-identical to before.
    """
    if roadmap is None or not getattr(roadmap, "phases", None):
        return None
    try:
        from pathlib import Path as _Path

        from app.engine.roadmap_history import diff_roadmaps, load_snapshot

        snapshot = load_snapshot(_Path(project_root) / ".apex" / "roadmap-snapshot.json")
        if not snapshot:
            return None
        return diff_roadmaps(snapshot, roadmap)
    except Exception:
        return None


def _roadmap_changes_signals(diff) -> list[str]:
    """The two optional signal-narration paragraphs (new work / stopped firing). Pure."""
    from app.engine.roadmap_history import _count_signals, _signal_phrase

    parts: list[str] = []
    new_signals = _count_signals(diff.new)
    gone_signals = _count_signals(diff.dropped)
    if new_signals:
        parts.append(f"<p><b>Where the new work comes from:</b> {_esc(_signal_phrase(new_signals))}</p>")
    if gone_signals:
        parts.append(f"<p><b>Signals that stopped firing:</b> {_esc(_signal_phrase(gone_signals))}</p>")
    return parts


def _roadmap_changes_items(diff) -> str:
    """Render the new (🆕) then dropped (✅) change ``<li>`` items (capped at 6 each). Pure."""
    return "".join(
        f"<li>🆕 [{_esc(c.curr_phase)}] {_esc(c.title)}"
        + (f" — <code>{_esc(c.grounded_in)}</code>" if c.grounded_in else "") + "</li>"
        for c in diff.new[:6]
    ) + "".join(
        f"<li>✅ {_esc(c.title)}"
        + (f" — its <code>{_esc(c.signal)}</code> signal no longer fires" if c.signal else "")
        + "</li>"
        for c in diff.dropped[:6]
    )


def _roadmap_changes_section(project_root: str, roadmap) -> str:
    """Cross-run roadmap story: which signals produced the new work, which
    stopped firing — when a saved snapshot exists to compare against."""
    diff = _roadmap_changes_diff(project_root, roadmap)
    if diff is None or not (diff.new or diff.dropped):
        return ""
    parts = [f"<div class='chips'>{_chip('new', len(diff.new))}"
             f"{_chip('no longer surfaced', len(diff.dropped))}"
             f"{_chip('stable', diff.stable_count)}</div>"]
    parts.extend(_roadmap_changes_signals(diff))
    items = _roadmap_changes_items(diff)
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

