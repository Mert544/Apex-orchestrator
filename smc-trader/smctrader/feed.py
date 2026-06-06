"""Load real OHLC candles from a CSV file (a simple data-feed adapter).

Accepts the common column names (case-insensitive): time/timestamp/date,
open/high/low/close, and an optional volume. Malformed rows are skipped so a
stray line never aborts a backtest. Deterministic and offline.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .candles import Candle

_ALIASES = {
    "time": ("time", "timestamp", "date", "datetime", "t"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "adj close", "adj_close"),
    "volume": ("volume", "vol", "v"),
}


def _pick(row: dict[str, str], field: str) -> str | None:
    for alias in _ALIASES[field]:
        for key, value in row.items():
            if key and key.strip().lower() == alias:
                return value
    return None


def rows_to_candles(rows: list[dict[str, str]]) -> list[Candle]:
    """Build candles from already-parsed CSV rows, skipping malformed ones."""
    candles: list[Candle] = []
    for i, row in enumerate(rows):
        try:
            o = float(_pick(row, "open"))    # type: ignore[arg-type]
            h = float(_pick(row, "high"))    # type: ignore[arg-type]
            low = float(_pick(row, "low"))   # type: ignore[arg-type]
            c = float(_pick(row, "close"))   # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        vol_raw = _pick(row, "volume")
        try:
            vol = float(vol_raw) if vol_raw not in (None, "") else 0.0
        except ValueError:
            vol = 0.0
        time_raw = _pick(row, "time")
        try:
            time = int(float(time_raw)) if time_raw not in (None, "") else i
        except ValueError:
            time = i
        candles.append(Candle(time=time, open=o, high=h, low=low, close=c, volume=vol))
    return candles


def load_csv(path: str | Path) -> list[Candle]:
    """Read an OHLC CSV (with a header row) into a list of Candle."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows_to_candles(rows)
