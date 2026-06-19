"""Honest real-world readiness measurement for Apex's develop-loop.

Apex grades itself A+ on itself. The question a *buyer* asks is different: run
Apex on a MESSY external project — what fraction of what it finds does it
actually AUTO-FIX (with a deterministic, test-verified transform) versus merely
FLAG for a human to decide? That "fixer vs linter" ratio is the honest measure
of real-world readiness, and this module computes it without touching the tree.

It reuses the EXISTING plan-building path end-to-end — it invents no analysis:

  ``IdeaPermutationEngine(project_root).run()``  → the idea tree (real seeding),
  ``IdeaActionBridge().plan_tree(report)``       → the action plan (real steps),

and then reads the plan's own ``executable`` flag — already the bridge's verdict
on whether a deterministic transform exists for a step — to split steps into
EXECUTABLE (auto-fixable) and RECOMMEND-ONLY (flag) buckets. The actionability
ratio is::

    actionability = executable_steps / total_steps        (0.0 when no steps)

``readiness_summary`` widens that into the "what would a user actually get" view
by folding in the profiler's analysis-scope accounting (how much of a polyglot
repo Apex's Python-only analysis even covers) and a count of high-confidence
findings (Python security findings + non-Python ``polyglot_findings``).

Everything here is DRY-RUN: nothing is generated, applied, or written to the
target. Deterministic (sorted, no time/random). Best-effort: any sub-analysis
that fails contributes its empty/zero section instead of raising.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

__all__ = [
    "fix_actionability",
    "readiness_summary",
    "render_readiness_markdown",
]


def _build_plan(root: str):
    """Reuse the existing ideate plan-building path; never apply or write.

    Returns the ``ActionPlan`` the bridge produces for ``root`` (the same plan
    ``apply_plan`` would consume in dry-run), or ``None`` if plan-building
    fails — keeping callers best-effort.
    """
    return _build_plan_with_profile(root)[0]


def _build_plan_with_profile(root: str):
    """The ideate plan AND the full profile the engine already built for it.

    The engine profiles the tree once during ``run()`` and stashes it on
    ``last_profile``; returning it lets :func:`readiness_summary` reuse that
    profile for its scope/findings sections instead of profiling a SECOND time.
    Returns ``(plan, profile)`` — ``(None, None)`` on failure (best-effort)."""
    try:
        from app.engine.idea_action_bridge import IdeaActionBridge
        from app.engine.idea_permutation import IdeaPermutationEngine

        engine = IdeaPermutationEngine(project_root=root)
        report = engine.run()
        plan = IdeaActionBridge().plan_tree(report, project_root=root)
        return plan, getattr(engine, "last_profile", None)
    except Exception:
        return None, None


def _profile(root: str):
    """Reuse the existing profiler; ``None`` on failure (best-effort)."""
    try:
        from app.tools.project_profile import ProjectProfiler

        return ProjectProfiler(str(root)).profile()
    except Exception:
        return None


def _polyglot_findings(root: str) -> list[dict]:
    """High-confidence non-Python findings (reuse existing scan); [] on failure."""
    try:
        from app.engine.polyglot_findings import scan_polyglot_findings

        return scan_polyglot_findings(str(root))
    except Exception:
        return []


def fix_actionability(root: str) -> dict[str, Any]:
    """Measure the fixer-vs-linter ratio of Apex's plan for ``root``.

    Builds the real ideate action plan (DRY-RUN — nothing written) and splits
    its steps by the bridge's own ``executable`` verdict: an executable step has
    a deterministic, test-verifiable transform (Apex can AUTO-FIX it); a
    recommend-only step is a design/flag decision Apex surfaces for a human.

    Returns a deterministic dict::

        {
          "total_steps", "executable_steps", "flag_steps",
          "actionability",                      # executable / total in [0,1]
          "by_action_type": {action_type: count, ...},        # all steps
          "executable_action_types": {action_type: count, ...},
          "flag_action_types": {action_type: count, ...},
        }

    Best-effort: a project with no plan / no steps yields all-zero counts and
    ``actionability == 0.0`` (never raises).
    """
    return _actionability_from_plan(_build_plan(root))


def _actionability_from_plan(plan) -> dict[str, Any]:
    """The fixer-vs-linter split for an ALREADY-built plan (``None`` -> zeros).

    Split out so :func:`readiness_summary` can reuse a single plan/profile build
    instead of building the (expensive) ideate plan a second time."""
    steps = list(plan.steps) if plan is not None else []
    total = len(steps)
    executable = sum(1 for s in steps if s.executable)
    flag = total - executable

    by_action: Counter[str] = Counter()
    exec_action: Counter[str] = Counter()
    flag_action: Counter[str] = Counter()
    for step in steps:
        action = step.action_type or "<unknown>"
        by_action[action] += 1
        (exec_action if step.executable else flag_action)[action] += 1

    return {
        "total_steps": total,
        "executable_steps": executable,
        "flag_steps": flag,
        "actionability": round(executable / total, 4) if total else 0.0,
        "by_action_type": dict(sorted(by_action.items())),
        "executable_action_types": dict(sorted(exec_action.items())),
        "flag_action_types": dict(sorted(flag_action.items())),
    }


def _scope_section(profile) -> dict[str, Any]:
    """Repo-analyzability coverage, read from the profiler's scope accounting."""
    if profile is None:
        return {
            "source_files": 0,
            "python_files": 0,
            "analyzed_ratio": 0.0,
            "out_of_scope_ratio": 0.0,
            "language_breakdown": {},
        }
    return {
        "source_files": int(getattr(profile, "source_file_count", 0)),
        "python_files": int(getattr(profile, "python_file_count", 0)),
        "analyzed_ratio": round(float(getattr(profile, "analyzed_ratio", 0.0)), 4),
        "out_of_scope_ratio": round(float(getattr(profile, "out_of_scope_ratio", 0.0)), 4),
        "language_breakdown": dict(sorted(
            (getattr(profile, "language_breakdown", {}) or {}).items())),
    }


