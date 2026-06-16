"""Combine the SMC concepts into concrete, risk-defined trade setups."""


from dataclasses import dataclass

from .candles import Candle
from .fvg import FairValueGap, find_fvgs
from .liquidity import LiquiditySweep, find_sweeps
from .order_blocks import OrderBlock, find_order_blocks
from .risk import r_multiple
from .structure import StructureEvent, market_structure
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


def _recent_sweep(
    sweeps: list[LiquiditySweep], ev: StructureEvent
) -> LiquiditySweep | None:
    """The most recent sweep within 10 bars before the structure event."""
    return next((s for s in sweeps if 0 <= ev.index - s.index <= 10), None)


def _aligned_ob(obs: list[OrderBlock], ev: StructureEvent) -> OrderBlock | None:
    """The latest order block matching the event direction at or before it."""
    return next(
        (o for o in reversed(obs) if o.direction == ev.direction and o.index <= ev.index),
        None,
    )


def _has_aligned_fvg(fvgs: list[FairValueGap], ev: StructureEvent) -> bool:
    """True if an FVG within 10 bars shares the event direction."""
    return any(
        abs(f.index - ev.index) <= 10 and f.direction == ev.direction for f in fvgs
    )


def _aligned_concepts(
    ev: StructureEvent,
    obs: list[OrderBlock],
    sweeps: list[LiquiditySweep],
    fvgs: list[FairValueGap],
) -> tuple[OrderBlock, LiquiditySweep] | None:
    """The order block + sweep backing this event, or None if alignment fails."""
    sweep = _recent_sweep(sweeps, ev)
    ob = _aligned_ob(obs, ev)
    if sweep is None or ob is None or not _has_aligned_fvg(fvgs, ev):
        return None
    return ob, sweep


def _build_setup(
    ev: StructureEvent,
    ob: OrderBlock,
    sweep: LiquiditySweep,
    range_low: float,
    range_high: float,
    min_rr: float,
) -> TradeSetup | None:
    """Turn aligned concepts into a risk-defined setup, or None if rejected."""
    entry = (ob.low + ob.high) / 2.0
    if ev.direction == "bullish":
        if zone_of(range_low, range_high, entry) == "premium":
            return None  # only buy discount
        stop = min(ob.low, sweep.level) - 0.1
        target = range_high
        direction, reason = "long", "CHoCH+sweep+OB+FVG in discount"
    else:
        if zone_of(range_low, range_high, entry) == "discount":
            return None  # only sell premium
        stop = max(ob.high, sweep.level) + 0.1
        target = range_low
        direction, reason = "short", "CHoCH+sweep+OB+FVG in premium"
    rr = r_multiple(entry, stop, target)
    if rr < min_rr:
        return None
    return TradeSetup(
        ev.index, direction, round(entry, 4), round(stop, 4),
        round(target, 4), reason, rr,
    )


def generate_setups(candles: list[Candle], min_rr: float = 1.5) -> list[TradeSetup]:
    """A setup forms when structure, an order block, an FVG and a liquidity sweep
    align in the right premium/discount zone.

    Long: a bullish CHoCH/BOS after a sell-side sweep, entering a bullish order
    block that sits in discount, stop below the swept low, target the range high.
    Short is the mirror.
    """
    if len(candles) < 10:
        return []
    obs = find_order_blocks(candles)
    fvgs = find_fvgs(candles)
    sweeps = find_sweeps(candles)
    events = market_structure(candles)
    range_low = min(c.low for c in candles)
    range_high = max(c.high for c in candles)

    setups: list[TradeSetup] = []
    for ev in events:
        aligned = _aligned_concepts(ev, obs, sweeps, fvgs)
        if aligned is None:
            continue
        ob, sweep = aligned
        setup = _build_setup(ev, ob, sweep, range_low, range_high, min_rr)
        if setup is not None:
            setups.append(setup)
    return setups
