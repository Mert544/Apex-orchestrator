from smctrader.data import synthetic_candles
from smctrader.power_of_three import analyze_po3
from smctrader.candles import Candle


def test_po3_structure_on_real_series():
    po3 = analyze_po3(synthetic_candles(seed=7, n=120))
    assert po3.accumulation_high >= po3.accumulation_low
    assert po3.distribution_direction in ("bullish", "bearish", "none")
    assert po3.manipulation_side in ("buy", "sell", "none")


def test_po3_degenerate_on_tiny_input():
    po3 = analyze_po3([Candle(0, 1, 1, 1, 1)])
    assert po3.distribution_direction == "none" and po3.manipulation_index == -1
