from smctrader.candles import Candle
from smctrader.fvg import find_fvgs
from smctrader.order_blocks import find_order_blocks
from smctrader.zones import zone_of, ote_zone


def test_bullish_fvg_detected():
    candles = [Candle(0, 1, 2, 1, 1.5), Candle(1, 1.5, 5, 1.5, 4.5), Candle(2, 4.5, 6, 3, 5)]
    gaps = find_fvgs(candles)
    assert any(g.direction == "bullish" for g in gaps)


def test_order_block_detected():
    candles = [Candle(0, 2, 2.1, 1.4, 1.5), Candle(1, 1.5, 5, 1.5, 4.8)]
    obs = find_order_blocks(candles)
    assert obs and obs[0].direction == "bullish"


def test_zone_and_ote():
    assert zone_of(0, 10, 8) == "premium"
    assert zone_of(0, 10, 2) == "discount"
    ote = ote_zone(0, 10, "bullish")
    assert ote.low < ote.high
