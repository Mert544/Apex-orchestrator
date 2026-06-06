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


def test_swept_swing_is_not_counted_twice():
    # swing low @ 6 (index 2) is wicked-and-reclaimed at index 6 AND again at
    # index 7; the docstring promises each swing provides liquidity exactly once,
    # so only the first grab is reported.
    candles = [
        _c(0, 10, 11, 9, 10), _c(1, 10, 11, 9, 10), _c(2, 10, 10.5, 6, 7),
        _c(3, 7, 9, 6.5, 8), _c(4, 8, 9, 7, 8.5), _c(5, 8.5, 9, 7.5, 8.7),
        _c(6, 8.7, 9, 5.5, 8.6),     # first grab of the 6-low
        _c(7, 8.6, 9, 5.4, 8.8),     # wicks below 6 again -> must NOT re-count
        _c(8, 8.8, 9.2, 8.4, 9),
    ]
    sells = [s for s in find_sweeps(candles) if s.side == "sell"]
    assert len(sells) == 1
    assert sells[0].index == 6 and sells[0].level == 6


def test_wick_that_closes_below_is_a_break_not_a_sweep():
    # candle wicks below the swing low but also CLOSES below it -> a breakdown,
    # not a stop-hunt sweep.
    candles = [
        _c(0, 10, 11, 9, 10), _c(1, 10, 11, 9, 10), _c(2, 10, 10.5, 6, 7),
        _c(3, 7, 9, 6.5, 8), _c(4, 8, 9, 7, 8.5), _c(5, 8.5, 9, 7.5, 8.7),
        _c(6, 8.7, 9, 5.5, 5.6),     # closes 5.6 < 6 -> break, not sweep
        _c(7, 5.6, 6, 5, 5.5), _c(8, 5.5, 6, 5, 5.4),
    ]
    assert not [s for s in find_sweeps(candles) if s.side == "sell"]


def test_equal_levels_respects_tolerance_boundary():
    # highs 8 and 8.20 are 0.20 apart: clustered at tol=0.25, separate at tol=0.1
    candles = [
        _c(0, 1, 2, 0.5, 1.5), _c(1, 1.5, 5, 1, 2), _c(2, 2, 8, 1.5, 3),
        _c(3, 3, 4, 2, 2.5), _c(4, 2.5, 5, 2, 3), _c(5, 3, 8.20, 2.5, 4),
        _c(6, 4, 4.5, 3, 3.5), _c(7, 3.5, 4, 3, 3.2),
    ]
    assert any(p.side == "buy" for p in equal_levels(candles, tolerance=0.25))
    assert not [p for p in equal_levels(candles, tolerance=0.1) if p.side == "buy"]


def test_no_pools_or_sweeps_on_empty_input():
    assert equal_levels([]) == []
    assert find_sweeps([]) == []
