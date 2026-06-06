import json
import re

from smctrader.bot import SMCBot
from smctrader.dashboard import build_dashboard, build_model


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
