"""Market structure: swing points, Break of Structure (BOS), Change of Character (CHoCH)."""


from dataclasses import dataclass

from .candles import Candle


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" | "low"


@dataclass(frozen=True)
class StructureEvent:
    index: int
    price: float
    event: str  # "BOS" | "CHoCH"
    direction: str  # "bullish" | "bearish"


def swing_highs(candles: list[Candle], left: int = 2, right: int = 2) -> list[SwingPoint]:
    """Fractal swing highs: a high strictly above ``left``/``right`` neighbours."""
    out: list[SwingPoint] = []
    for i in range(left, len(candles) - right):
        h = candles[i].high
        if all(h > candles[i - j].high for j in range(1, left + 1)) and \
           all(h > candles[i + j].high for j in range(1, right + 1)):
            out.append(SwingPoint(i, h, "high"))
    return out


def swing_lows(candles: list[Candle], left: int = 2, right: int = 2) -> list[SwingPoint]:
    """Fractal swing lows: a low strictly below ``left``/``right`` neighbours."""
    out: list[SwingPoint] = []
    for i in range(left, len(candles) - right):
        low = candles[i].low
        if all(low < candles[i - j].low for j in range(1, left + 1)) and \
           all(low < candles[i + j].low for j in range(1, right + 1)):
            out.append(SwingPoint(i, low, "low"))
    return out


def market_structure(candles: list[Candle], left: int = 2, right: int = 2) -> list[StructureEvent]:
    """Detect BOS (trend continuation) and CHoCH (trend reversal) events.

    A close above the last confirmed swing high is bullish; below the last swing
    low is bearish. If it agrees with the current trend it is a BOS; if it flips
    the trend it is a CHoCH (the first sign of a reversal).
    """
    highs = {p.index: p.price for p in swing_highs(candles, left, right)}
    lows = {p.index: p.price for p in swing_lows(candles, left, right)}
    events: list[StructureEvent] = []
    trend = ""  # "bullish" | "bearish" | ""
    last_high: float | None = None
    last_low: float | None = None
    for i, c in enumerate(candles):
        if i in highs:
            last_high = highs[i]
        if i in lows:
            last_low = lows[i]
        if last_high is not None and c.close > last_high:
            event = "BOS" if trend == "bullish" else "CHoCH"
            events.append(StructureEvent(i, c.close, event, "bullish"))
            trend = "bullish"
            last_high = None  # consumed; wait for the next swing high
        elif last_low is not None and c.close < last_low:
            event = "BOS" if trend == "bearish" else "CHoCH"
            events.append(StructureEvent(i, c.close, event, "bearish"))
            trend = "bearish"
            last_low = None
    return events


def current_trend(candles: list[Candle]) -> str:
    """The latest structural trend, or '' if undetermined."""
    events = market_structure(candles)
    return events[-1].direction if events else ""
