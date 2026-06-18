"""Effort/ROI enricher — reasons about the likely EFFORT to fix a module's
converging concerns and the PAYOFF of doing so, so a developer knows what they
are signing up for before they start.

Apex's confluence ideas note that several concerns converge on a module, but a
bare list ("hub, untested, deep-nesting") says nothing about whether addressing
them is a cheap afternoon or a week-long decoupling — nor whether the payoff is
worth it. This lens grounds each converging signal label on a small, explicit
(effort_weight, payoff_weight) basis, aggregates the present concerns into a
coarse effort band (small / moderate / large) and a payoff band (low / moderate
/ high), and emits a one-line clause naming ONLY the concerns that are present.

It is a pure function with the same contract as ``idea_reasoning._abductive``:
it returns ``(clause, [f"effort: {clause}"])`` when at least two labels are
mappable, else ``(None, None)`` so an un-reasoned idea stays byte-identical.
Deterministic: no time, no random, fixed basis and band thresholds.
"""

from __future__ import annotations

from typing import Any

# Explicit per-label basis. Each entry is (effort_weight, payoff_weight, kind),
# where ``kind`` is a short human phrase naming the SHAPE of the work, reused in
# the rationale. Weights are small integers on a fixed scale: effort 1=cheap,
# 2=moderate, 3=expensive; payoff 1=low, 2=moderate, 3=high. Several distinct
# labels legitimately share one basis (``hub``/``god-class`` are both expensive
# structural changes); the enricher de-duplicates identical ``kind`` phrases so a
# synonym pair does not name the same work twice. A label not listed here is
# simply skipped (it contributes no effort/payoff signal).
_EFFORT_BASIS: dict[str, tuple[int, int, str]] = {
    # cheap safety-net test, high payoff
    "untested": (1, 3, "a cheap safety-net test"),
    "critical-untested": (1, 3, "a cheap safety-net test"),
    "shallow-coverage": (1, 3, "a cheap safety-net test"),
    # expensive structural change, high payoff
    "hub": (3, 3, "a larger decoupling"),
    "dependency-hub": (3, 3, "a larger decoupling"),
    "symbol-hub": (3, 3, "a larger decoupling"),
    "god-class": (3, 3, "a larger decoupling"),
    "deep-nesting": (3, 3, "a larger decoupling"),
    "complexity-hotspot": (3, 3, "a larger decoupling"),
    # cheap tidy, low payoff
    "doc-drift": (1, 1, "a quick tidy"),
    "unused-import": (1, 1, "a quick tidy"),
    "modernization": (1, 1, "a quick tidy"),
    "modernization-imports": (1, 1, "a quick tidy"),
    # moderate fix, high payoff
    "eval": (2, 3, "a moderate hardening"),
    "security-eval": (2, 3, "a moderate hardening"),
    "security-finding": (2, 3, "a moderate hardening"),
    "base-exception": (2, 3, "a moderate hardening"),
    "sensitive-path": (2, 3, "a moderate hardening"),
}

# Coarse band labels keyed by an aggregate score. Effort bands read the WORST
# (largest) present effort weight — the most expensive concern dominates what you
# sign up for. Payoff bands read the BEST (largest) present payoff weight — the
# highest-value concern is the headline reason to act. Index 0 is unused so a
# weight maps directly to its band name.
_EFFORT_BANDS = ("", "a small change", "a moderate change", "a large change")
_PAYOFF_BANDS = ("", "low payoff", "moderate payoff", "high payoff")


def _present_kinds(seq: list[str]) -> list[str]:
    """De-duplicated work-shape phrases for the mappable labels, in label order.

    Several labels can share one ``kind`` (``hub``/``symbol-hub`` are both
    ``a larger decoupling``); each distinct phrase is listed once.
    """
    kinds: list[str] = []
    for label in seq:
        entry = _EFFORT_BASIS.get(label)
        if entry is not None and entry[2] not in kinds:
            kinds.append(entry[2])
    return kinds


def _aggregate(seq: list[str]) -> tuple[int, int, int]:
    """Aggregate the mappable labels into (worst_effort, best_payoff, count).

    ``worst_effort`` is the maximum effort weight present (the most expensive
    concern dominates), ``best_payoff`` the maximum payoff weight present (the
    most valuable concern is the headline), and ``count`` the number of mappable
    labels (used for the ``< 2`` byte-identical guard).
    """
    worst_effort = 0
    best_payoff = 0
    count = 0
    for label in seq:
        entry = _EFFORT_BASIS.get(label)
        if entry is None:
            continue
        count += 1
        worst_effort = max(worst_effort, entry[0])
        best_payoff = max(best_payoff, entry[1])
    return worst_effort, best_payoff, count


def effort_enrichment(labels: object) -> "tuple[str | None, list[str] | None]":
    """Reason about the EFFORT to fix and the PAYOFF of the converging concerns.

    Maps each converging signal label to an explicit (effort, payoff) basis,
    aggregates the present concerns into a coarse effort band (small / moderate /
    large) and payoff band (low / moderate / high), and returns a one-line
    ``effort: ...`` clause naming only the concerns present, plus a single
    ``[f"effort: {clause}"]`` fact. Returns ``(None, None)`` when fewer than two
    labels are mappable (an un-reasoned idea stays byte-identical). Deterministic.
    """
    seq: list[str] = [str(label) for label in (labels or []) if label is not None]
    worst_effort, best_payoff, count = _aggregate(seq)
    if count < 2:
        return None, None
    effort_band = _EFFORT_BANDS[worst_effort]
    payoff_band = _PAYOFF_BANDS[best_payoff]
    kinds = _present_kinds(seq)
    clause = (
        f"effort: {effort_band} for {payoff_band} — "
        + ", then ".join(kinds)
    )
    return clause, [f"effort: {clause}"]


# Re-export for callers that prefer an explicit type alias on the seam.
_Labels = Any
