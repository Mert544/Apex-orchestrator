"""The Power of Three (PO3): accumulation -> manipulation -> distribution."""


from dataclasses import dataclass

from .candles import Candle, highest_high, lowest_low


@dataclass(frozen=True)
class PO3:
    accumulation_high: float
    accumulation_low: float
    manipulation_index: int
    manipulation_side: str   # "buy" | "sell" | "none"
    distribution_direction: str  # "bullish" | "bearish" | "none"


def analyze_po3(candles: list[Candle], accumulation_frac: float = 0.34) -> PO3:
    """Split a session into accumulation, then find the manipulation grab and the
    distribution leg.

    Accumulation is the opening consolidation range; manipulation is the first
    close back inside after a wick beyond that range (a judas swing / stop run);
    distribution is the net move of the remaining candles.
    """
    if len(candles) < 3:
        return PO3(0.0, 0.0, -1, "none", "none")
    acc_end = max(1, int(len(candles) * accumulation_frac))
    acc = candles[:acc_end]
    acc_high = highest_high(acc)
    acc_low = lowest_low(acc)

    manip_index = -1
    manip_side = "none"
    for i in range(acc_end, len(candles)):
        c = candles[i]
        if c.high > acc_high and c.close < acc_high:
            manip_index, manip_side = i, "buy"   # grabbed buy-side, reversed down
            break
        if c.low < acc_low and c.close > acc_low:
            manip_index, manip_side = i, "sell"  # grabbed sell-side, reversed up
            break

    tail = candles[manip_index:] if manip_index >= 0 else candles[acc_end:]
    direction = "none"
    if tail:
        direction = "bullish" if tail[-1].close > tail[0].open else "bearish"
    return PO3(round(acc_high, 4), round(acc_low, 4), manip_index, manip_side, direction)
