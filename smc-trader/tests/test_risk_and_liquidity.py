from smctrader.candles import Candle
from smctrader.liquidity import equal_levels, find_sweeps


def _c(i, o, h, low, c):
    return Candle(i, o, h, low, c)


def test_sweep_detects_wick_through_prior_low_that_closes_back():
    # build a clear swing low at index 2, then a later candle wicks below it and
    # closes back above -> a sell-side liquidity sweep (stop hunt).
    candles = [
        _c(0, 10, 11, 9, 10), _c(1, 10, 11, 9, 10), _c(2, 10, 10.5, 6, 7),   # swing low @ 6
        _c(3, 7, 9, 6.5, 8), _c(4, 8, 9, 7, 8.5), _c(5, 8.5, 9, 7.5, 8.7),
        _c(6, 8.7, 9, 5.5, 8.6),                                              # wick to 5.5 < 6, closes 8.6
        _c(7, 8.6, 9, 8, 8.8), _c(8, 8.8, 9.2, 8.4, 9),
    ]
    sweeps = find_sweeps(candles)
    assert any(s.side == "sell" for s in sweeps)


def test_equal_levels_cluster_detected():
    # two swing highs at ~the same price form a buy-side liquidity pool
    candles = [
        _c(0, 1, 2, 0.5, 1.5), _c(1, 1.5, 5, 1, 2), _c(2, 2, 8, 1.5, 3),     # swing high 8
        _c(3, 3, 4, 2, 2.5), _c(4, 2.5, 5, 2, 3), _c(5, 3, 8.02, 2.5, 4),    # swing high ~8
        _c(6, 4, 4.5, 3, 3.5), _c(7, 3.5, 4, 3, 3.2),
    ]
    pools = equal_levels(candles, tolerance=0.1)
    assert any(p.side == "buy" for p in pools)
