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
* **Reliability signal** (weight ``_W_RELIABILITY``): the per-action
  ``learned_reliability`` score ``r`` in ``[0, 1]`` (share of that action's
  outcomes that landed). Higher reliability → lower risk, contributing
  ``(1 - r)``. Absent action → this signal abstains (contributes the baseline
  ``0.5``) so an unseen action is not punished.
* **Track-record signal** (weight ``_W_TRACK``): the same landing ratio
  read at the (action, module) granularity from ``summarise_fix_track_record``;
  it backs the reliability view with module-specific evidence and likewise
  contributes ``(1 - ratio)``, abstaining (``0.5``) when neither the action nor
  the module has a record.
* **Counterfactual signal** (weight ``_W_AVOID``): if
  ``should_avoid(failure_signatures(history), action_type, module_traits(module))``
  fires, this signal contributes ``1.0`` (a strong, evidence-backed risk bump);
  otherwise it contributes the baseline ``0.5`` (abstain — "no avoid lesson").
* **Native-experience signal** (weight ``_W_EXPERIENCE``): a 4th, newest sense
  organ — :func:`app.engine.native_proof_memory.decayed_reliability` reports,
  per learned idiom SHAPE (not per action/module), how reliably the native
  synthesis lane's transplants have actually stuck here. This module reduces
  that shape-keyed map to one project-level "native landing confidence" (the
  mean decayed score across every learned shape) and treats it exactly like
  the reliability signal it is: high confidence → lower risk, contributing
  ``(1 - confidence)``. It is gated to the action types where the native lane
  is actually the synthesis mechanism (currently ``implement_stub`` /
  ``implement-stub`` — see ``_is_native_action``); every other action type
  abstains at the baseline so this signal never distorts maintain-path risk
  for actions the native lane has no say in.

The active signals are averaged with weights that sum to ``1.0`` and the
result is clamped to ``[0, 1]`` and rounded to ``_PRECISION`` places. With an
empty/missing history every signal abstains, so the score is exactly the
baseline ``0.5``.

