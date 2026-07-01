"""Wilson score-interval lower bound — the SINGLE shared implementation.

The "proven beats lucky" arithmetic (a thin-but-perfect small sample cannot
outrank a well-attested larger one) is used by ``value_reliability`` (operator
value realization) and ``dream_gate_learn`` (tighten-only promote gate), and
mirrors ``idea_memory._Stat.confidence``. Factored into ONE dependency-free leaf
so the identical body is not copied per consumer.

Dependency-free by design: imports nothing from ``app`` (stdlib ``math`` only),
so this edge closes no import cycle. Deterministic; no clock/random.
"""

from __future__ import annotations

import math

# z-score for the Wilson lower bound — 1.96 ≈ the 95% one-sided normal quantile.
# Fixed constant (no scipy/statistics) so the bound is deterministic.
WILSON_Z = 1.96


def wilson_lower_bound(phat: float, n: float) -> float:
    """Wilson score interval lower bound for rate ``phat`` over ``n`` samples.

    Shrinks toward 0 as ``n`` shrinks, so accumulated evidence is rewarded and a
    lucky small sample is discounted. Safe on zero samples (returns 0.0)."""
    if n <= 0:
        return 0.0
    z = WILSON_Z
    denom = 1.0 + z * z / n
    center = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return (center - margin) / denom
