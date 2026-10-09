"""Backtesting framework and engines for quantitative strategies."""

from src.backtest.dataset import generate_synthetic_strategy_dataset, load_strategy_dataset
from src.backtest.engine import BacktestResult, QuantitativeBacktestEngine, TradeRecord
from src.backtest.nautilus_runner import NautilusBacktestRunner

__all__ = [
    "BacktestResult",
    "NautilusBacktestRunner",
    "QuantitativeBacktestEngine",
    "TradeRecord",
    "generate_synthetic_strategy_dataset",
    "load_strategy_dataset",
]
