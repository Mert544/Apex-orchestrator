"""Self-assessment — Apex grades its OWN fixing, not the codebase's.

``proof_history.py`` reconstructs *what Apex can fix here* from the durable
proof artifacts: per action type (and per module) how many fixes ``applied`` vs
``rolled_back`` vs ``blocked``, and a bounded reliability ratio. That is an
outward-looking signal — which findings stick on this project.

This module turns the same evidence INWARD. It asks: where does Apex's own
fixing fail most? Which action families does it keep *trying* yet keep losing to
rollbacks or blocks? It ranks those weak spots, distils a concrete
*self-curriculum* (what to harden next), and measures whether Apex's stated
confidence — the verification it claims to have performed — actually matches the
fixes that landed (a calibration gap exposing over/under-confidence).

Everything is **pure and deterministic**: same proof history → same output, no
time, no randomness, no I/O. It consumes the loaded history (a ``list[dict]`` as
returned by ``proof_history.load_proof_history``) and only ever *reads* it.
Empty or missing history yields empty/neutral results and never raises. All
ratios are bounded to [0, 1]; all lists are bounded by the distinct keys present.
"""

from __future__ import annotations

from app.engine.proof_history import summarise_fix_track_record

# A weakness only matters once Apex has *tried* an action enough times for the
# ratio to mean something — a single rolled-back one-off is noise, not a weak
# spot. This floor keeps the ranking grounded in repeated, observed failure.
_MIN_ATTEMPTS = 2
# Reliability at/below this is "fragile" (it lands less than half the time);
# below it but with blocks dominating reads as "blocked" instead.
_FRAGILE_AT = 0.5
# Hard cap on emitted weaknesses so the list stays bounded regardless of how
# many distinct action types a long history accumulates.
_MAX_WEAKNESSES = 12
# The placeholder bucket proof_history uses for attribute-less fixes; excluded
# from the self-assessment so a curriculum never says "get better at <unknown>".
_UNKNOWN = "<unknown>"


def _verdict(reliability: float, attempts: int, blocked: int, lost: int) -> str:
    """A deterministic human label for one action's track record.

    ``blocked`` dominating the losses means preconditions are usually unmet (the
    fix never got to run); otherwise low reliability means it rolls back. At or
    above the fragile threshold the action is simply reliable."""
    if reliability >= _FRAGILE_AT:
        return "reliable"
    if lost > 0 and blocked * 2 >= lost:
        return "blocked — preconditions usually unmet"
    return "fragile — rolls back often"


def assess_weaknesses(history: list[dict]) -> list[dict]:
    """Rank the action types where Apex's own fixing is weakest, worst first.

    From the proof track record, keep action types Apex has attempted at least
    ``_MIN_ATTEMPTS`` times, then order them by a deterministic priority that
    puts *low reliability with high volume* on top — a frequently-tried,
    often-failing fix family is the most worth hardening. Each item is
    ``{"action", "reliability", "attempts", "lost", "verdict"}`` where ``lost``
    is rollbacks + blocks. The attribute-less bucket is excluded. Bounded to
    ``_MAX_WEAKNESSES`` items. Empty/missing history → ``[]``; never raises."""
    by_action = summarise_fix_track_record(history).get("by_action") or {}
    items: list[dict] = []
    for action, stats in by_action.items():
        if action == _UNKNOWN:
            continue
        attempts = int(stats["total"])
        if attempts < _MIN_ATTEMPTS:
            continue
        reliability = float(stats["reliability"])
        blocked = int(stats["blocked"])
        lost = int(stats["rolled_back"]) + blocked
        items.append({
            "action": action,
            "reliability": reliability,
            "attempts": attempts,
            "lost": lost,
            "verdict": _verdict(reliability, attempts, blocked, lost),
        })
    items.sort(key=_weakness_sort_key)
    return items[:_MAX_WEAKNESSES]


def _weakness_sort_key(item: dict) -> tuple:
    """Deterministic priority: lowest reliability first, then most-lost, then
    most-attempted, then action name. A pure total order over the items so the
    ranking is stable for identical input (no time/random)."""
    return (
        item["reliability"],
        -item["lost"],
        -item["attempts"],
        item["action"],
    )


def self_curriculum(history: list[dict], top: int = 3) -> list[str]:
    """The top-N concrete "Apex should get better at X" hardening directions.

    Derived straight from ``assess_weaknesses``: the worst action families
    become learning targets, phrased by their verdict so the direction names the
    *failure mode* (rolls back vs blocked) Apex must fix. ``top`` is clamped to
    [0, len(weaknesses)]; ``top <= 0`` or empty history → ``[]``; never raises."""
    if top <= 0:
        return []
    lines: list[str] = []
    for item in assess_weaknesses(history)[:top]:
        lines.append(_curriculum_line(item))
    return lines


def _curriculum_line(item: dict) -> str:
    """One curriculum direction for a weakness, keyed off its verdict so the
    phrasing matches the failure mode. Deterministic given the item."""
    action = item["action"]
    if item["verdict"].startswith("blocked"):
        return (
            f"Apex should get better at satisfying preconditions for '{action}' "
            f"(blocked {item['lost']}/{item['attempts']} attempts)"
        )
    return (
        f"Apex should get better at landing '{action}' without rollback "
        f"(reliability {item['reliability']:.2f} over {item['attempts']} attempts)"
    )


def _claimed_landed(history: list[dict]) -> int:
    """Count fixes where Apex CLAIMED soundness — it recorded a performed
    verification. That stated confidence is what calibration tests against the
    fixes that actually landed. Tolerant of missing/odd verification dicts."""
    claimed = 0
    for proof in history or []:
        for fix in proof.get("fixes") or []:
            if not isinstance(fix, dict):
                continue
            verification = fix.get("verification")
            if isinstance(verification, dict) and verification.get("performed"):
                claimed += 1
    return claimed


def confidence_calibration(history: list[dict]) -> dict:
    """Does Apex's stated confidence match what actually landed?

    Apex's *claimed* rate is the share of fixes for which it recorded a performed
    verification (it asserted the fix was sound); its *actual* rate is the share
    that truly landed (``applied``). The ``gap = claimed - actual``: positive is
    OVER-confidence (it vouched for more than stuck), negative is UNDER-confidence
    (it landed more than it vouched for), zero is calibrated. Returns
    ``{"claimed", "actual", "gap", "verdict", "fixes"}`` with bounded rates.
    Empty/missing history → a neutral all-zero "no evidence" reading; never raises."""
    totals = summarise_fix_track_record(history).get("totals") or {}
    fixes = int(totals.get("total", 0))
    if fixes <= 0:
        return {
            "claimed": 0.0,
            "actual": 0.0,
            "gap": 0.0,
            "verdict": "no evidence",
            "fixes": 0,
        }
    claimed = round(_claimed_landed(history) / fixes, 4)
    actual = float(totals.get("reliability", 0.0))
    gap = round(claimed - actual, 4)
    return {
        "claimed": claimed,
        "actual": actual,
        "gap": gap,
        "verdict": _calibration_verdict(gap),
        "fixes": fixes,
    }


def _calibration_verdict(gap: float) -> str:
    """A deterministic label for the calibration gap. A small band around zero is
    "well calibrated"; outside it, the sign names the direction of miscalibration."""
    if gap > 0.1:
        return "over-confident — claims more than lands"
    if gap < -0.1:
        return "under-confident — lands more than it claims"
    return "well calibrated"
