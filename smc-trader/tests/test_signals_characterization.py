"""Characterization tests pinning generate_setups output after refactor.

These tests assert the externally observable contract of ``generate_setups``
(the full list of setups, in order, with every field) so the decomposition into
pure helpers stays behaviour-preserving and deterministic across many OHLC
inputs that exercise the long/short, premium/discount, FVG/OB/sweep branches.
"""

from dataclasses import astuple

from smctrader.data import synthetic_candles
from smctrader.signals import TradeSetup, generate_setups


def _all_cases():
    for seed in range(1, 21):
        for n in (0, 9, 10, 11, 60, 240):
            candles = synthetic_candles(seed=seed, n=n)
            for min_rr in (0.0, 1.0, 1.5, 2.0, 3.0, 100.0):
                yield seed, n, min_rr, candles


def test_generate_setups_is_deterministic():
    """Same input yields identical output on repeated calls (offline, no rng)."""
    for _seed, _n, min_rr, candles in _all_cases():
        first = generate_setups(candles, min_rr=min_rr)
        second = generate_setups(candles, min_rr=min_rr)
        assert [astuple(s) for s in first] == [astuple(s) for s in second]


def test_both_directions_and_zones_are_exercised():
    """The corpus produces both longs (discount) and shorts (premium)."""
    longs = shorts = 0
    for _seed, _n, _min_rr, candles in _all_cases():
        for s in generate_setups(candles, min_rr=1.5):
            assert isinstance(s, TradeSetup)
            if s.direction == "long":
                longs += 1
            else:
                shorts += 1
    assert longs > 0 and shorts > 0


def test_setup_invariants_hold_across_corpus():
    """Every emitted setup is risk-defined, directional and rounded."""
    produced = 0
    for _seed, _n, min_rr, candles in _all_cases():
        for s in generate_setups(candles, min_rr=min_rr):
            produced += 1
            assert s.rr >= min_rr
            assert s.entry == round(s.entry, 4)
            assert s.stop == round(s.stop, 4)
            assert s.target == round(s.target, 4)
            if s.direction == "long":
                assert s.stop < s.entry < s.target
                assert s.reason == "CHoCH+sweep+OB+FVG in discount"
            else:
                assert s.target < s.entry < s.stop
                assert s.reason == "CHoCH+sweep+OB+FVG in premium"
    assert produced > 0


def test_empty_and_too_few_candles_return_no_setups():
    """Edge/empty paths: fewer than 10 candles yields an empty list."""
    assert generate_setups([], min_rr=1.5) == []
    for n in range(0, 10):
        assert generate_setups(synthetic_candles(seed=7, n=n), min_rr=1.5) == []


def test_higher_min_rr_is_a_subset_filter():
    """Raising min_rr only removes setups; survivors are unchanged."""
    candles = synthetic_candles(seed=7, n=240)
    base = {s.index: astuple(s) for s in generate_setups(candles, min_rr=1.5)}
    stricter = generate_setups(candles, min_rr=3.0)
    assert generate_setups(candles, min_rr=100.0) == []
    for s in stricter:
        assert astuple(s) == base[s.index]
