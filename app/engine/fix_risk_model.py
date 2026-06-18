"""Fix-risk model — a forward-looking rollback risk from the proof history.

Apex already RECORDS what its own fixes did: every maintenance pass leaves a
``.apex/proof-of-fix.json`` whose per-fix ``outcome`` is ``applied`` /
``rolled_back`` / ``blocked`` (see ``proof_of_fix.py``). Two read-only learners
distil that trail — ``proof_history`` rewards what LANDS (per-action
``learned_reliability`` and a track-record summary), and
``counterfactual_learning`` mines what did NOT land into ``(action | trait)``
failure signatures with a deterministic ``avoid`` verdict. Both are purely
descriptive: nothing yet turns them into a number a *planner* can read.

This module is that missing intelligence layer. Given a PROPOSED fix — an
``(action_type, module)`` pair — it fuses the recorded evidence into a single
**risk score** in ``[0, 1]``: ``0`` means "this kind of fix has historically
landed cleanly here", ``1`` means "this kind of fix predictably rolls back".
A later wave can let the planner deprioritise high-risk fixes; this module
never applies, blocks, or mutates anything — it is pure read-only analysis.

Scoring (all deterministic — same proof files → same score, no time/random):

* **Neutral baseline** is ``0.5`` — with NO evidence at all we know nothing, so
  a proposed fix is neither safe nor risky. Every signal below nudges away from
  ``0.5`` only when it has real evidence to cite.
* **Reliability signal** (weight ``_W_RELIABILITY = 0.45``): the per-action
  ``learned_reliability`` score ``r`` in ``[0, 1]`` (share of that action's
  outcomes that landed). Higher reliability → lower risk, contributing
  ``(1 - r)``. Absent action → this signal abstains (contributes the baseline
  ``0.5``) so an unseen action is not punished.
* **Track-record signal** (weight ``_W_TRACK = 0.25``): the same landing ratio
  read at the (action, module) granularity from ``summarise_fix_track_record``;
  it backs the reliability view with module-specific evidence and likewise
  contributes ``(1 - ratio)``, abstaining (``0.5``) when neither the action nor
  the module has a record.
* **Counterfactual signal** (weight ``_W_AVOID = 0.30``): if
  ``should_avoid(failure_signatures(history), action_type, module_traits(module))``
  fires, this signal contributes ``1.0`` (a strong, evidence-backed risk bump);
  otherwise it contributes the baseline ``0.5`` (abstain — "no avoid lesson").

The three weighted contributions are averaged (weights sum to ``1.0``) and the
result is clamped to ``[0, 1]`` and rounded to ``_PRECISION`` places. With an
empty/missing history every signal abstains, so the score is exactly the
baseline ``0.5``.

Everything is **best-effort at the I/O edge**: a missing ``.apex`` dir,
unreadable proofs, or malformed rows are tolerated by the underlying loaders, so
this module never raises — the worst case is the neutral baseline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engine.counterfactual_learning import (
    failure_signatures,
    module_traits,
    should_avoid,
)
from app.engine.proof_history import (
    learned_reliability,
    load_proof_history,
    summarise_fix_track_record,
)

# The score with no evidence: neither safe nor risky.
_BASELINE = 0.5

# Signal weights — sum to 1.0 so a weighted average stays in [0, 1].
_W_RELIABILITY = 0.45
_W_TRACK = 0.25
_W_AVOID = 0.30

# Fixed rounding for every emitted float, so scores compare byte-for-byte.
_PRECISION = 4

# How many riskiest entries the report surfaces per dimension.
_TOP_N = 5


def _clamp(value: float) -> float:
    """Bound a raw score to ``[0.0, 1.0]`` (never below 0, never above 1)."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _reliability_risk(reliabilities: dict[str, float], action_type: str) -> float:
    """Risk contributed by the per-action reliability view, in ``[0, 1]``.

    A known action contributes ``1 - reliability`` (reliable → low risk); an
    unseen action abstains at the neutral baseline so it is not punished."""
    score = reliabilities.get(action_type)
    if score is None:
        return _BASELINE
    return _clamp(1.0 - float(score))