def _findings_section(profile, polyglot: list[dict]) -> dict[str, Any]:
    """High-confidence findings: Python security modules + polyglot findings."""
    py_security = sorted(getattr(profile, "security_finding_modules", []) or []) \
        if profile is not None else []
    poly_kinds: Counter[str] = Counter(
        f.get("kind", "<unknown>") for f in polyglot)
    return {
        "python_security_modules": py_security,
        "python_security_count": len(py_security),
        "polyglot_findings_count": len(polyglot),
        "polyglot_findings_by_kind": dict(sorted(poly_kinds.items())),
        "high_confidence_total": len(py_security) + len(polyglot),
    }


def readiness_summary(root: str) -> dict[str, Any]:
    """The honest "what would a user actually get" view of Apex on ``root``.

    Combines :func:`fix_actionability` (the auto-fix-vs-flag ratio) with two
    grounding sections, all from existing analysis and all DRY-RUN:

      * ``scope``   — how much of the repo is even analyzable (Python vs
        polyglot-only vs out-of-scope), from the profiler's scope accounting;
      * ``findings`` — high-confidence findings count (Python security findings
        + non-Python ``polyglot_findings``).

    Deterministic; best-effort (a failing sub-analysis contributes its
    empty/zero section, never raises).
    """
    # Build the plan and reuse the engine's profile in ONE pass (the plan build
    # already profiled the tree) instead of profiling again for scope/findings.
    plan, profile = _build_plan_with_profile(root)
    if profile is None:
        profile = _profile(root)  # plan build failed — fall back to a fresh profile
    polyglot = _polyglot_findings(root)
    scope = _scope_section(profile)
    # Honesty marker: when the profiler failed ENTIRELY there is no scope to
    # report. The all-zero section would otherwise read as a *confident* "0%
    # analyzed · 0% out of scope" — logically inconsistent. Flag it so the
    # renderer can say "unknown — analysis unavailable" instead of two zeros.
    # The flag is purely additive (the profile-present path is unchanged), and
    # ``_scope_section`` itself keeps its pinned, profile-driven dict shape.
    scope["analyzable"] = profile is not None
    return {
        "root": str(root),
        "actionability": _actionability_from_plan(plan),
        "scope": scope,
        "findings": _findings_section(profile, polyglot),
    }


