"""smc-trader — a Smart Money Concepts / ICT algorithmic trading bot.

Implements the core ICT / Smart Money literature as deterministic detectors over
OHLC candle data: market structure (BOS/CHoCH), order blocks, fair value gaps,
liquidity pools and sweeps, premium/discount + OTE, the Power of Three model, and
session killzones — combined into trade setups, sized by risk, and backtested.

Offline and deterministic by default (synthetic data generator included); no
broker, no network. Educational / research use.
"""

__version__ = "0.1.0"
