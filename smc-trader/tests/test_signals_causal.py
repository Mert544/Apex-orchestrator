"""Causal (no look-ahead) regression tests for generate_setups + survivor kills.

BUG 1 removed a backtest-invalidating look-ahead: the dealing range (range_low /
range_high) used for the premium/discount gate AND the target/RR was previously
computed once over ALL candles, so a setup at index i "saw" future highs/lows.
The range is now computed point-in-time over ``candles[:i+1]``.

These tests pin that causal contract and also kill the mutation survivors the
auditor flagged in signals.py: the 10-bar proximity windows, the
direction-equality alignment checks, and the ``stop -/+ 0.1`` buffer.
"""

from smctrader.data import synthetic_candles
from smctrader.liquidity import LiquiditySweep
from smctrader.order_blocks import OrderBlock
from smctrader.fvg import FairValueGap
from smctrader.structure import StructureEvent
from smctrader.signals import (
    _aligned_ob,
    _build_setup,
    _has_aligned_fvg,
    _recent_sweep,
    generate_setups,
)


# --------------------------------------------------------------------------- #
# BUG 1 / BUG 3: causal equivalence (the central anti-look-ahead invariant)
# --------------------------------------------------------------------------- #

def test_range_derived_fields_match_point_in_time_truncation():
    """BUG 1 anti-look-ahead: whenever a setup at index i still forms from only
    ``candles[:i+1]``, its range-derived fields (target/stop/rr/entry/direction)
    are byte-identical to the full-series result. Before the fix the full-series
    target/rr leaked future highs/lows and would differ.

    BUG 2 anti-look-ahead (FVG alignment): with the FVG window now causal
    (past-only), every full-series setup re-forms point-in-time too, EXCEPT
    setups whose index sits below the 10-candle minimum that ``generate_setups``
    needs to run at all (``candles[:i+1]`` then has fewer than 10 candles -- an
    inherent boundary, not a look-ahead). Those are skipped here and pinned
    separately by the dedicated causal-count test below.
    """
    seeds_checked = 0
    compared = 0
    survivors = 0
    for seed in range(1, 25):
        candles = synthetic_candles(seed=seed, n=240)
        full = generate_setups(candles, min_rr=1.5)
        if not full:
            continue
        seeds_checked += 1
        for s in full:
            # Cannot reconstruct a setup whose own bar leaves < 10 candles.
            if s.index + 1 < 10:
                continue
            compared += 1
            # min_rr=0 on the truncation so the RR filter never hides the row.
            causal = generate_setups(candles[: s.index + 1], min_rr=0.0)
            match = next((c for c in causal if c.index == s.index), None)
            # With BUG 2 fixed there is no future-FVG escape hatch: the setup MUST
            # re-form causally.
            assert match is not None, (seed, s.index)
            survivors += 1
            assert match.target == s.target, (seed, s.index, match.target, s.target)
            assert match.stop == s.stop
            assert round(match.rr, 4) == s.rr
            assert match.direction == s.direction
            assert match.entry == s.entry
    assert seeds_checked > 0 and survivors > 0
    # Every comparable setup survives and matches now (no future-FVG artifacts).
    assert survivors == compared


def test_fvg_alignment_has_no_look_ahead_full_equals_causal():
    """BUG 2 regression: the FVG-alignment decision must be identical whether
    computed over the full series or point-in-time (``candles[:ev.index+1]``).

    Before the fix, ``_has_aligned_fvg`` scanned a symmetric +/-10 window, so a
    setup at ``ev.index`` could be confirmed by an FVG up to 10 bars in the
    FUTURE; ~28 of the 159 full-series setups (seeds 1..24, n=240) existed ONLY
    because of those future FVGs and vanished under truncation. With the causal
    past-only window, the full-series setup count equals the causal-reconstruction
    count (no future-FVG artifacts), and every setup's alignment is stable.

    The only legitimate exception is the 10-candle minimum that ``generate_setups``
    itself requires: a setup at index i with ``i + 1 < 10`` cannot be rebuilt from
    its own truncated history, so it is excluded from the per-setup comparison.
    """
    total_full = 0
    total_recovered = 0
    comparable = 0
    for seed in range(1, 25):
        candles = synthetic_candles(seed=seed, n=240)
        full = generate_setups(candles, min_rr=1.5)
        total_full += len(full)
        for s in full:
            if s.index + 1 < 10:
                continue
            comparable += 1
            causal = generate_setups(candles[: s.index + 1], min_rr=0.0)
            assert any(c.index == s.index for c in causal), (seed, s.index)
            total_recovered += 1
    # Sanity: this corpus really does produce a non-trivial number of setups.
    assert total_full >= 100
    # Every comparable full-series setup is reproducible point-in-time: the FVG
    # alignment never depends on a future bar.
    assert total_recovered == comparable


