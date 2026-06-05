"""Order block detection — the last opposing candle before a displacement move."""

from __future__ import annotations

from dataclasses import dataclass

from .candles import Candle


@dataclass(frozen=True)
class OrderBlock:
    index: int
    direction: str  # "bullish" | "bearish"
    low: float
    high: float

    def contains(self, price: float) -> bool:
        """True if ``price`` is inside the order-block zone."""
        return self.low <= price <= self.high


def _displacement(prev: Candle, cur: Candle, factor: float) -> bool:
    """A strong, body-dominant move relative to the prior candle's range."""
    return cur.body > max(prev.candle_range, 1e-9) * factor


def find_order_blocks(candles: list[Candle], factor: float = 0.8) -> list[OrderBlock]:
    """Bullish OB = last down candle before an up displacement; bearish = mirror.

    The order block is the zone (low..high) of that last opposing candle, where
    institutional orders are presumed to rest.
    """
    blocks: list[OrderBlock] = []
    for i in range(1, len(candles)):
        prev, cur = candles[i - 1], candles[i]
        if cur.bullish and prev.bearish and _displacement(prev, cur, factor):
            blocks.append(OrderBlock(i - 1, "bullish", prev.low, prev.high))
        elif cur.bearish and prev.bullish and _displacement(prev, cur, factor):
            blocks.append(OrderBlock(i - 1, "bearish", prev.low, prev.high))
    return blocks