**Byte-identical guarantee.** The experience signal only ever joins the
average when there is real evidence to use it: the action type is
native-relevant AND ``decayed_reliability`` returns a non-empty map. In every
other case (no native experience recorded yet, or an action type the native
lane doesn't drive) the fusion falls back to the historical 3-signal weights
(``_W_RELIABILITY_NO_EXPERIENCE`` / ``_W_TRACK_NO_EXPERIENCE`` /
``_W_AVOID_NO_EXPERIENCE`` — the exact ``0.45`` / ``0.25`` / ``0.30`` this
module used before the 4th signal existed). So the experience weight
"redistributes to the identity" when it has nothing to say: ``fix_risk``
returns the SAME number it always did for a project with no recorded native
experience, for every action type and module, with no exceptions.

Everything is **best-effort at the I/O edge**: a missing ``.apex`` dir,
unreadable proofs/experience store, or malformed rows are tolerated by the
underlying loaders, so this module never raises — the worst case is the
neutral baseline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engine.counterfactual_learning import (
    failure_signatures,
    module_traits,
    should_avoid,
)
from app.engine.native_proof_memory import decayed_reliability
from app.engine.proof_history import (
    _DECAY as _PROOF_DECAY,
    _iter_fixes,
    _module_of,
    _outcome_of,
    learned_reliability,
    learned_reliability_decayed,
    load_proof_history,
    summarise_fix_track_record,
)

# The score with no evidence: neither safe nor risky.
_BASELINE = 0.5

# Signal weights used when the native-experience signal is ACTIVE (real
# evidence exists — see `_experience_risk`). Reliability stays clearly
# dominant; the new signal gets the smallest say since it is a single
# project-level number, not a granular (action, module) fact. Sum to 1.0.
_W_RELIABILITY = 0.40
_W_TRACK = 0.22
_W_AVOID = 0.26
_W_EXPERIENCE = 0.12

# The historical (pre-experience) weights — used whenever the experience
# signal abstains (no evidence, or an action type the native lane doesn't
# drive). This is the exact 3-weight split this module used before the 4th
# signal existed, so falling back to it is byte-identical to the old score.
# Also sum to 1.0.
_W_RELIABILITY_NO_EXPERIENCE = 0.45
_W_TRACK_NO_EXPERIENCE = 0.25
_W_AVOID_NO_EXPERIENCE = 0.30

# Action types the native synthesis lane actually drives (see
# `app.execution.objectives.implement_stub`, which is the only objective that
# reads `native_proof_memory`/`native_synth` candidates). Normalized against
# hyphens so both the objective-name spelling (`implement-stub`) and the
# action-type spelling (`implement_stub`) match — see `_is_native_action`.
_NATIVE_ACTIONS = frozenset({"implement_stub"})

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


def _track_risk(
    summary: dict,
    action_type: str,
    module: str,
    decayed: dict[str, float] | None = None,
) -> float:
    """Risk from the (action, module) track record, in ``[0, 1]``.

    When a non-empty ``decayed`` module-fragility map is supplied (the
    ``recency=True`` opt-in — see :func:`_module_fragility_decayed`) AND it
    has an entry for ``module``, that RANK-DECAYED risk ratio is used
    directly (it is already risk-shaped, so no ``1 - ratio`` flip). Otherwise
    falls back to the historical equal-weight path: prefers a module-specific
    landing ratio when the proof history has acted on that module before,
    else the action's ratio, else abstains at the baseline. ``decayed=None``
    (the default) is byte-identical to the pre-recency behaviour."""
    if decayed and module in decayed:
        return _clamp(decayed[module])
    by_module = summary.get("by_module") or {}
    by_action = summary.get("by_action") or {}
    entry = by_module.get(module)
    if not isinstance(entry, dict) or not entry.get("total"):
        entry = by_action.get(action_type)
    if not isinstance(entry, dict) or not entry.get("total"):
        return _BASELINE
    ratio = float(entry.get("reliability") or 0.0)
    return _clamp(1.0 - ratio)


def _module_fragility_decayed(history: list[dict]) -> dict[str, float]:
    """Recency-weighted MODULE fragility — generational forgetting for the
    track-record signal, in ``[0, 1]`` per module.

    Mirrors :func:`app.engine.proof_history.learned_reliability_decayed`
    (same rank-based ``_PROOF_DECAY ** (n-1-i)`` weighting, the SAME
    ``0.85`` constant, read read-only from ``proof_history``) but keyed by
    MODULE (:func:`app.engine.proof_history._module_of`) instead of action,
    and shaped as a RISK ratio (``not_applied / total``) rather than a
    reliability ratio, so it plugs directly into :func:`_track_risk`'s scale
    without a ``1 - ratio`` flip.

    Proofs are ordered oldest→newest by the loader's existing deterministic
    key; generation ``i`` (``0`` = oldest of ``n``) gets weight
    ``_PROOF_DECAY ** (n-1-i)``, so the newest generation weighs ``1.0`` and
    older ones decay geometrically. A module that used to roll back often but
    has landed cleanly in the most recent generations is no longer punished
    forever by ancient failures — the same "çağ atlatma" leap
    ``learned_reliability_decayed`` gives actions.

    Pure rank arithmetic — no wall-clock, no randomness, so identical proof
    content yields an identical mapping. Empty/missing history → ``{}``;
    never raises (mirrors every other reducer in this module)."""
    proofs = history or []
    n = len(proofs)
    not_applied: dict[str, float] = {}
    total: dict[str, float] = {}
    for i, proof in enumerate(proofs):
        weight = _PROOF_DECAY ** (n - 1 - i)
        for fix in _iter_fixes([proof]):
            module = _module_of(fix)
            total[module] = total.get(module, 0.0) + weight
            if _outcome_of(fix) != "applied":
                not_applied[module] = not_applied.get(module, 0.0) + weight
    return {
        module: round(not_applied.get(module, 0.0) / total[module], _PRECISION)
        for module in sorted(total)
        if total[module] > 0
    }


def _avoid_risk(signatures: dict[str, dict[str, Any]], action_type: str, module: str) -> float:
    """Risk from the counterfactual avoid-guard: ``1.0`` if it fires else baseline."""
    if should_avoid(signatures, action_type, module_traits(module)):
        return 1.0
    return _BASELINE


def _is_native_action(action_type: str) -> bool:
    """True for action types where the native lane is the actual synthesis
    mechanism, so its landing confidence is relevant evidence for THIS fix.

    Accepts both the underscored action-type spelling (``implement_stub``,
    used by ``idea_action_bridge`` steps) and the hyphenated objective-name
    spelling (``implement-stub``, used by the develop-loop's ``Move.operator``)
    by normalizing hyphens to underscores before the membership check."""
    return action_type.replace("-", "_") in _NATIVE_ACTIONS


def _native_confidence(root: str | Path) -> float | None:
    """Project-level native-lane landing confidence, or ``None`` when there is
    no native experience to read at all (missing store, zero recorded
    landings, or any loader failure — this never raises).

    Reduces the shape-keyed :func:`decayed_reliability` map to one number: the
    mean decayed score across every learned shape, clamped to ``[0, 1]`` (a
    shape landed across many generations can sum past ``1.0`` before the
    clamp). This mirrors how the other signals collapse a whole history into
    a single per-fix contribution."""
    try:
        scores = decayed_reliability(root)
    except Exception:
        return None
    if not scores:
        return None
    return _clamp(sum(scores.values()) / len(scores))


def _experience_risk(root: str | Path, action_type: str) -> tuple[float, bool]:
    """Risk from the native lane's proven landing confidence, in ``[0, 1]``,
    plus whether the signal is ACTIVE (real evidence exists for an action type
    the native lane actually drives).

    Gated to :func:`_is_native_action`; every other action type abstains at
    the baseline WITHOUT even reading the experience store, so native
    experience never moves risk for an unrelated action. When active, higher
    confidence means lower risk, contributing ``(1 - confidence)`` — the same
    shape as the reliability signal it complements. Inactive → baseline, and
    the caller falls back to the pre-experience weights (see ``_score``)."""
    if not _is_native_action(action_type):
        return _BASELINE, False
    confidence = _native_confidence(root)
    if confidence is None:
        return _BASELINE, False
    return _clamp(1.0 - confidence), True


def _score(
    reliabilities: dict[str, float],
    summary: dict,
    signatures: dict[str, dict[str, Any]],
    action_type: str,
    module: str,
    root: str | Path = ".",
    decayed_fragility: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Fuse the signals for one (action, module) into a scored evidence dict.

    Returns the rounded ``risk`` plus the rounded per-signal contributions and a
    sorted ``evidence`` list naming which signals carried real evidence (i.e.
    departed from the neutral baseline). The native-experience signal joins the
    average (at ``_W_*`` weights) only when it is ACTIVE; otherwise the fusion
    uses the historical ``_W_*_NO_EXPERIENCE`` weights, which is exactly the
    3-signal formula this module used before the 4th signal existed — so an
    inactive experience signal is byte-identical to the old score.

    ``decayed_fragility`` (default ``None``) is threaded straight into
    :func:`_track_risk` — see that function for how it swaps in the
    rank-decayed module-fragility ratio. ``None`` (or an empty map) keeps the
    track signal byte-identical to the pre-recency behaviour."""
    reliability = _reliability_risk(reliabilities, action_type)
    track = _track_risk(summary, action_type, module, decayed_fragility)
    avoid = _avoid_risk(signatures, action_type, module)
    experience, active = _experience_risk(root, action_type)
    if active:
        raw = (
            _W_RELIABILITY * reliability
            + _W_TRACK * track
            + _W_AVOID * avoid
            + _W_EXPERIENCE * experience
        )
    else:
        raw = (
            _W_RELIABILITY_NO_EXPERIENCE * reliability
            + _W_TRACK_NO_EXPERIENCE * track
            + _W_AVOID_NO_EXPERIENCE * avoid
        )
    risk = round(_clamp(raw), _PRECISION)
    evidence: list[str] = []
    if reliability != _BASELINE:
        evidence.append("reliability")
    if track != _BASELINE:
        evidence.append("track_record")
    if avoid >= 1.0:
        evidence.append("counterfactual_avoid")
    if active and experience != _BASELINE:
        evidence.append("native_experience")
    return {
        "action_type": action_type,
        "module": module,
        "risk": risk,
        "reliability_risk": round(reliability, _PRECISION),
        "track_risk": round(track, _PRECISION),
        "avoid_risk": round(avoid, _PRECISION),
        "experience_risk": round(experience, _PRECISION) if active else None,
        "evidence": sorted(evidence),
    }


def fix_risk(
    root: str | Path, action_type: str, module: str, recency: bool = False
) -> float:
    """Forward-looking rollback risk for a proposed fix, in ``[0.0, 1.0]``.

    ``0`` = the proof history says this kind of fix lands cleanly here; ``1`` =
    it predictably rolls back. Fuses the per-action ``learned_reliability``, the
    (action, module) track record, the counterfactual avoid-guard, and (for
    native-relevant action types with recorded native landings) the native
    lane's landing confidence, as documented in the module docstring.
    Empty/missing history → the neutral baseline ``0.5``. Pure and
    deterministic; never raises.

    ``recency`` is an OPT-IN switch (default ``False``) that swaps the flat
    lifetime reliability signal for the rank-decayed
    :func:`learned_reliability_decayed`, AND swaps the flat module track-record
    ratio for the rank-decayed :func:`_module_fragility_decayed`, so a fix
    family (and a module) that stopped rolling back several runs ago is no
    longer dragged down by ancient failures. When ``False`` the score is
    byte-identical to the historical behaviour; the other signals (avoid-guard,
    native experience) are unchanged in both modes. With an empty proof
    history ``recency=True`` and ``recency=False`` score identically (both
    signals abstain to the neutral baseline)."""
    reliabilities, summary, signatures, decayed_fragility = _signal_inputs(
        root, recency)
    return _score(
        reliabilities, summary, signatures, str(action_type), str(module), root,
        decayed_fragility,
    )["risk"]


def _signal_inputs(
    root: str | Path, recency: bool
) -> tuple[dict, dict, dict, dict[str, float] | None]:
    """The fused-signal inputs, loaded ONCE from the proof history —
    ``(reliabilities, summary, signatures, decayed_fragility)`` — shared by
    :func:`fix_risk`, :func:`rank_fix_risks` and :func:`explain_fix_risk` so
    the recency-switch semantics live in exactly one place. ``recency`` swaps
    in the rank-decayed variants as :func:`fix_risk` documents;
    ``decayed_fragility`` is ``None`` when recency is off."""
    history = load_proof_history(root)
    reliabilities = (
        learned_reliability_decayed(history)
        if recency
        else learned_reliability(history)
    )
    summary = summarise_fix_track_record(history)
    signatures = failure_signatures(history)
    decayed_fragility = _module_fragility_decayed(history) if recency else None
    return reliabilities, summary, signatures, decayed_fragility


def rank_fix_risks(
    root: str | Path, candidates: list[tuple[str, str]], recency: bool = False
) -> list[dict]:
    """Score each ``(action_type, module)`` candidate and rank riskiest first.

    Returns one evidence dict per candidate (see :func:`_score`), sorted
    deterministically by descending ``risk`` then by the ``(action_type,
    module)`` key so ties are stable. The proof history is read ONCE and reused
    across candidates. ``recency`` is the same OPT-IN decay switch
    :func:`fix_risk` documents (default ``False`` — byte-identical to the
    historical behaviour); an empty candidate list → ``[]``; never raises."""
    reliabilities, summary, signatures, decayed_fragility = _signal_inputs(
        root, recency)
    scored = [
        _score(
            reliabilities, summary, signatures, str(action), str(module), root,
            decayed_fragility,
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


# --------------------------------------------------------------------------- #
# explain_fix_risk — a deterministic, human-readable per-signal breakdown of
# ONE (action, module) score, so a reviewer can see WHY a fix was flagged
# risky instead of just the final number. Read-only: it calls the exact same
# `_score` fusion `fix_risk`/`rank_fix_risks` use, so the breakdown can never
# drift from the returned score (never-fake-green discipline applies to
# explanations too).
# --------------------------------------------------------------------------- #

# Fixed emission order for the per-signal breakdown — matches the `evidence`
# names `_score` already emits, so `active` is a direct membership check.
_SIGNAL_ORDER = ("reliability", "track_record", "counterfactual_avoid", "native_experience")


def _explain_weights(active_experience: bool) -> dict[str, float]:
    """The ACTUAL weight each signal carries in the fusion `_score` just ran.

    Mirrors the same active/inactive weight-set choice `_score` makes: when
    the experience signal is active the 4-weight (`_W_*`) set applies; when it
    is not, the 3-weight (`_W_*_NO_EXPERIENCE`) set applies and the experience
    signal's weight is exactly ``0.0`` (it plays no part in the sum)."""
    if active_experience:
        return {
            "reliability": _W_RELIABILITY,
            "track_record": _W_TRACK,
            "counterfactual_avoid": _W_AVOID,
            "native_experience": _W_EXPERIENCE,
        }
    return {
        "reliability": _W_RELIABILITY_NO_EXPERIENCE,
        "track_record": _W_TRACK_NO_EXPERIENCE,
        "counterfactual_avoid": _W_AVOID_NO_EXPERIENCE,
        "native_experience": 0.0,
    }


def _explain_values(scored: dict[str, Any], active_experience: bool) -> dict[str, float]:
    """The already-rounded per-signal risk values `_score` computed, keyed to
    match `_SIGNAL_ORDER`. An inactive experience signal reads as the neutral
    baseline (it never joined the fusion, so it has nothing else to report)."""
    return {
        "reliability": scored["reliability_risk"],
        "track_record": scored["track_risk"],
        "counterfactual_avoid": scored["avoid_risk"],
        "native_experience": scored["experience_risk"] if active_experience else _BASELINE,
    }


def _explain_formula(weights: dict[str, float]) -> str:
    """A human-readable ``risk = w1×signal1 + w2×signal2 + ...`` string,
    omitting any signal whose weight is ``0.0`` (it did not join the sum)."""
    terms = [f"{weights[name]}×{name}" for name in _SIGNAL_ORDER if weights[name] > 0]
    return "risk = " + " + ".join(terms)


def explain_fix_risk(
    action: str, module: str, root: str | Path = ".", recency: bool = True
) -> dict:
    """Deterministic, human-readable per-signal breakdown of ONE fix-risk score.

    Runs the EXACT same fusion :func:`fix_risk` uses (via :func:`_score`), so
    the breakdown can never diverge from the number a caller would get from
    ``fix_risk(root, action, module, recency=recency)`` — this function does
    not reimplement the arithmetic, it only shapes it for display.

    Returns a dict with the resolved ``action_type``/``module``, the total
    ``fixes`` recorded in the history (``0`` → an honest-empty caller can
    render "no history"), the fused ``risk``, a human ``formula`` string, and
    a ``signals`` list — one entry per :data:`_SIGNAL_ORDER` name, each with
    its ``decayed_value`` (the same rounded per-signal risk :func:`_score`
    returns), the ``weight`` actually applied in the fusion (``0.0`` for an
    inactive experience signal), the ``contribution`` (``weight × value``,
    rounded to :data:`_PRECISION`), and whether the signal is ``active``
    (carried real evidence away from the neutral baseline — the SAME test
    ``_score``'s ``evidence`` list already applies). Because every entry's
    weight is the one truly used in the fusion, summing every entry's
    ``contribution`` reconstructs the returned ``risk`` (within the rounding
    tolerance of independently-rounded per-signal values).

    ``recency`` defaults to ``True`` here (unlike :func:`fix_risk`'s
    ``False``) because an explanation is read on demand, not cached, and the
    recency-aware view is the more informative default for a human reviewing
    one candidate; pass ``recency=False`` to explain the flat-weight score
    instead. Best-effort: every loader beneath this is fail-safe, so a
    missing or corrupt store degrades to the neutral baseline and never
    raises."""
    action_type = str(action)
    module_name = str(module)
    reliabilities, summary, signatures, decayed_fragility = _signal_inputs(
        root, recency)
    scored = _score(
        reliabilities, summary, signatures, action_type, module_name, root,
        decayed_fragility,
    )
    active_experience = scored["experience_risk"] is not None
    weights = _explain_weights(active_experience)
    values = _explain_values(scored, active_experience)
    evidence = set(scored["evidence"])
    signals = [
        {
            "name": name,
            "decayed_value": round(values[name], _PRECISION),
            "weight": weights[name],
            "contribution": round(weights[name] * values[name], _PRECISION),
            "active": name in evidence,
        }
        for name in _SIGNAL_ORDER
    ]
    return {
        "action_type": action_type,
        "module": module_name,
        "signals": signals,
        "risk": scored["risk"],
        "fixes": summary.get("fixes", 0),
        "formula": _explain_formula(weights),
    }


def render_fix_risk_explanation(
    action: str, module: str, root: str | Path = "."
) -> str:
    """Pure Markdown formatter over :func:`explain_fix_risk` (``recency=True``).

    Deterministic: fixed section order, fixed precision, no time/random. With
    no proof history at all (``fixes == 0``) renders an explicit honest-empty
    notice instead of a table of signals that all abstain. Never raises."""
    info = explain_fix_risk(action, module, root)
    header = f"# Fix-Risk Explanation — {info['action_type']} / {info['module']}"
    # The mode is DISCLOSED because it differs from the aggregate report's
    # default: `apex fix-risk` (render_fix_risk_markdown) scores in the flat
    # lifetime mode, so the same (action, module) can legitimately carry a
    # different number there — an explanation that silently explained a
    # different score than the report shows would be its own honesty bug.
    lines: list[str] = [
        header, "",
        "Mode: recency-decayed (the aggregate `apex fix-risk` report uses "
        "the flat lifetime mode — the two can legitimately differ).",
        "", f"Risk: {info['risk']}",
    ]
    if not info["fixes"]:
        lines.append("")
        lines.append(
            "_No proof history — every signal abstains at the neutral baseline._"
        )
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append("| Signal | Active | Decayed value | Weight | Contribution |")
    lines.append("|---|---|---|---|---|")
    for sig in info["signals"]:
        active = "yes" if sig["active"] else "no"
        lines.append(
            f"| {sig['name']} | {active} | {sig['decayed_value']} | "
            f"{sig['weight']} | {sig['contribution']} |"
        )
    lines.append("")
    lines.append(f"Formula: {info['formula']}")
    return "\n".join(lines) + "\n"