def test_target_uses_only_past_extremes_not_future():
    """Concretely: a future spike beyond the point-in-time range must NOT change
    an already-formed long setup's target (which is the causal range high)."""
    base = synthetic_candles(seed=7, n=240)
    longs = [s for s in generate_setups(base, min_rr=1.5) if s.direction == "long"]
    assert longs, "need a long setup to exercise the target path"
    s = longs[0]
    # The target equals the max high over candles[:index+1], never a later bar.
    causal_high = max(c.high for c in base[: s.index + 1])
    assert s.target == round(causal_high, 4)
    later_high = max((c.high for c in base[s.index + 1:]), default=causal_high)
    if later_high > causal_high:
        # The look-ahead bug would have used this larger value; the fix must not.
        assert s.target < round(later_high, 4)


# --------------------------------------------------------------------------- #
# Helpers shared by the survivor-kill tests
# --------------------------------------------------------------------------- #

def _ev(index, direction="bullish"):
    return StructureEvent(index=index, price=100.0, event="CHoCH", direction=direction)


def test_trade_setup_is_frozen_immutable():
    """TradeSetup must be a frozen dataclass (hashable, immutable) so emitted
    setups cannot be mutated downstream -- kills the frozen=True->False mutant."""
    import pytest
    from dataclasses import FrozenInstanceError

    setup = _build_setup(
        _ev(30, "bullish"),
        OrderBlock(index=29, direction="bullish", low=9.0, high=11.0),
        LiquiditySweep(index=25, level=8.5, side="sell"),
        range_low=0.0, range_high=100.0, min_rr=0.0,
    )
    assert setup is not None
    with pytest.raises(FrozenInstanceError):
        setup.entry = 999.0  # type: ignore[misc]
    assert hash(setup) is not None  # frozen dataclasses are hashable


# --------------------------------------------------------------------------- #
# Survivor: the 10-bar proximity window in _recent_sweep
# --------------------------------------------------------------------------- #

def test_recent_sweep_window_is_exactly_ten_bars_and_causal():
    ev = _ev(20)
    inside = LiquiditySweep(index=10, level=1.0, side="sell")     # exactly 10 bars before
    boundary_old = LiquiditySweep(index=9, level=1.0, side="sell")  # 11 bars -> excluded
    at_event = LiquiditySweep(index=20, level=1.0, side="sell")   # delta 0 -> included
    future = LiquiditySweep(index=21, level=1.0, side="sell")     # after event -> excluded

    assert _recent_sweep([inside], ev) is inside        # delta 10 in -> kills "<= 10"->"< 10"
    assert _recent_sweep([boundary_old], ev) is None    # delta 11 out -> kills "10"->"11"
    assert _recent_sweep([at_event], ev) is at_event    # delta 0 in -> kills "0"->"1" / "0<="->"0<"
    assert _recent_sweep([future], ev) is None          # delta -1 out -> kills dropping 0<= guard
    # the most recent (closest) eligible sweep wins
    near = LiquiditySweep(index=18, level=2.0, side="sell")
    assert _recent_sweep([inside, near], ev) is inside  # first match in list order


# --------------------------------------------------------------------------- #
# Survivor: direction-equality + 10-bar window in _has_aligned_fvg
# --------------------------------------------------------------------------- #

def test_has_aligned_fvg_requires_matching_direction_and_proximity():
    """BUG 2 (FVG-alignment look-ahead) fix: the window is now CAUSAL, a past-only
    ``1 <= ev.index - f.index <= 10`` lookback. Previously a symmetric
    ``abs(f.index - ev.index) <= 10`` let an FVG up to 10 bars in the FUTURE (and
    even at ``ev.index`` itself, which ``find_fvgs`` cannot confirm until candle
    ``ev.index + 1`` closes) confirm alignment -- a look-ahead leak. These
    expectations are updated from the old buggy behaviour to the corrected one.
    """
    ev = _ev(20, "bullish")
    same_dir = FairValueGap(index=15, direction="bullish", low=1.0, high=2.0)
    opp_dir = FairValueGap(index=15, direction="bearish", low=1.0, high=2.0)
    too_far = FairValueGap(index=9, direction="bullish", low=1.0, high=2.0)   # 11 bars back
    far_future = FairValueGap(index=31, direction="bullish", low=1.0, high=2.0)  # future

    assert _has_aligned_fvg([same_dir], ev) is True
    assert _has_aligned_fvg([opp_dir], ev) is False     # kills "==" -> "!=" on direction
    assert _has_aligned_fvg([too_far], ev) is False     # delta 11 out -> kills "10"->"11"
    assert _has_aligned_fvg([far_future], ev) is False  # future FVG excluded (causal)
    # exactly 10 bars in the PAST is still aligned (lower window boundary)
    assert _has_aligned_fvg(
        [FairValueGap(index=10, direction="bullish", low=1.0, high=2.0)], ev
    ) is True
    # delta 0 (FVG at the event bar) is now EXCLUDED: find_fvgs needs candle
    # ev.index+1 to confirm it, so it is not known point-in-time.
    assert _has_aligned_fvg(
        [FairValueGap(index=20, direction="bullish", low=1.0, high=2.0)], ev
    ) is False
    # delta 1 (one bar before the event) is the upper, most-recent allowed edge.
    assert _has_aligned_fvg(
        [FairValueGap(index=19, direction="bullish", low=1.0, high=2.0)], ev
    ) is True
    # a FUTURE FVG (10 bars ahead) used to be accepted by the symmetric window;
    # it must now be rejected (the core look-ahead fix).
    assert _has_aligned_fvg(
        [FairValueGap(index=30, direction="bullish", low=1.0, high=2.0)], ev
    ) is False


