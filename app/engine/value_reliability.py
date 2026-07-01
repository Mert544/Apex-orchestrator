"""Value-realized reranker — correct the static move-value prior with PROVEN
realized outcomes, per operator, WITHOUT ever inflating off unverified work.

``move_value`` is a frozen buyer-value *prior*: it says how much a buyer WOULD
value a class of change. This module reads the durable proof-of-fix history (the
SAME ``.apex/proof-of-fix.json`` trail ``proof_history``/``value_landed`` consume)
and asks the honest follow-up: *of the value an operator PROMISED on this repo,
how much did it actually REALIZE — landed-and-held AND verified?* The answer is a
per-operator VALUE-REALIZATION factor that ``scored_move_value`` folds in as a
subordinate, neutral-default tiebreak multiplier.

**Sound by construction — demote-only, never inflates off unverified work.** The
fold reuses ``value_landed``'s never-fake-green bucketer verbatim:

  * ``value_landed._held`` counts a move ONLY if it was ``applied`` AND NOT rolled
    back — so a rolled-back / blocked / declined "win" contributes ZERO to both the
    realized numerator AND the predicted denominator: it is invisible here.
  * of the HELD moves, only the ``verified`` coverage bucket (a test exercises the
    change) credits the numerator; a ``weak`` (green-but-uncovered) or
    ``unverified`` (baseline-red / no-suite) landing credits the DENOMINATOR only.

So the realization RATE is ``verified-held / total-held`` ∈ [0, 1]: it is **at
most 1.0** (every held move verified), reached only when the operator fully
realized its promise. The factor is that rate — Wilson-lower-bounded on the held
sample count (proven beats lucky), then clamped to a BOUNDED band
``[_REALIZATION_FLOOR, 1.0]``. The ``1.0`` ceiling is the whole point: an operator
that reliably realizes stays NEUTRAL (never boosted above its prior), while one
that over-promised — high predicted value, low verified realization — is DEMOTED
toward the floor. **The factor can only DEMOTE an over-promiser; it can never
inflate selection off unverified work.**

**Neutral 1.0 on a fresh repo.** With no proof history (or fewer than
``_MIN_SAMPLES`` held moves for an operator) an operator is simply absent from the
returned map, and :func:`realization_factor` returns ``1.0`` — so
``scored_move_value`` is byte-identical to the pre-change static-table behaviour.
Opt-in by construction: the multiplier is neutral until PROVEN evidence exists.

Recency: proofs are ordered oldest→newest by ``proof_history``'s existing
deterministic key and each generation is weighted ``_DECAY ** (n-1-i)`` (the SAME
``_DECAY = 0.85`` recency ``learned_reliability_decayed`` uses), so a fix family
that stopped under-realizing several runs ago can climb back toward neutral. The
Wilson interval's width still uses the TRUE held sample count, so recency shapes
the rate without faking away thin evidence.

Everything is pure and deterministic: same proof content → same factors (no
clock, no random, no hash-order). Stdlib ``math`` only; no LLM. It reuses
``value_landed``'s bucketer and ``proof_history``'s loader/decay so the value view
can never disagree with the evidence — or with the metric that scores it.
"""

from __future__ import annotations

import math
from pathlib import Path

from app.engine.proof_history import _DECAY, load_proof_history
from app.engine.value_landed import (
    _VERIFIED_LEVELS,
    _coverage_level,
    _held,
)

__all__ = [
    "operator_realization_factors",
    "realization_factor",
    "REALIZATION_SCHEMA",
]

REALIZATION_SCHEMA = "apex-value-realized"

# z-score for the Wilson score interval lower bound — the SAME 1.96 (≈95% normal
# quantile) ``idea_memory._WILSON_Z`` uses, so "proven beats lucky" reads
# identically here: a thin-but-perfect 2-of-2 cannot outrank a well-attested
# 9-of-10. Fixed constant (no scipy/statistics), so the bound is deterministic.
_WILSON_Z = 1.96

# Don't move on an operator until it has at least this many HELD moves — mirrors
# ``idea_memory._MIN_SAMPLES`` / the ``land_factors`` sample gate. Below it an
# operator is absent from the map (neutral 1.0), so a lone under-realizing fluke
# can never demote an operator.
_MIN_SAMPLES = 2

# Bounded band floor — the strongest DEMOTION the factor may apply, mirroring
# ``ascend._RELIABILITY_FLOOR``: a chronic over-promiser is heavily damped toward
# this, never erased to zero (which would starve the operator). The band CEILING
# is a hard 1.0 (neutral): the factor never inflates an operator above its prior.
_REALIZATION_FLOOR = 0.15


