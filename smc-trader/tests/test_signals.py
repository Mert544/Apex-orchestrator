from smctrader.data import synthetic_candles
from smctrader.signals import generate_setups


def test_setups_are_risk_defined_and_directional():
    setups = generate_setups(synthetic_candles(seed=7, n=240), min_rr=1.5)
    for s in setups:
        assert s.direction in ("long", "short")
        assert s.rr >= 1.5
        assert s.stop != s.entry
        # long: stop below entry below/at target; short: mirror
        if s.direction == "long":
            assert s.stop < s.entry and s.target > s.entry
        else:
            assert s.stop > s.entry and s.target < s.entry


def test_no_setups_on_too_few_candles():
    assert generate_setups([], min_rr=1.5) == []
