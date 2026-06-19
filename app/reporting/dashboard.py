"""Human-facing HTML dashboard.

DETERMINISM SCOPE: this module is a *human snapshot*, NOT a byte-determinism
surface. The rendered page deliberately carries a wall-clock ``generated``
timestamp and the absolute ``project_root`` host path so a reader knows when and
where it was built; both vary per render/host by design and are therefore OUT OF
SCOPE for the "same repo state -> same bytes" guarantee. The single timestamp is
the only varying line (the path is constant for a given checkout), so CI that
wants stability normalizes that one line (see the dashboard characterization
tests). The actual byte-determinism guarantee is upheld by the analytical
surfaces — e.g. the ``apex scan`` stdout payload — not by this artifact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaPermutationEngine
from app.tools.project_profile import ProjectProfiler


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


def _plugin_operators() -> list[Any]:
    """Plugin-contributed operators that widen the idea alphabet (best-effort)."""
    try:
        from app.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.load_all()
        return registry.idea_operators()
    except Exception:
        return []


def _build_roadmap(idea_report):
    """Sequenced-plan roadmap over the idea tree; ``None`` if unavailable."""
    try:
        from app.engine.idea_roadmap import RoadmapSynthesizer

        return RoadmapSynthesizer().build(idea_report)
    except Exception:
        return None


def _build_shape(idea_report):
    """Tree-shape telemetry over the idea tree; ``None`` if unavailable."""
    try:
        from app.engine.idea_tree_shape import analyze_tree_shape

        return analyze_tree_shape(idea_report)
    except Exception:
        return None


def _build_pareto(roadmap) -> list[Any]:
    """Efficient frontier derived from the roadmap; ``[]`` if unavailable."""
    try:
        from app.engine.idea_pareto import frontier_from_roadmap

        return frontier_from_roadmap(roadmap) if roadmap is not None else []
    except Exception:
        return []


def _build_trajectory(project_root: str) -> list[Any]:
    """Self-improvement trajectory history; ``[]`` if unavailable."""
    try:
        from app.engine.evolution import load_history

        return load_history(project_root)
    except Exception:
        return []


def _build_learned(project_root: str):
    """Learned-memory summary for the project; ``None`` if unavailable."""
    try:
        from app.engine.idea_memory import IdeaMemory

        return IdeaMemory.load(project_root).summary()
    except Exception:
        return None


def _build_autonomy(action_plan, git) -> dict[str, Any] | None:
    """What ``apex auto`` would decide for this project right now; ``None`` on error."""
    try:
        from app.policies.autonomy_policy import AutonomyPolicy

        tree_clean = bool(git) and int(git.get("dirty", 0) or 0) == 0
        autonomy = AutonomyPolicy().decide(
            executable_steps=action_plan.stats.get("executable_steps", 0),
            working_tree_clean=tree_clean,
        ).to_dict()
        autonomy["executable"] = action_plan.stats.get("executable_steps", 0)
        return autonomy
    except Exception:
        return None


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

    idea_report = IdeaPermutationEngine(
        {"max_total_ideas": max_ideas, "max_idea_depth": idea_depth, "breadth": breadth},
        project_root,
        extra_operators=_plugin_operators(),
    ).run(objective=objective or None)
    action_plan = IdeaActionBridge().plan_tree(idea_report, top=15)

    roadmap = _build_roadmap(idea_report)
    shape = _build_shape(idea_report)
    pareto = _build_pareto(roadmap)
    trajectory = _build_trajectory(project_root)
    learned = _build_learned(project_root)
    reasoning = _run_reasoning(project_root, objective)
    git = _git_info(project_root)
    debug = _run_debug(project_root, profile)
    autonomy = _build_autonomy(action_plan, git)

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
#
# The markup primitives (``_esc`` / ``_chip`` / ``_card`` / ``_kpi`` /
# ``_severity_badge``) and the cohesive cluster of pure ``_<section>_section``
# renderers were extracted verbatim into ``dashboard_sections`` to keep this
# module focused on data gathering + page assembly. They are imported below so
# the page builder and existing callers/tests keep referencing them here.
from app.reporting.dashboard_sections import (  # noqa: F401  (re-exported)
    RenderedSections,
    _actions_section,
    _anchor_focus,
    _architecture_section,
    _autonomy_section,
    _card,
    _chip,
    _coordinator_block,
    _coverage_bar,
    _debug_section,
    _deep_nesting_block,
    _dream_section,
    _esc,
    _findings_section,
    _health_bars,
    _ideas_section,
    _kind_badge,
    _kind_badge_label,
    _kpi,
    _learned_section,
    _outscope_section,
    _outscope_test_corpus,
    _overview,
    _pareto_section,
    _profile_section,
    _proof_applied_count,
    _proof_section,
    _quality_pct_bar,
    _quality_section,
    _reasoning_section,
    _repo_section,
    _roadmap_changes_section,
    _roadmap_section,
    _scope_composition,
    _severity_badge,
    _shape_section,
    _trackrecord_section,
    _trajectory_section,
)


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


def _hero_coverage_pct(findings) -> int:
    """Coverage percentage from scanner findings, or ``-1`` when unavailable."""
    cov = findings.get("coverage", {}) or {}
    if "coverage_ratio" not in cov:
        return -1
    return int(cov.get("coverage_ratio", 0) * 100)


def _hero_security_count(findings) -> int:
    """Security finding count from scanner findings (``0`` when absent)."""
    sec = findings.get("security", {}) or {}
    return sec.get("findings_count", 0) or 0


def _hero_scope_pct(profile) -> int:
    """Analyzed-scope percentage from the project profile (``0`` when absent)."""
    return int(round(float(getattr(profile, "analyzed_ratio", 1.0) or 0.0) * 100))


def _hero_top_move(action_plan) -> str:
    """Title of the highest-priority action, or ``""`` when there are no steps."""
    steps = getattr(action_plan, "steps", None) or []
    return steps[0].title if steps else ""


def _hero_grade(project_root) -> tuple[str, int | None]:
    """Run the single deterministic health-grade pass (best-effort).

    Same light profile + detector pass as ``apex review``/``apex ascend``. A
    degraded grade just yields ``("", None)`` so the tile is omitted.
    """
    try:
        from app.engine.health_score import grade as _grade

        g = _grade(project_root)
        return g.letter, g.score
    except Exception:
        return "", None


def _hero_charts_html(grade_letter, grade_score, scope_pct) -> str:
    """The optional gauge + scope-bar chart strip; ``""`` when neither applies."""
    from app.reporting.dashboard_charts import grade_gauge, scope_bar

    gauge = grade_gauge(grade_score, grade_letter) if isinstance(grade_score, int) and grade_score >= 0 else ""
    scope_svg = scope_bar(scope_pct) if scope_pct >= 0 else ""
    return f"<div class='hero-charts'>{gauge}{scope_svg}</div>" if (gauge or scope_svg) else ""


def _hero_top_move_html(top_move) -> str:
    """The top-move paragraph rendered on its own line; ``""`` when empty."""
    return f"<p class='vital-top-move'>{_esc(top_move)}</p>" if top_move else ""


def _hero_vitals(project_root, profile, findings, idea_report, action_plan) -> str:
    """Build the hero "vital signs" banner: stat tiles + grade gauge + scope bar.

    Every input is data already computed for the page; the only extra work is one
    deterministic health-grade pass (light profile, no clock, no network). Each
    metric degrades gracefully to "omitted" when it is not available, so the banner
    never crashes and stays byte-identical for identical inputs.
    """
    from app.reporting.dashboard_hero import render_vitals

    scope_pct = _hero_scope_pct(profile)
    grade_letter, grade_score = _hero_grade(project_root)

    vitals = render_vitals(
        grade_letter=grade_letter,
        grade_score=grade_score,
        coverage_pct=_hero_coverage_pct(findings),
        security_findings=_hero_security_count(findings),
        scope_pct=scope_pct,
        idea_count=idea_report.stats.get("total_ideas", 0),
        runnable_actions=len(action_plan.executable_steps()),
        top_move="",  # rendered separately below so it sits on its own line
    )
    charts = _hero_charts_html(grade_letter, grade_score, scope_pct)
    top_html = _hero_top_move_html(_hero_top_move(action_plan))
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


def _shape_has_ideas(shape) -> bool:
    """The shape card renders only when it has at least one idea to describe."""
    return shape is not None and bool(getattr(shape, "total_ideas", 0))


def _roadmap_has_phases(roadmap) -> bool:
    """The roadmap card renders only when the roadmap carries phases."""
    return roadmap is not None and bool(getattr(roadmap, "phases", None))


def _learned_has_entries(learned) -> bool:
    """The learned card renders only when memory has reliable/unreliable entries."""
    return bool(learned and (learned.get("most_reliable") or learned.get("least_reliable")))


def _dream_exists(project_root) -> bool:
    """The dream card renders only when its digest file is present."""
    return (Path(project_root) / ".apex" / "dream-digest.md").exists()


def _middle_nav_links(
    project_root, git, debug, roadmap, shape, autonomy, pareto, trajectory,
    learned, sections: RenderedSections,
) -> list[tuple[str, str]]:
    """The optional, gated nav entries (in page order) between the fixed head/tail."""
    gated = [
        (bool(sections.quality_html), ("quality", "Quality")),
        (_shape_has_ideas(shape), ("shape", "Shape")),
        (_roadmap_has_phases(roadmap), ("roadmap", "Roadmap")),
        (bool(pareto), ("frontier", "Frontier")),
        (bool(autonomy), ("autonomy", "Autonomy")),
        (bool(trajectory), ("trajectory", "Trajectory")),
        (_learned_has_entries(learned), ("learned", "Learned")),
        (bool(sections.trackrecord_html), ("trackrecord", "Track record")),
        (bool(sections.outscope_html), ("outscope", "Out of scope")),
        (_dream_exists(project_root), ("dream", "Dream")),
    ]
    return [link for cond, link in gated if cond]


def _nav_links(
    project_root, git, debug, roadmap, shape, autonomy, pareto, trajectory,
    learned, *, sections: RenderedSections,
) -> str:
    """Build the sticky-nav anchor list, gating optional sections in page order.

    Mirrors the section assembly below: each conditional appends a link only when
    the matching section will render, so the nav never points at an empty anchor.
    The pre-rendered fragments that BOTH gate a nav link and appear in the body
    arrive bundled in ``sections`` (one arg instead of three parallel strings).
    """
    nav_links = [("overview", "Overview"), ("findings", "Findings"),
                 ("architecture", "Architecture"), ("ideas", "Ideas")]
    nav_links += _middle_nav_links(
        project_root, git, debug, roadmap, shape, autonomy, pareto, trajectory,
        learned, sections,
    )
    nav_links += [("actions", "Actions"), ("reasoning", "Reasoning"), ("profile", "Profile")]
    if debug:
        nav_links.append(("debug", "Debug"))
    if git:
        nav_links.append(("repository", "Repo"))
    return "".join(f"<a href='#{i}'>{_esc(t)}</a>" for i, t in nav_links)


def _page_sections(
    project_root, profile, findings, idea_report, action_plan, reasoning,
    git, debug, roadmap, shape, autonomy, pareto, trajectory, learned,
    *, sections: RenderedSections,
) -> str:
    """Concatenate every section renderer in page order.

    The fragments in ``sections`` (quality / track-record / out-of-scope) are
    passed in pre-rendered so the work is done exactly once (it also drives nav
    gating) rather than recomputed here.
    """
    return "".join(
        [
            _overview(profile, findings, idea_report, action_plan, git),
            _findings_section(findings, project_root),
            _architecture_section(profile),
            _ideas_section(idea_report),
            sections.quality_html,
            _shape_section(shape),
            _roadmap_section(roadmap),
            _roadmap_changes_section(project_root, roadmap),
            _proof_section(project_root),
            _dream_section(project_root),
            _pareto_section(pareto, getattr(idea_report, "stats", {}).get("total_ideas", 0)),
            _autonomy_section(autonomy),
            _trajectory_section(trajectory),
            _learned_section(learned),
            sections.trackrecord_html,
            sections.outscope_html,
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
    # The quality card is the heaviest part of a build (4 full-tree re-parses);
    # ``quality=False`` skips it entirely. Default stays byte-identical. These
    # three fragments are rendered once here because they both gate a nav link
    # AND appear in the body, then bundled so the assembly helpers take one arg.
    rendered = RenderedSections(
        quality_html=_quality_section(project_root) if quality else "",
        trackrecord_html=_trackrecord_section(learned, project_root),
        outscope_html=_outscope_section(project_root),
    )
    links = _nav_links(
        project_root, git, debug, roadmap, shape, autonomy, pareto, trajectory,
        learned, sections=rendered,
    )
    # OUT OF SCOPE for the "same repo state -> same bytes" guarantee: this is a
    # human snapshot, not a CI byte-determinism surface. The ``generated`` stamp
    # below is deliberately wall-clock (datetime.now), and ``project_root`` is
    # rendered as the absolute host path; both vary per render/host by design so
    # a human reading the page knows *when* and *where* it was built. CI that
    # needs byte-stability normalizes the single stamp line (see the dashboard
    # characterization tests) rather than this module guaranteeing it. The
    # byte-determinism guarantee is upheld by the analytical surfaces (e.g. the
    # ``apex scan`` stdout payload), not by this presentation artifact.
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hero_vitals = _hero_vitals(project_root, profile, findings, idea_report, action_plan)

    sections = _page_sections(
        project_root, profile, findings, idea_report, action_plan, reasoning,
        git, debug, roadmap, shape, autonomy, pareto, trajectory, learned,
        sections=rendered,
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
