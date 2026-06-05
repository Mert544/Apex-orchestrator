"""Liquidity: equal highs/lows (resting liquidity) and sweeps (stop hunts)."""


from dataclasses import dataclass

from .candles import Candle
from .structure import swing_highs, swing_lows


@dataclass(frozen=True)
class LiquidityPool:
    price: float
    side: str  # "buy" (above highs) | "sell" (below lows)
    indices: tuple[int, ...]


@dataclass(frozen=True)
class LiquiditySweep:
    index: int
    side: str  # "buy" | "sell"
    level: float


def equal_levels(candles: list[Candle], tolerance: float = 0.05) -> list[LiquidityPool]:
    """Cluster swing highs/lows that sit within ``tolerance`` — resting liquidity."""
    pools: list[LiquidityPool] = []
    for points, side in ((swing_highs(candles), "buy"), (swing_lows(candles), "sell")):
        used: set[int] = set()
        for i, p in enumerate(points):
            if i in used:
                continue
            cluster = [p.index]
            for j in range(i + 1, len(points)):
                if abs(points[j].price - p.price) <= tolerance:
                    cluster.append(points[j].index)
                    used.add(j)
            if len(cluster) >= 2:
                pools.append(LiquidityPool(round(p.price, 4), side, tuple(cluster)))
    return pools


def find_sweeps(candles: list[Candle], left: int = 2, right: int = 2) -> list[LiquiditySweep]:
    """A wick beyond the nearest un-swept swing that closes back inside it.

    Each swing provides liquidity exactly once: after it is grabbed it is removed
    from the pool, so counts stay realistic (no re-counting old swings).
    """
    sweeps: list[LiquiditySweep] = []
    highs = swing_highs(candles, left, right)
    lows = swing_lows(candles, left, right)
    swept_high: set[int] = set()
    swept_low: set[int] = set()
    for c_idx in range(right + 1, len(candles)):
        c = candles[c_idx]
        prior_highs = [h for h in highs if h.index < c_idx and h.index not in swept_high]
        if prior_highs:
            h = prior_highs[-1]
            if c.high > h.price and c.close < h.price:
                sweeps.append(LiquiditySweep(c_idx, "buy", h.price))
                swept_high.add(h.index)
        prior_lows = [low for low in lows if low.index < c_idx and low.index not in swept_low]
        if prior_lows:
            low = prior_lows[-1]
            if c.low < low.price and c.close > low.price:
                sweeps.append(LiquiditySweep(c_idx, "sell", low.price))
                swept_low.add(low.index)
    return sweeps
