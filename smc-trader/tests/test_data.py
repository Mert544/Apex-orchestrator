from smctrader.data import synthetic_candles


def test_deterministic_for_a_seed():
    assert synthetic_candles(seed=7, n=50) == synthetic_candles(seed=7, n=50)
    assert synthetic_candles(seed=7, n=50) != synthetic_candles(seed=8, n=50)


def test_length_and_ohlc_invariants():
    candles = synthetic_candles(seed=3, n=120)
    assert len(candles) == 120
    for c in candles:
        assert c.high >= c.low
        assert c.high >= c.open and c.high >= c.close
        assert c.low <= c.open and c.low <= c.close
        assert c.high > 0 and c.low > 0
