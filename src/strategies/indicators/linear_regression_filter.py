from __future__ import annotations

from collections import deque
import math
from typing import Any, Sequence

import numpy as np
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from src.strategies.indicators.rolling_stats import sigmoid


class LinearRegressionFilter(Indicator):
    """
    Long-term Linear Regression Valuation Filter:
    - Calculates baseline intrinsic trend line: f(t) = alpha * t + beta
    - Standardized residuals (RMSE and Z_reg)
    - Strategic Target Points: Target Point(P) = f(t) + P * RMSE
    - Sigmoid Sizing: BP1 = 1 - Sigmoid(Z_reg), SP1 = Sigmoid(Z_reg)
    """

    def __init__(
        self,
        window: int | None = 5000,
        strategic_levels: Sequence[float] = (2.0, 1.144, 0.472, 0.0, -0.472, -1.144, -2.0),
        alpha: float | None = None,
        beta: float | None = None,
        rmse: float | None = None,
        expanding: bool = False,
    ):
        super().__init__([window if (window is not None and window > 0) else 0])
        self.window = window or 0
        self.expanding = expanding or (window is None) or (window <= 0)
        self.strategic_levels = tuple(strategic_levels)

        # Pre-fitted baseline parameters if provided
        self.fixed_alpha = alpha
        self.fixed_beta = beta
        self.fixed_rmse = rmse

        self._buffer: deque[float] = deque() if self.expanding else deque(maxlen=window)
        self.current_t: int = 0

        self.baseline_f: float = 0.0
        self.rmse: float = 0.0
        self.z_reg: float = 0.0
        self.bp: float = 0.5
        self.sp: float = 0.5
        self.target_points: dict[float, float] = {}

    @property
    def value(self) -> float:
        return self.z_reg

    def handle_bar(self, bar: Bar) -> None:
        self.update_raw(bar.close.as_double())

    def handle_quote_tick(self, tick: Any) -> None:
        pass

    def handle_trade_tick(self, tick: Any) -> None:
        pass

    def update_raw(self, price: float) -> None:
        self._buffer.append(price)
        self.current_t += 1

        if self.fixed_alpha is not None and self.fixed_beta is not None and self.fixed_rmse is not None:
            # Use pre-fitted baseline
            self.baseline_f = self.fixed_alpha * self.current_t + self.fixed_beta
            self.rmse = max(self.fixed_rmse, 1e-8)
            err = price - self.baseline_f
            self.z_reg = err / self.rmse
        else:
            # Dynamic rolling / expanding fit
            n = len(self._buffer)
            if n < 10:
                self.baseline_f = price
                self.rmse = 1.0
                self.z_reg = 0.0
            else:
                prices = np.array(self._buffer, dtype=np.float64)
                t = np.arange(n, dtype=np.float64)
                t_mean = np.mean(t)
                p_mean = np.mean(prices)
                t_dev = t - t_mean
                p_dev = prices - p_mean
                var_t = float(np.sum(t_dev**2))
                cov_tp = float(np.sum(t_dev * p_dev))

                slope = cov_tp / var_t if var_t > 0 else 0.0
                intercept = p_mean - slope * t_mean

                self.baseline_f = slope * (n - 1) + intercept
                residuals = prices - (slope * t + intercept)
                self.rmse = max(float(np.sqrt(np.mean(residuals**2))), 1e-8)
                self.z_reg = (price - self.baseline_f) / self.rmse

        sig = sigmoid(self.z_reg)
        self.bp = 1.0 - sig
        self.sp = sig

        self.target_points = {
            p: self.baseline_f + p * self.rmse for p in self.strategic_levels
        }

        self._set_has_inputs(True)
        init_threshold = 10 if self.expanding else min(self.window, 100)
        if len(self._buffer) >= init_threshold:
            self._set_initialized(True)
    def is_in_buy_zone(
        self,
        price: float,
        atr: float,
        tolerance_mult: float = 1.0,
        sma_filter: float | None = None,
    ) -> bool:
        """
        0 < price - Target Point <= tolerance_mult * ATR
        Checks against any strategic target level with P <= 0.
        If sma_filter is provided: requires sma_filter > Target Point to prevent buying downtrends/chasing.
        """
        for p, target in self.target_points.items():
            if p <= 0.0:
                dist = price - target
                if 0.0 < dist <= tolerance_mult * atr:
                    if sma_filter is not None and sma_filter <= target:
                        continue
                    return True
        return False

    def is_in_sell_zone(
        self,
        price: float,
        atr: float,
        tolerance_mult: float = 1.0,
        sma_filter: float | None = None,
    ) -> bool:
        """
        -tolerance_mult * ATR <= price - Target Point < 0
        Checks against any strategic target level with P >= 0.
        If sma_filter is provided: requires sma_filter < Target Point to prevent selling uptrends.
        """
        for p, target in self.target_points.items():
            if p >= 0.0:
                dist = price - target
                if -tolerance_mult * atr <= dist < 0.0:
                    if sma_filter is not None and sma_filter >= target:
                        continue
                    return True
        return False

    def _reset(self) -> None:
        self._buffer.clear()
        self.current_t = 0
        self.baseline_f = 0.0
        self.rmse = 0.0
        self.z_reg = 0.0
        self.bp = 0.5
        self.sp = 0.5
        self.target_points.clear()
