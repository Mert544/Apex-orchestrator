"""Fair Value Gaps (FVG) / imbalances — 3-candle gaps left by fast moves."""

from __future__ import annotations

from dataclasses import dataclass

from .candles import Candle


@dataclass(frozen=True)
class FairValueGap:
    index: int           # index of the middle (displacement) candle
    direction: str       # "bullish" | "bearish"
    low: float
    high: float

    @property
    def midpoint(self) -> float:
        """The 50% consequent-encroachment level of the gap."""
        return (self.low + self.high) / 2.0


def find_fvgs(candles: list[Candle]) -> list[FairValueGap]:
    """Bullish FVG: candle[i-1].high < candle[i+1].low (a gap up); bearish: mirror."""
    gaps: list[FairValueGap] = []
    for i in range(1, len(candles) - 1):
        a, c = candles[i - 1], candles[i + 1]
        if a.high < c.low:
            gaps.append(FairValueGap(i, "bullish", a.high, c.low))
        elif a.low > c.high:
            gaps.append(FairValueGap(i, "bearish", c.high, a.low))
    return gaps
