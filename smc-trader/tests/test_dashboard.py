import json
import re

from smctrader.bot import SMCBot
from smctrader.dashboard import build_dashboard, build_live_dashboard, build_model


def test_model_has_all_overlays():
    candles = SMCBot().load_synthetic(seed=7, n=240)
    m = build_model(candles)
    assert m["candles"] and len(m["candles"]) == 240
    for key in ("order_blocks", "fvgs", "sweeps", "structure", "setups", "stats"):
        assert key in m
    assert 0.0 <= m["stats"]["win_rate"] <= 1.0


def test_dashboard_is_self_contained_html():
    html = SMCBot().dashboard(SMCBot().load_synthetic(seed=7, n=120))
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "/*__DATA__*/" not in html       # placeholder substituted
    assert "cdn" not in html.lower()        # no external libraries
    m = re.search(r"const DATA = (\{.*?\});", html, re.S)
    assert m is not None and isinstance(json.loads(m.group(1)), dict)


def test_dashboard_handles_short_series():
    html = build_dashboard(SMCBot().load_synthetic(seed=1, n=12))
    assert "<!DOCTYPE html>" in html


def test_live_dashboard_is_self_contained_and_placeholder_free():
    html = build_live_dashboard(symbol="ETHUSDT", interval="4h", limit=250)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    # every placeholder substituted
    for ph in ("__SYMBOL__", "__INTERVAL__", "__LIMIT__"):
        assert ph not in html
    assert "cdn" not in html.lower()          # no external JS libraries
    assert 'value="ETHUSDT"' in html          # symbol wired in
    assert "limit=250" in html                # limit wired into fetch URL


def test_live_dashboard_pulls_live_data_no_baked_candles():
    html = build_live_dashboard()
    # fetches LIVE klines from Binance public API (with a fallback host)
    assert "/api/v3/klines?symbol=" in html
    assert "api.binance.com" in html
    assert "data-api.binance.vision" in html
    # SMC detection mirrored client-side
    for fn in ("function swings", "function structure", "function orderBlocks",
               "function fvgs", "function sweeps", "function analyze"):
        assert fn in html
    # nothing is baked in: no embedded candle dataset like the static dashboard
    assert "const DATA = {" not in html
    assert "/*__DATA__*/" not in html


def test_bot_live_dashboard_wired():
    html = SMCBot().live_dashboard(symbol="SOLUSDT", interval="15m")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert 'value="SOLUSDT"' in html
