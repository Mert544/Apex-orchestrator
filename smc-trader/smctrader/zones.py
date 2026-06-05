"""Premium / discount equilibrium and the Optimal Trade Entry (OTE) zone."""

from __future__ import annotations

from dataclasses import dataclass


def fib_levels(low: float, high: float) -> dict[str, float]:
    """Standard ICT fib levels of a low->high dealing range."""
    span = high - low
    return {
        "0.0": low,
        "0.236": low + span * 0.236,
        "0.382": low + span * 0.382,
        "0.5": low + span * 0.5,
        "0.618": low + span * 0.618,
        "0.705": low + span * 0.705,
        "0.79": low + span * 0.79,
        "1.0": high,
    }


def zone_of(low: float, high: float, price: float) -> str:
    """'premium' (sell), 'discount' (buy) or 'equilibrium' for ``price`` in a range."""
    eq = (low + high) / 2.0
    if price > eq:
        return "premium"
    if price < eq:
        return "discount"
    return "equilibrium"


@dataclass(frozen=True)
class OTEZone:
    direction: str  # "bullish" | "bearish"
    low: float
    high: float

    def contains(self, price: float) -> bool:
        """True if ``price`` falls inside the OTE band."""
        return self.low <= price <= self.high


def ote_zone(low: float, high: float, direction: str) -> OTEZone:
    """The 0.62-0.79 retracement of a dealing range (the OTE sweet spot).

    For a bullish setup the entry is a discount retracement of the up-leg; for a
    bearish setup it is a premium retracement of the down-leg.
    """
    levels = fib_levels(low, high)
    if direction == "bullish":
        return OTEZone("bullish", levels["0.618"], levels["0.79"])
    # bearish: mirror the band into premium (measured from the high downward)
    span = high - low
    return OTEZone("bearish", high - span * 0.79, high - span * 0.618)