def _track_risk(summary: dict, action_type: str, module: str) -> float:
    """Risk from the (action, module) track record, in ``[0, 1]``.

    Prefers a module-specific landing ratio when the proof history has acted on
    that module before, else the action's ratio, else abstains at the baseline.
    Contribution is ``1 - ratio`` so a high-landing key reads as low risk."""
    by_module = summary.get("by_module") or {}
    by_action = summary.get("by_action") or {}
    entry = by_module.get(module)
    if not isinstance(entry, dict) or not entry.get("total"):
        entry = by_action.get(action_type)
    if not isinstance(entry, dict) or not entry.get("total"):
        return _BASELINE
    ratio = float(entry.get("reliability") or 0.0)
    return _clamp(1.0 - ratio)


def _avoid_risk(signatures: dict[str, dict[str, Any]], action_type: str, module: str) -> float:
    """Risk from the counterfactual avoid-guard: ``1.0`` if it fires else baseline."""
    if should_avoid(signatures, action_type, module_traits(module)):
        return 1.0
    return _BASELINE


def _score(
    reliabilities: dict[str, float],
    summary: dict,
    signatures: dict[str, dict[str, Any]],
    action_type: str,
    module: str,
) -> dict[str, Any]:
    """Fuse the three signals for one (action, module) into a scored evidence dict.

    Returns the rounded ``risk`` plus the rounded per-signal contributions and a
    sorted ``evidence`` list naming which signals carried real evidence (i.e.
    departed from the neutral baseline)."""
    reliability = _reliability_risk(reliabilities, action_type)
    track = _track_risk(summary, action_type, module)
    avoid = _avoid_risk(signatures, action_type, module)
    raw = (
        _W_RELIABILITY * reliability
        + _W_TRACK * track
        + _W_AVOID * avoid
    )
    risk = round(_clamp(raw), _PRECISION)
    evidence: list[str] = []
    if reliability != _BASELINE:
        evidence.append("reliability")
    if track != _BASELINE:
        evidence.append("track_record")
    if avoid >= 1.0:
        evidence.append("counterfactual_avoid")
    return {
        "action_type": action_type,
        "module": module,
        "risk": risk,
        "reliability_risk": round(reliability, _PRECISION),
        "track_risk": round(track, _PRECISION),
        "avoid_risk": round(avoid, _PRECISION),
        "evidence": sorted(evidence),
    }


def fix_risk(root: str | Path, action_type: str, module: str) -> float:
    """Forward-looking rollback risk for a proposed fix, in ``[0.0, 1.0]``.

    ``0`` = the proof history says this kind of fix lands cleanly here; ``1`` =
    it predictably rolls back. Fuses the per-action ``learned_reliability``, the
    (action, module) track record, and the counterfactual avoid-guard as
    documented in the module docstring. Empty/missing history → the neutral
    baseline ``0.5``. Pure and deterministic; never raises."""
    history = load_proof_history(root)
    reliabilities = learned_reliability(history)
    summary = summarise_fix_track_record(history)
    signatures = failure_signatures(history)
    return _score(
        reliabilities, summary, signatures, str(action_type), str(module)
    )["risk"]


def rank_fix_risks(
    root: str | Path, candidates: list[tuple[str, str]]
) -> list[dict]:
    """Score each ``(action_type, module)`` candidate and rank riskiest first.

    Returns one evidence dict per candidate (see :func:`_score`), sorted
    deterministically by descending ``risk`` then by the ``(action_type,
    module)`` key so ties are stable. The proof history is read ONCE and reused
    across candidates. An empty candidate list → ``[]``; never raises."""
    history = load_proof_history(root)
    reliabilities = learned_reliability(history)
    summary = summarise_fix_track_record(history)
    signatures = failure_signatures(history)
    scored = [
        _score(
            reliabilities, summary, signatures, str(action), str(module)
        )
        for action, module in (candidates or [])
    ]
    scored.sort(key=lambda d: (-d["risk"], d["action_type"], d["module"]))
    return scored