def _verdict(actionability: float) -> str:
    """A plain, deterministic reading of the fixer-vs-linter ratio."""
    if actionability >= 0.6:
        return "auto-fixer — most planned steps have a deterministic transform"
    if actionability >= 0.3:
        return "mixed — a meaningful share auto-fixes, the rest is flag-only"
    return "mostly linter — most findings are flagged for a human, not auto-fixed"


def _actionability_lines(act: dict[str, Any]) -> list[str]:
    """Render the actionability block (shared by the markdown report)."""
    pct = int(round(act["actionability"] * 100))
    lines = [
        "## Fixer vs Linter",
        "",
        f"- **Actionability:** {pct}% "
        f"({act['executable_steps']}/{act['total_steps']} steps auto-fixable) — "
        f"{_verdict(act['actionability'])}",
        f"- **Auto-fixable steps:** {act['executable_steps']}",
        f"- **Flag-only steps:** {act['flag_steps']}",
        "",
        "### Auto-fixable by action",
    ]
    exec_types = act["executable_action_types"]
    lines += [f"- `{a}` × {n}" for a, n in exec_types.items()] or ["- (none)"]
    lines += ["", "### Flag-only by action"]
    flag_types = act["flag_action_types"]
    lines += [f"- `{a}` × {n}" for a, n in flag_types.items()] or ["- (none)"]
    return lines


def _scope_lines(scope: dict[str, Any]) -> list[str]:
    """Render the analyzability/coverage block.

    When ``analyzable`` is present and False (the profiler failed entirely),
    the coverage percentages are unknown — reporting "0% analyzed · 0% out of
    scope" would be a confident-looking lie, so we render an explicit
    "unknown — analysis unavailable" line instead. The profile-present path
    (``analyzable`` absent or True) is byte-identical to before.
    """
    lines = [
        "## Repo Coverage",
        "",
        f"- **Source files:** {scope['source_files']} "
        f"({scope['python_files']} Python)",
    ]
    if not scope.get("analyzable", True):
        lines.append("- **Analyzed (Python):** unknown — analysis unavailable")
    else:
        analyzed_pct = int(round(scope["analyzed_ratio"] * 100))
        out_pct = int(round(scope["out_of_scope_ratio"] * 100))
        lines.append(
            f"- **Analyzed (Python):** {analyzed_pct}% · "
            f"**out of scope:** {out_pct}%")
    breakdown = scope["language_breakdown"]
    if breakdown:
        langs = ", ".join(f"{lang} {n}" for lang, n in breakdown.items())
        lines.append(f"- **Non-Python languages:** {langs}")
    return lines


def _findings_lines(findings: dict[str, Any]) -> list[str]:
    """Render the high-confidence findings block."""
    lines = [
        "## High-Confidence Findings",
        "",
        f"- **Total:** {findings['high_confidence_total']} "
        f"(Python security {findings['python_security_count']} · "
        f"polyglot {findings['polyglot_findings_count']})",
    ]
    by_kind = findings["polyglot_findings_by_kind"]
    if by_kind:
        kinds = ", ".join(f"{k} {n}" for k, n in by_kind.items())
        lines.append(f"- **Polyglot findings by kind:** {kinds}")
    return lines


def render_readiness_markdown(root: str) -> str:
    """Render the readiness summary for ``root`` as deterministic markdown.

    A single, reproducible report: the fixer-vs-linter actionability ratio with
    its per-action breakdown, repo analyzability coverage, and a high-confidence
    findings count. Pure formatting over :func:`readiness_summary` (DRY-RUN).
    """
    summary = readiness_summary(root)
    name = Path(str(root)).resolve().name or str(root)
    lines = [f"# Apex Readiness — {name}", ""]
    lines += _actionability_lines(summary["actionability"])
    lines += [""] + _scope_lines(summary["scope"])
    lines += [""] + _findings_lines(summary["findings"])
    return "\n".join(lines) + "\n"
