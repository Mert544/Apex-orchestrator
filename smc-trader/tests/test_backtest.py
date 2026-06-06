from smctrader.backtest import backtest
from smctrader.data import synthetic_candles


def test_backtest_reports_consistent_stats():
    report = backtest(synthetic_candles(seed=7, n=240), balance=10000.0)
    assert 0.0 <= report.win_rate <= 1.0
    assert report.wins + report.losses <= len(report.trades)
    assert isinstance(report.end_balance, float)
    # win_rate matches wins/(wins+losses)
    closed = report.wins + report.losses
    if closed:
        assert abs(report.win_rate - report.wins / closed) < 1e-3


def test_backtest_is_deterministic():
    a = backtest(synthetic_candles(seed=7, n=240))
    b = backtest(synthetic_candles(seed=7, n=240))
    assert a.total_r == b.total_r and a.end_balance == b.end_balance
