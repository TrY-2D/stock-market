"""Quantitative Trading Strategies."""

from src.strategies.indicators import (
    CandlestickPatternDetector,
    CandlestickSignal,
    DirectionalMovementIndex,
    LinearRegressionChannel,
    MultivariateLinearRegression,
    RollingStatistics,
)
from src.strategies.nautilus_strategy import NautilusQuantitativeConfig, NautilusQuantitativeStrategy
from src.strategies.valuation import ExpectedReturnEngine, ValuationSnapshot

__all__ = [
    "CandlestickPatternDetector",
    "CandlestickSignal",
    "DirectionalMovementIndex",
    "ExpectedReturnEngine",
    "LinearRegressionChannel",
    "MultivariateLinearRegression",
    "NautilusQuantitativeConfig",
    "NautilusQuantitativeStrategy",
    "RollingStatistics",
    "ValuationSnapshot",
]
