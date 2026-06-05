"""Combine the SMC concepts into concrete, risk-defined trade setups."""


from dataclasses import dataclass

from .candles import Candle
from .fvg import find_fvgs
from .liquidity import find_sweeps
from .order_blocks import find_order_blocks
from .risk import r_multiple
from .structure import market_structure
from .zones import zone_of


@dataclass(frozen=True)
class TradeSetup:
    index: int
    direction: str   # "long" | "short"
    entry: float
    stop: float
    target: float
    reason: str
    rr: float


def generate_setups(candles: list[Candle], min_rr: float = 1.5) -> list[TradeSetup]:
    """A setup forms when structure, an order block, an FVG and a liquidity sweep
    align in the right premium/discount zone.

    Long: a bullish CHoCH/BOS after a sell-side sweep, entering a bullish order
    block that sits in discount, stop below the swept low, target the range high.
    Short is the mirror.
    """
    if len(candles) < 10:
        return []
    setups: list[TradeSetup] = []
    obs = find_order_blocks(candles)
    fvgs = find_fvgs(candles)
    sweeps = find_sweeps(candles)
    events = market_structure(candles)
    range_low = min(c.low for c in candles)
    range_high = max(c.high for c in candles)

    fvg_idx = {f.index: f for f in fvgs}
    for ev in events:
        recent_sweep = next((s for s in sweeps if 0 <= ev.index - s.index <= 10), None)
        if recent_sweep is None:
            continue
        ob = next((o for o in reversed(obs) if o.direction == ev.direction and o.index <= ev.index), None)
        if ob is None:
            continue
        has_fvg = any(abs(k - ev.index) <= 10 and f.direction == ev.direction for k, f in fvg_idx.items())
        if not has_fvg:
            continue
        entry = (ob.low + ob.high) / 2.0
        if ev.direction == "bullish":
            if zone_of(range_low, range_high, entry) == "premium":
                continue  # only buy discount
            stop = min(ob.low, recent_sweep.level) - 0.1
            target = range_high
            rr = r_multiple(entry, stop, target)
            if rr >= min_rr:
                setups.append(TradeSetup(ev.index, "long", round(entry, 4), round(stop, 4),
                                         round(target, 4), "CHoCH+sweep+OB+FVG in discount", rr))
        else:
            if zone_of(range_low, range_high, entry) == "discount":
                continue  # only sell premium
            stop = max(ob.high, recent_sweep.level) + 0.1
            target = range_low
            rr = r_multiple(entry, stop, target)
            if rr >= min_rr:
                setups.append(TradeSetup(ev.index, "short", round(entry, 4), round(stop, 4),
                                         round(target, 4), "CHoCH+sweep+OB+FVG in premium", rr))
    return setups
