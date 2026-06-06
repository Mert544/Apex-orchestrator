from smctrader.data import synthetic_candles
from smctrader.signals import generate_setups
from smctrader.zones import zone_of


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


def test_longs_only_in_discount_shorts_only_in_premium():
    candles = synthetic_candles(seed=7, n=240)
    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    for s in generate_setups(candles, min_rr=1.5):
        z = zone_of(lo, hi, s.entry)
        if s.direction == "long":
            assert z != "premium"      # buy discount/equilibrium only
        else:
            assert z != "discount"     # sell premium/equilibrium only


def test_higher_min_rr_filters_setups_out():
    candles = synthetic_candles(seed=7, n=240)
    base = generate_setups(candles, min_rr=1.5)
    assert base                                   # baseline produces setups
    assert generate_setups(candles, min_rr=100.0) == []   # nothing clears 100R


def test_returned_setups_always_meet_the_threshold():
    candles = synthetic_candles(seed=11, n=240)
    for thr in (1.5, 2.0, 3.0):
        assert all(s.rr >= thr for s in generate_setups(candles, min_rr=thr))


def test_setup_fields_are_rounded_and_consistent():
    for s in generate_setups(synthetic_candles(seed=3, n=240), min_rr=1.5):
        assert s.entry == round(s.entry, 4)
        assert s.stop == round(s.stop, 4)
        assert s.target == round(s.target, 4)
        assert "OB" in s.reason and "FVG" in s.reason