def fix_risk_report(root: str | Path) -> dict:
    """Deterministic summary of what the proof history implies about fix risk.

    Reads the history once and reports the overall landing reliability, the
    riskiest action types and modules (each scored against itself, i.e. the
    action/module pair the history actually recorded), and the counterfactual
    avoid lessons. Empty/missing history → zeroed counts and empty lists with
    the neutral ``overall_reliability`` of ``0.0``; never raises."""
    history = load_proof_history(root)
    reliabilities = learned_reliability(history)
    summary = summarise_fix_track_record(history)
    signatures = failure_signatures(history)

    riskiest_actions = sorted(
        (
            {"action_type": action, "risk": round(_clamp(1.0 - score), _PRECISION)}
            for action, score in reliabilities.items()
        ),
        key=lambda d: (-d["risk"], d["action_type"]),
    )[:_TOP_N]

    by_module = summary.get("by_module") or {}
    riskiest_modules = sorted(
        (
            {
                "module": module,
                "risk": round(_clamp(1.0 - float(stats.get("reliability") or 0.0)), _PRECISION),
            }
            for module, stats in by_module.items()
            if isinstance(stats, dict) and stats.get("total")
        ),
        key=lambda d: (-d["risk"], d["module"]),
    )[:_TOP_N]

    avoid_signatures = sorted(
        key for key, stats in signatures.items()
        if isinstance(stats, dict) and stats.get("avoid")
    )

    totals = summary.get("totals") or {}
    return {
        "proofs": summary.get("proofs", 0),
        "fixes": summary.get("fixes", 0),
        "overall_reliability": round(float(totals.get("reliability") or 0.0), _PRECISION),
        "rolled_back": int(totals.get("rolled_back") or 0),
        "blocked": int(totals.get("blocked") or 0),
        "riskiest_actions": riskiest_actions,
        "riskiest_modules": riskiest_modules,
        "avoid_signatures": avoid_signatures,
    }


def render_fix_risk_markdown(root: str | Path) -> str:
    """Pure formatting over :func:`fix_risk_report` — a human-readable digest.

    Deterministic: sorted sections, fixed precision, no time/random. An empty
    history renders an explicit "no proof history" notice. Never raises."""
    report = fix_risk_report(root)
    lines: list[str] = ["# Fix-Risk Model", ""]
    if not report["fixes"]:
        lines.append("_No proof history — every fix scores the neutral baseline (0.5)._")
        return "\n".join(lines) + "\n"

    lines.append(
        f"Proofs: {report['proofs']} | fixes: {report['fixes']} | "
        f"overall reliability: {report['overall_reliability']}"
    )
    lines.append(
        f"Rolled back: {report['rolled_back']} | blocked: {report['blocked']}"
    )
    lines.append("")

    lines.append("## Riskiest action types")
    if report["riskiest_actions"]:
        for row in report["riskiest_actions"]:
            lines.append(f"- {row['action_type']}: risk {row['risk']}")
    else:
        lines.append("_None recorded._")
    lines.append("")

    lines.append("## Riskiest modules")
    if report["riskiest_modules"]:
        for row in report["riskiest_modules"]:
            lines.append(f"- {row['module']}: risk {row['risk']}")
    else:
        lines.append("_None recorded._")
    lines.append("")

    lines.append("## Counterfactual avoid signatures")
    if report["avoid_signatures"]:
        for sig in report["avoid_signatures"]:
            lines.append(f"- {sig}")
    else:
        lines.append("_None — no signature clears the avoid threshold._")

    return "\n".join(lines).rstrip() + "\n"
