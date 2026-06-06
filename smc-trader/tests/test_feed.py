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


def test_column_aliases_are_case_insensitive_and_varied():
    rows = [{"T": "5", "O": "10", "H": "12", "L": "9", "Adj Close": "11", "Vol": "7"}]
    candles = rows_to_candles(rows)
    assert len(candles) == 1
    c = candles[0]
    assert (c.time, c.open, c.high, c.low, c.close, c.volume) == (5, 10.0, 12.0, 9.0, 11.0, 7.0)


def test_missing_or_bad_time_falls_back_to_row_index():
    rows = [
        {"open": "10", "high": "12", "low": "9", "close": "11"},                  # no time -> idx 0
        {"time": "oops", "open": "10", "high": "12", "low": "9", "close": "11"},  # bad -> idx 1
    ]
    candles = rows_to_candles(rows)
    assert [c.time for c in candles] == [0, 1]


def test_float_time_is_truncated_to_int():
    rows = [{"time": "1700.9", "open": "1", "high": "2", "low": "0.5", "close": "1.5"}]
    assert rows_to_candles(rows)[0].time == 1700


def test_bad_volume_defaults_to_zero():
    rows = [{"time": "1", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "NaNish"}]
    assert rows_to_candles(rows)[0].volume == 0.0


def test_row_missing_required_ohlc_is_skipped():
    rows = [{"time": "1", "open": "1", "high": "2", "low": "0.5"}]   # no close -> skip
    assert rows_to_candles(rows) == []


def test_empty_rows_and_empty_csv(tmp_path: Path):
    assert rows_to_candles([]) == []
    p = tmp_path / "empty.csv"
    p.write_text("time,open,high,low,close\n", encoding="utf-8")
    assert load_csv(p) == []


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
