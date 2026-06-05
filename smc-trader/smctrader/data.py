"""Deterministic synthetic OHLC generator (offline) for backtests and demos.

Produces a believable price path with trends, pullbacks, and the occasional
liquidity-grab wick, seeded so the same seed always yields the same series.
"""


from .candles import Candle


def synthetic_candles(seed: int = 7, n: int = 240, start: float = 100.0) -> list[Candle]:
    """A deterministic OHLC series with structure the detectors can find."""
    candles: list[Candle] = []
    price = start
    x = seed & 0x7FFFFFFF
    trend = 1.0
    for i in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        r = (x % 1000) / 1000.0  # 0..1 deterministic
        # Flip the trend periodically to create market structure.
        if i % 40 == 0:
            trend = -trend
        drift = trend * 0.35
        step = drift + (r - 0.5) * 1.8
        open_ = price
        close = max(1.0, price + step)
        high = max(open_, close) + r * 0.9
        low = min(open_, close) - (1.0 - r) * 0.9
        # Occasional liquidity-grab wick (stop hunt) every ~17 bars.
        if i % 17 == 0 and i > 0:
            low -= 1.4 * r
        candles.append(Candle(time=i, open=round(open_, 4), high=round(high, 4),
                              low=round(low, 4), close=round(close, 4), volume=round(100 + r * 50, 2)))
        price = close
    return candles