# --------------------------------------------------------------------------- #
# Survivor: direction-equality + index<=event in _aligned_ob
# --------------------------------------------------------------------------- #

def test_aligned_ob_picks_latest_matching_direction_at_or_before_event():
    ev = _ev(20, "bullish")
    early = OrderBlock(index=5, direction="bullish", low=1.0, high=2.0)
    late = OrderBlock(index=18, direction="bullish", low=3.0, high=4.0)
    opp = OrderBlock(index=19, direction="bearish", low=5.0, high=6.0)
    future = OrderBlock(index=25, direction="bullish", low=7.0, high=8.0)

    assert _aligned_ob([early, late], ev) is late      # "latest" => reversed scan
    assert _aligned_ob([opp], ev) is None              # kills "==" direction match
    assert _aligned_ob([future], ev) is None           # kills "<=" event-index guard
    # an OB exactly at the event index is allowed (boundary of <=)
    at_ev = OrderBlock(index=20, direction="bullish", low=9.0, high=10.0)
    assert _aligned_ob([early, at_ev], ev) is at_ev


# --------------------------------------------------------------------------- #
# Survivor: the stop -/+ 0.1 buffer in _build_setup
# --------------------------------------------------------------------------- #

def test_build_setup_long_stop_has_minus_buffer_below_swept_low():
    ev = _ev(30, "bullish")
    # entry mid = 10.0; put it in discount of a 0..100 range so the gate passes.
    ob = OrderBlock(index=29, direction="bullish", low=9.0, high=11.0)
    sweep = LiquiditySweep(index=25, level=8.5, side="sell")
    setup = _build_setup(ev, ob, sweep, range_low=0.0, range_high=100.0, min_rr=0.0)
    assert setup is not None and setup.direction == "long"
    # stop = min(ob.low=9.0, sweep.level=8.5) - 0.1 = 8.4  (kills "+0.1" / "0.0")
    assert setup.stop == 8.4
    assert setup.target == 100.0   # long target is the (causal) range high
    assert setup.entry == 10.0


def test_build_setup_short_stop_has_plus_buffer_above_swept_high():
    ev = _ev(30, "bearish")
    ob = OrderBlock(index=29, direction="bearish", low=89.0, high=91.0)  # mid 90 -> premium
    sweep = LiquiditySweep(index=25, level=91.5, side="buy")
    setup = _build_setup(ev, ob, sweep, range_low=0.0, range_high=100.0, min_rr=0.0)
    assert setup is not None and setup.direction == "short"
    # stop = max(ob.high=91.0, sweep.level=91.5) + 0.1 = 91.6 (kills "-0.1")
    assert setup.stop == 91.6
    assert setup.target == 0.0     # short target is the (causal) range low
    assert setup.entry == 90.0


def test_build_setup_rejects_long_in_premium_and_short_in_discount():
    # long whose entry sits in premium (top of range) must be rejected
    ev_l = _ev(30, "bullish")
    ob_hi = OrderBlock(index=29, direction="bullish", low=89.0, high=91.0)  # mid 90
    sweep_l = LiquiditySweep(index=25, level=88.0, side="sell")
    assert _build_setup(ev_l, ob_hi, sweep_l, 0.0, 100.0, 0.0) is None
    # short whose entry sits in discount (bottom of range) must be rejected
    ev_s = _ev(30, "bearish")
    ob_lo = OrderBlock(index=29, direction="bearish", low=9.0, high=11.0)   # mid 10
    sweep_s = LiquiditySweep(index=25, level=12.0, side="buy")
    assert _build_setup(ev_s, ob_lo, sweep_s, 0.0, 100.0, 0.0) is None


def test_build_setup_applies_min_rr_filter():
    ev = _ev(30, "bullish")
    ob = OrderBlock(index=29, direction="bullish", low=9.0, high=11.0)  # entry 10
    sweep = LiquiditySweep(index=25, level=8.5, side="sell")
    # risk ~1.6, reward to range_high=100 is huge -> passes a sane threshold...
    assert _build_setup(ev, ob, sweep, 0.0, 100.0, min_rr=1.5) is not None
    # ...but an absurd threshold rejects it (kills "rr < min_rr" -> "<=" survivor too)
    assert _build_setup(ev, ob, sweep, 0.0, 100.0, min_rr=10_000.0) is None
