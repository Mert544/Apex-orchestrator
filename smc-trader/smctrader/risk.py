"""Position sizing and R-multiple risk math."""



def position_size(balance: float, risk_pct: float, entry: float, stop: float) -> float:
    """Units to trade so that hitting ``stop`` loses ``risk_pct`` of ``balance``."""
    per_unit = abs(entry - stop)
    if per_unit <= 0 or balance <= 0 or risk_pct <= 0:
        return 0.0
    risk_cash = balance * (risk_pct / 100.0)
    return round(risk_cash / per_unit, 6)


def r_multiple(entry: float, stop: float, target: float) -> float:
    """Reward-to-risk of a setup (target distance / stop distance)."""
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    return round(abs(target - entry) / risk, 4)
