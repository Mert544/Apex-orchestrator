"""OHLC candle data structure and helpers."""


from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    """A single OHLC bar. ``time`` is an epoch second or a bar index."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def candle_range(self) -> float:
        return self.high - self.low

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0


def highest_high(candles: list[Candle]) -> float:
    """The highest high across the candles (0.0 for an empty series)."""
    return max((c.high for c in candles), default=0.0)


def lowest_low(candles: list[Candle]) -> float:
    """The lowest low across the candles (0.0 for an empty series)."""
    return min((c.low for c in candles), default=0.0)
