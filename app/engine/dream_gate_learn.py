"""Dream gate learning — TIGHTEN-ONLY feedback for the dream promote gate.

``dream.py``'s promote gate (``PROMOTE_STREAK`` = 3 consecutive dreams,
``PROMOTE_CONFIDENCE`` = 0.80) decides when a discovered confluence graduates
from "the organism noticed a pattern" into "a saved work order the waking
engine will act on" (:func:`app.engine.dream._promote`). Those two constants
are frozen priors — they say nothing about whether THIS project's graduated
confluences actually turned into landed, verified fixes. This module reads the
durable evidence and asks the honest follow-up: *of the confluences the dream
has promoted here, how many were later actually FIXED — held-and-verified?*
The answer feeds back as a per-key gate-TIGHTENING factor.

**Sound by construction — tighten-only, mirrors ``value_reliability.py``'s
demote-only discipline exactly, applied to a GATE instead of a SCORE.** The
same never-fake-green fold is reused: a promoted confluence's module is
cross-referenced against the durable proof-of-fix trail
(``.apex/proof-of-fix.json``, read via ``proof_history.load_proof_history``)
and credited ``realized=True`` only when a fix on that module was ``applied``
AND NOT rolled back (:func:`app.engine.value_landed._held`) AND a test
exercises it (:func:`app.engine.value_landed._coverage_level` in
``_VERIFIED_LEVELS``). A promoted confluence that never landed a held+verified
fix, or landed one that was rolled back, contributes ``realized=False`` — never
invisible, never a false positive.

The realized RATE (``realized / promoted``) is therefore ``in [0, 1]`` by
construction, Wilson-lower-bounded on the promoted sample count (the SAME
``_WILSON_Z = 1.96`` interval — proven beats lucky: a thin 1-of-1 win cannot
out-tighten a well-attested 8-of-10), then clamped to
``[_GATE_FACTOR_FLOOR, 1.0]``. Below ``_MIN_SAMPLES`` promoted confluences for a
key, that key is simply ABSENT from the returned map — a fresh project or a
project with too little promotion history is byte-identical to today (no
factor, gate reads the static constants).

``effective_promote_gate`` folds a factor into the two gate constants
MONOTONE-TIGHTEN-ONLY: ``effective_streak >= PROMOTE_STREAK`` and
``effective_confidence >= PROMOTE_CONFIDENCE`` ALWAYS hold, and a
neutral/absent factor (``1.0``) reproduces the static constants EXACTLY
(byte-identical). **The soundness argument, restated for the gate:** a buggy or
adversarial factor computation can at worst make the gate MORE conservative —
a confluence that would have graduated now needs one more dream or a slightly
higher confidence (a missed opportunity). It can NEVER loosen the gate below
its frozen prior, so it can never manufacture a promotion the static gate
would have refused, and it can never fabricate a proof — the factor is a pure
function of the SAME durable evidence ``value_landed``/``proof_history``
already trust. Recency-decayed with the SAME ``proof_history._DECAY = 0.85``
rank-based weighting ``value_reliability`` uses, so a key whose promotions
stopped landing several dreams ago can climb back toward neutral.

Reads TWO existing durable stores — the append-only ``.apex/dream-journal.json``
(to reconstruct WHICH confluence keys were promoted, and when, via the SAME
streak arithmetic ``dream._consecutive_streak`` uses) and
``.apex/proof-of-fix.json`` (via ``proof_history``) — and creates **no new
store**. Everything is pure and deterministic: same journal + proof content →
same factors (no clock, no random, no hash-order). Stdlib ``math``/``json``
only; no LLM.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from app.engine.proof_history import _DECAY, _module_of, load_proof_history
from app.engine.value_landed import _VERIFIED_LEVELS, _coverage_level, _held

__all__ = [
    "gate_tighten_factors",
    "effective_promote_gate",
    "REALIZED_PROMOTION_SCHEMA",
]

REALIZED_PROMOTION_SCHEMA = "apex-dream-gate-learn"

# z-score for the Wilson score interval lower bound — the SAME 1.96 constant
# ``idea_memory._WILSON_Z`` / ``value_reliability._WILSON_Z`` use, so "proven
# beats lucky" reads identically here: a thin-but-perfect 1-of-1 promotion
# cannot out-tighten a well-attested 8-of-10. Deterministic (no scipy/statistics).
_WILSON_Z = 1.96

# Don't tighten a key's gate until it has at least this many PROMOTED confluence
# samples — mirrors ``value_reliability._MIN_SAMPLES``. Below it the key is
# absent from the map (neutral 1.0), so a lone promotion can never tighten.
_MIN_SAMPLES = 2

# Bounded band floor for the TIGHTEN factor — mirrors
# ``value_reliability._REALIZATION_FLOOR``: a chronically-unrealized promotion
# key is damped toward this, never to 0 (which would make the gate
# unsatisfiable / lock the key out forever). The ceiling is a hard 1.0
# (neutral): the factor never loosens the gate below its static prior.
_GATE_FACTOR_FLOOR = 0.15

# The bounded band the EFFECTIVE streak may tighten into, on top of the static
# ``PROMOTE_STREAK`` — a fixed cap so a chronically-unrealized key asks for at
# most this many MORE consecutive dreams, never an unbounded/runaway gate.
_MAX_TIGHTEN_STREAK = 3

# The bounded band the EFFECTIVE confidence may tighten into, on top of the
# static ``PROMOTE_CONFIDENCE`` — a fixed cap on how much higher the bar can
# climb, mirroring ``_MAX_TIGHTEN_STREAK`` for the confidence dimension.
_MAX_TIGHTEN_CONFIDENCE = 0.15

_JOURNAL_REL = ".apex/dream-journal.json"
_CONFLUENCE_PREFIX = "confluence:"


def _wilson_lower_bound(phat: float, n: float) -> float:
    """Wilson score interval lower bound for rate ``phat`` over ``n`` samples.

    The SAME arithmetic as ``idea_memory._Stat.confidence`` /
    ``value_reliability._wilson_lower_bound`` (stdlib ``math`` only): it shrinks
    toward 0 as ``n`` shrinks, rewarding accumulated evidence over a lucky small
    sample. Safe on zero samples (returns 0.0). Deterministic."""
    if n <= 0:
        return 0.0
    z = _WILSON_Z
    denom = 1.0 + z * z / n
    center = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return (center - margin) / denom


def _load_journal(root: Path) -> list[Any]:
    """Read the append-only dream journal, tolerating a missing/corrupt file.

    Mirrors ``dream._load_journal`` exactly (same file, same tolerance) — this
    module reads it independently so it stays a dependency-free leaf (no
    import of ``dream.py``, which would risk an import cycle since ``dream.py``
    is the one wiring this module in)."""
    path = root / _JOURNAL_REL
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _promoted_generations(history: list[Any], min_streak: int) -> list[tuple[str, float]]:
    """Every ``(confluence_key, weight)`` promotion EVENT reconstructed from the
    journal, oldest→newest.

    Replicates ``dream._consecutive_streak`` over the journal's own
    ``{key: text}`` (or legacy bare-list) generations: at each generation index
    ``i``, a ``confluence:`` key is a promotion event iff its streak ending at
    ``i`` is ``>= min_streak`` (the SAME design-level gate
    ``dream._promotable_discoveries`` applies). Each event's weight is the
    recency decay ``_DECAY ** (n-1-i)`` (the SAME rank-based weighting
    ``value_reliability`` uses), so a promotion many dreams ago counts for less
    than a recent one. Deterministic; empty journal → ``[]``."""
    n = len(history)
    events: list[tuple[str, float]] = []
    for i, gen in enumerate(history):
        keys = gen.keys() if isinstance(gen, dict) else gen
        streak = 0
        for back in range(i, -1, -1):
            prior = history[back]
            prior_keys = prior.keys() if isinstance(prior, dict) else prior
            if _confluence_present(prior_keys, keys):
                streak += 1
            else:
                break
        weight = _DECAY ** (n - 1 - i)
        for key in keys:
            if isinstance(key, str) and key.startswith(_CONFLUENCE_PREFIX) and streak >= min_streak:
                events.append((key, weight))
    return events


def _confluence_present(candidate_keys: Any, target_keys: Any) -> bool:
    """True when EVERY ``confluence:`` key of ``target_keys`` also appears in
    ``candidate_keys`` — the per-generation membership test the streak walk
    needs (a generation "continues" a key's streak iff that key is present)."""
    target_set = set(target_keys)
    candidate_set = set(candidate_keys)
    confluence_targets = {k for k in target_set if isinstance(k, str)
                          and k.startswith(_CONFLUENCE_PREFIX)}
    return confluence_targets <= candidate_set


def _realized_modules(project_root: str | Path) -> dict[str, bool]:
    """Per-module: did a HELD + VERIFIED fix EVER land on it, per the durable
    proof-of-fix trail?

    Reuses ``value_landed``'s never-fake-green ``_held`` gate and coverage
    bucketer verbatim (the SAME bucketer ``value_reliability`` folds), so a
    rolled-back/blocked fix is invisible and only a landed-and-held move whose
    coverage level is in ``_VERIFIED_LEVELS`` counts. ``True`` once any such fix
    is seen on the module; modules with no held+verified fix are simply absent
    (read as ``False`` by the caller). Deterministic; empty history → ``{}``."""
    verified: dict[str, bool] = {}
    for proof in load_proof_history(project_root) or []:
        for rec in proof.get("fixes") or []:
            if not isinstance(rec, dict) or not _held(rec):
                continue
            if _coverage_level(rec) not in _VERIFIED_LEVELS:
                continue
            module = _module_of(rec)
            if module:
                verified[module] = True
    return verified


def gate_tighten_factors(project_root: str | Path,
                         promote_streak: int = 3) -> dict[str, float]:
    """Per-confluence-key gate-TIGHTEN factor, in ``[_GATE_FACTOR_FLOOR, 1.0]``.

    Reads the existing durable evidence ONLY — no new store. The journal
    (:func:`_promoted_generations`) reconstructs which ``confluence:<module>``
    keys were promoted, and when; each promotion event is credited
    ``realized=True`` iff the proof-of-fix trail (:func:`_realized_modules`)
    shows a held-and-verified fix EVER landed on that module. The recency-
    weighted realized rate is Wilson-lower-bounded on the promoted sample count,
    then clamped to the bounded tighten band.

    Because the rate is ``realized / promoted`` it is at most 1.0 — a key whose
    every promotion realized stays NEUTRAL (the gate is unaffected); one that
    over-promised (promoted repeatedly but never landed a verified fix) is
    TIGHTENED toward the floor. Keys with fewer than ``_MIN_SAMPLES`` promotion
    events are OMITTED (neutral by absence). Empty/missing journal or proof
    history → ``{}`` (every key neutral — the byte-identical default). Pure and
    deterministic; never raises (a missing dir / malformed store is tolerated
    by the underlying loaders).

    ``promote_streak`` is the caller's design-level streak gate (defaults to
    ``dream.PROMOTE_STREAK``'s value, ``3``, DUPLICATED here rather than
    imported — this module stays dependency-free of ``dream.py`` so ``dream.py``
    can import IT with no import cycle, even a lazy one). Passing the caller's
    live constant keeps the reconstructed promotion events aligned with
    whatever gate actually produced them."""
    root = Path(project_root)
    events = _promoted_generations(_load_journal(root), promote_streak)
    if not events:
        return {}
    realized_modules = _realized_modules(root)
    promoted: dict[str, float] = {}
    realized: dict[str, float] = {}
    samples: dict[str, int] = {}
    for key, weight in events:
        promoted[key] = promoted.get(key, 0.0) + weight
        samples[key] = samples.get(key, 0) + 1
        module = key[len(_CONFLUENCE_PREFIX):]
        if realized_modules.get(module):
            realized[key] = realized.get(key, 0.0) + weight
    factors: dict[str, float] = {}
    for key in sorted(promoted):
        n = samples[key]
        if n < _MIN_SAMPLES:
            continue
        denom = promoted[key]
        rate = realized.get(key, 0.0) / denom if denom > 0 else 0.0
        bound = _wilson_lower_bound(rate, n)
        factors[key] = round(min(1.0, max(_GATE_FACTOR_FLOOR, bound)), 4)
    return factors


def effective_promote_gate(factors: dict[str, float] | None, key: str = "*",
                           promote_streak: int = 3,
                           promote_confidence: float = 0.80) -> tuple[int, float]:
    """The MONOTONE-TIGHTEN-ONLY effective ``(streak, confidence)`` gate for
    ``key``, folding in its factor from :func:`gate_tighten_factors`.

    ``factor = factors.get(key, 1.0)`` (a missing map, missing key, or neutral
    ``1.0`` factor all mean the same thing: no tightening evidence). When
    ``factor >= 1.0`` the gate is the static constants EXACTLY —
    ``(promote_streak, promote_confidence)`` — byte-identical to today's
    behaviour. Otherwise both dimensions tighten, bounded:

      * ``effective_streak = min(promote_streak + _MAX_TIGHTEN_STREAK,
        round(promote_streak / max(factor, _GATE_FACTOR_FLOOR)))``
      * ``effective_confidence = min(1.0, promote_confidence +
        (1.0 - factor) * _MAX_TIGHTEN_CONFIDENCE)``

    **INVARIANT (the whole soundness property):**
    ``effective_streak >= promote_streak`` and
    ``effective_confidence >= promote_confidence`` ALWAYS — a buggy or
    adversarial factor can at worst make the gate MORE conservative (a missed
    graduation), never loosen it below the frozen prior. So this can never
    manufacture a false promotion or a fake proof: the tightened gate is a
    strict superset of restrictions over the static one. Pure arithmetic;
    deterministic.

    ``promote_streak``/``promote_confidence`` default to
    ``dream.PROMOTE_STREAK``/``dream.PROMOTE_CONFIDENCE``'s current values,
    DUPLICATED (not imported — see :func:`gate_tighten_factors`) so a caller
    that doesn't pass them still gets the same gate a byte-identical call would
    have used today."""
    factor = (factors or {}).get(key, 1.0)
    if factor >= 1.0:
        return promote_streak, promote_confidence
    effective_streak = min(promote_streak + _MAX_TIGHTEN_STREAK,
                           round(promote_streak / max(factor, _GATE_FACTOR_FLOOR)))
    effective_confidence = min(1.0, promote_confidence
                               + (1.0 - factor) * _MAX_TIGHTEN_CONFIDENCE)
    return effective_streak, effective_confidence