def _wilson_lower_bound(phat: float, n: float) -> float:
    """Wilson score interval lower bound for rate ``phat`` over ``n`` samples.

    The SAME arithmetic as ``idea_memory._Stat.confidence`` (stdlib ``math``
    only), factored out so this leaf need not build a ``_Stat``: it shrinks toward
    0 as ``n`` shrinks, so accumulated evidence is rewarded and a lucky small
    sample is discounted. Safe on zero samples (returns 0.0). Deterministic."""
    if n <= 0:
        return 0.0
    z = _WILSON_Z
    denom = 1.0 + z * z / n
    center = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return (center - margin) / denom


def _held_rows(history: list[dict]) -> list[tuple[str, bool, float]]:
    """Fold the proof history into ``(operator, verified, weight)`` rows for the
    HELD moves only — reusing ``value_landed``'s never-fake-green ``_held`` gate
    and coverage bucketer verbatim, so a rolled-back/blocked move is invisible.

    Each row's ``weight`` is the recency decay of its proof generation:
    ``_DECAY ** (n-1-i)`` with ``i`` the proof's oldest→newest rank (the ordering
    ``load_proof_history`` already fixes), so the newest generation weighs 1.0.
    ``verified`` is True only for the ``value_landed`` verified coverage levels."""
    proofs = history or []
    n = len(proofs)
    rows: list[tuple[str, bool, float]] = []
    for i, proof in enumerate(proofs):
        weight = _DECAY ** (n - 1 - i)
        for rec in proof.get("fixes") or []:
            if not isinstance(rec, dict) or not _held(rec):
                continue
            finding = rec.get("finding") or {}
            operator = finding.get("operator") or ""
            if not operator:
                continue
            verified = _coverage_level(rec) in _VERIFIED_LEVELS
            rows.append((operator, verified, weight))
    return rows


def operator_realization_factors(project_root: str | Path) -> dict[str, float]:
    """Per-operator VALUE-REALIZATION factor from the proof-of-fix history.

    Reads the durable proof trail under ``<project_root>/.apex/`` (the SAME store
    ``value_landed`` / ``proof_history`` read), folds it through
    ``value_landed``'s never-fake-green ``_held`` gate + coverage bucketer, and for
    each operator computes the recency-weighted realized-verified / predicted rate
    — i.e. the fraction of HELD value that was actually VERIFIED. That rate is
    Wilson-lower-bounded on the TRUE held sample count, then clamped to the bounded
    band ``[_REALIZATION_FLOOR, 1.0]``.

    Because the rate is ``verified-held / total-held`` it is at most 1.0, so the
    factor NEVER exceeds 1.0: an operator that fully realizes its promise stays
    neutral, and one that over-promised (held moves that landed weak/unverified) is
    DEMOTED — demote-only by construction. A rolled-back move is invisible (``_held``
    excludes it), so the factor can never inflate selection off unverified work.

    An operator with fewer than ``_MIN_SAMPLES`` held moves is OMITTED (so its
    factor stays a neutral 1.0). Empty / missing history → ``{}`` (every operator
    neutral). Pure and deterministic: no clock, no random, no hash-order; never
    raises (a missing dir / malformed proof is skipped by the loader)."""
    history = load_proof_history(project_root)
    predicted: dict[str, float] = {}
    realized: dict[str, float] = {}
    samples: dict[str, int] = {}
    for operator, verified, weight in _held_rows(history):
        predicted[operator] = predicted.get(operator, 0.0) + weight
        samples[operator] = samples.get(operator, 0) + 1
        if verified:
            realized[operator] = realized.get(operator, 0.0) + weight
    factors: dict[str, float] = {}
    for operator in sorted(predicted):
        n = samples[operator]
        if n < _MIN_SAMPLES:
            continue
        denom = predicted[operator]
        rate = realized.get(operator, 0.0) / denom if denom > 0 else 0.0
        bound = _wilson_lower_bound(rate, n)
        factors[operator] = round(min(1.0, max(_REALIZATION_FLOOR, bound)), 4)
    return factors


def realization_factor(operator: str,
                       factors: dict[str, float] | None) -> float:
    """The bounded, demote-only realization multiplier for one operator.

    Looks ``operator`` up in a precomputed ``factors`` map
    (:func:`operator_realization_factors`). Returns a NEUTRAL ``1.0`` when there is
    no map (a fresh repo / no proofs) or the operator is untracked (too few held
    moves) — so ``scored_move_value`` is byte-identical to the static table until
    PROVEN evidence exists. A tracked operator's factor is in
    ``[_REALIZATION_FLOOR, 1.0]``: at most neutral, at worst damped — never an
    inflation. Pure lookup; deterministic."""
    if not factors or not operator:
        return 1.0
    return factors.get(operator, 1.0)
