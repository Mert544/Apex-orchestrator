from smctrader.bot import SMCBot


def test_bot_runs_full_pipeline():
    bot = SMCBot()
    candles = bot.load_synthetic(seed=7, n=240)
    summary = bot.summary(candles)
    assert summary["structure_events"] >= 1
    assert summary["order_blocks"] >= 1
    assert isinstance(summary["end_balance"], float)
    assert 0.0 <= summary["win_rate"] <= 1.0
