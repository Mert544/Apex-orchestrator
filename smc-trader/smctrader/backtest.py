"""Walk-forward backtest of SMC setups over a candle series."""


from dataclasses import dataclass, field

from .candles import Candle
from .risk import position_size
from .signals import TradeSetup, generate_setups


@dataclass
class TradeOutcome:
    setup: TradeSetup
    result: str   # "win" | "loss" | "open"
    r: float


@dataclass
class BacktestReport:
    trades: list[TradeOutcome] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    end_balance: float = 0.0

    @property
    def win_rate(self) -> float:
        closed = self.wins + self.losses
        return round(self.wins / closed, 4) if closed else 0.0


def _resolve(candles: list[Candle], setup: TradeSetup) -> str:
    """Did target or stop get hit first after the setup formed?"""
    for c in candles[setup.index + 1:]:
        if setup.direction == "long":
            if c.low <= setup.stop:
                return "loss"
            if c.high >= setup.target:
                return "win"
        else:
            if c.high >= setup.stop:
                return "loss"
            if c.low <= setup.target:
                return "win"
    return "open"


def backtest(candles: list[Candle], balance: float = 10000.0,
             risk_pct: float = 1.0, min_rr: float = 1.5) -> BacktestReport:
    """Generate setups, resolve each against future candles, and tally R + equity."""
    report = BacktestReport(end_balance=balance)
    for setup in generate_setups(candles, min_rr=min_rr):
        outcome = _resolve(candles, setup)
        size = position_size(report.end_balance, risk_pct, setup.entry, setup.stop)
        if outcome == "win":
            r = setup.rr
            report.wins += 1
            report.end_balance += size * abs(setup.target - setup.entry)
        elif outcome == "loss":
            r = -1.0
            report.losses += 1
            report.end_balance -= size * abs(setup.entry - setup.stop)
        else:
            r = 0.0
        report.total_r = round(report.total_r + r, 4)
        report.trades.append(TradeOutcome(setup, outcome, r))
    report.end_balance = round(report.end_balance, 2)
    return report
