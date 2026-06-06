from pathlib import Path

from smctrader.feed import load_csv, rows_to_candles


def test_rows_to_candles_parses_and_skips_bad_rows():
    rows = [
        {"time": "1", "open": "10", "high": "12", "low": "9", "close": "11", "volume": "100"},
        {"time": "2", "open": "x", "high": "12", "low": "9", "close": "11"},   # bad open -> skip
        {"time": "3", "open": "11", "high": "13", "low": "10", "close": "12"}, # no volume -> 0
    ]
    candles = rows_to_candles(rows)
    assert len(candles) == 2
    assert candles[0].open == 10.0 and candles[0].close == 11.0 and candles[0].volume == 100.0
    assert candles[1].time == 3 and candles[1].volume == 0.0


def test_load_csv_roundtrip(tmp_path: Path):
    p = tmp_path / "ohlc.csv"
    p.write_text("Date,Open,High,Low,Close,Volume\n1,10,12,9,11,100\n2,11,13,10,12,150\n", encoding="utf-8")
    candles = load_csv(p)
    assert len(candles) == 2
    assert candles[0].high == 12.0 and candles[1].close == 12.0


def test_load_csv_feeds_the_bot(tmp_path: Path):
    from smctrader.bot import SMCBot
    p = tmp_path / "d.csv"
    lines = "\n".join(f"{i},{10+i%3},{12+i%3},{9+i%3},{11+i%3}" for i in range(30))
    p.write_text("time,open,high,low,close\n" + lines + "\n", encoding="utf-8")
    bot = SMCBot()
    candles = bot.load_csv(str(p))
    assert len(candles) == 30
    summary = bot.summary(candles)
    assert "structure_events" in summary
