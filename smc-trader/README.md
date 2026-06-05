# smc-trader

A **Smart Money Concepts / ICT** algorithmic trading bot — deterministic, offline,
and backtestable. It reads OHLC candles and applies the core SMC/ICT literature:

- **Market structure** — swing points, Break of Structure (BOS), Change of Character (CHoCH)
- **Order blocks** — last opposing candle before a displacement
- **Fair Value Gaps (FVG)** — 3-candle imbalances
- **Liquidity** — equal highs/lows (resting liquidity) + sweeps / stop hunts
- **Premium / Discount + OTE** — equilibrium and the 0.62–0.79 optimal trade entry
- **Power of Three** — accumulation → manipulation → distribution
- **Killzones** — Asian / London / New York session windows
- **Signals + risk + backtest** — combine the above into R-defined setups and tally results

## Quick start

```python
from smctrader.bot import SMCBot

bot = SMCBot(risk_pct=1.0, min_rr=1.5)
candles = bot.load_synthetic(seed=7, n=240)   # or supply your own list[Candle]
print(bot.summary(candles))
```

Built and hardened with [Apex](../README.md). Educational / research use — not financial advice.
