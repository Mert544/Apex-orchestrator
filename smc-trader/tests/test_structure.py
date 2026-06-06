from smctrader.candles import Candle
from smctrader.structure import swing_highs, market_structure


def _c(i, o, h, low, c):
    return Candle(i, o, h, low, c)


def test_swing_high_and_low_detected():
    candles = [_c(0, 1, 2, 0.5, 1.5), _c(1, 1.5, 3, 1, 2.5), _c(2, 2.5, 5, 2, 4),
               _c(3, 4, 3.5, 2, 2.5), _c(4, 2.5, 3, 1.5, 2)]
    assert any(p.index == 2 for p in swing_highs(candles, 2, 2))


def test_market_structure_emits_events():
    candles = [Candle(i, 1, 1 + i * 0.1, 0.5, 1 + i * 0.1) for i in range(20)]
    events = market_structure(candles)
    assert all(e.event in ("BOS", "CHoCH") for e in events)
