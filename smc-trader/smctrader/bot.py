"""SMCBot — orchestrates the full Smart Money Concepts analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backtest import BacktestReport, backtest
from .candles import Candle
from .dashboard import build_dashboard
from .data import synthetic_candles
from .feed import load_csv
from .fvg import find_fvgs
from .liquidity import equal_levels, find_sweeps
from .order_blocks import find_order_blocks
from .power_of_three import analyze_po3
from .sessions import killzone
from .signals import generate_setups
from .structure import current_trend, market_structure


@dataclass
class Analysis:
    trend: str
    structure_events: int
    order_blocks: int
    fvgs: int
    liquidity_pools: int
    sweeps: int
    setups: int
    po3_direction: str
    report: BacktestReport = field(default=None)  # type: ignore[assignment]


class SMCBot:
    """Run the SMC/ICT pipeline over a candle series (or synthetic data)."""

    def __init__(self, risk_pct: float = 1.0, min_rr: float = 1.5) -> None:
        self.risk_pct = risk_pct
        self.min_rr = min_rr

    def load_synthetic(self, seed: int = 7, n: int = 240) -> list[Candle]:
        """A deterministic offline candle series for demos/backtests."""
        return synthetic_candles(seed=seed, n=n)

    def load_csv(self, path: str) -> list[Candle]:
        """Load real OHLC candles from a CSV file (open/high/low/close[/volume])."""
        return load_csv(path)

    def analyze(self, candles: list[Candle]) -> Analysis:
        """Full read of the chart: structure, blocks, gaps, liquidity, PO3, setups."""
        po3 = analyze_po3(candles)
        report = backtest(candles, risk_pct=self.risk_pct, min_rr=self.min_rr)
        return Analysis(
            trend=current_trend(candles),
            structure_events=len(market_structure(candles)),
            order_blocks=len(find_order_blocks(candles)),
            fvgs=len(find_fvgs(candles)),
            liquidity_pools=len(equal_levels(candles)),
            sweeps=len(find_sweeps(candles)),
            setups=len(generate_setups(candles, min_rr=self.min_rr)),
            po3_direction=po3.distribution_direction,
            report=report,
        )

    def dashboard(self, candles: list[Candle]) -> str:
        """Render a self-contained HTML chart with the SMC analysis + backtest."""
        return build_dashboard(candles, risk_pct=self.risk_pct, min_rr=self.min_rr)

    def summary(self, candles: list[Candle]) -> dict[str, Any]:
        """A compact dict report (handy for a CLI or JSON output)."""
        a = self.analyze(candles)
        return {
            "trend": a.trend,
            "structure_events": a.structure_events,
            "order_blocks": a.order_blocks,
            "fvgs": a.fvgs,
            "liquidity_pools": a.liquidity_pools,
            "sweeps": a.sweeps,
            "setups": a.setups,
            "po3_direction": a.po3_direction,
            "killzone_now": killzone(8),
            "trades": len(a.report.trades),
            "win_rate": a.report.win_rate,
            "total_r": a.report.total_r,
            "end_balance": a.report.end_balance,
        }
