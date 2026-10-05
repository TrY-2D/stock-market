from __future__ import annotations

from collections import deque
import math
from typing import Any, Sequence

import numpy as np
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


def sigmoid(z: float) -> float:
    """Stable sigmoid function."""
    if z >= 40.0:
        return 1.0
    if z <= -40.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


class RollingStatistics(Indicator):
    """
    Rolling window statistics calculator (Mean, Standard Deviation, Z-Score,
    Strategic Target Points, and Sigmoid allocation coefficients).
    """

    def __init__(
        self,
        window: int | None = 1500,
        strategic_levels: Sequence[float] = (2.0, 1.144, 0.472, 0.0, -0.472, -1.144, -2.0),
        expanding: bool = False,
    ):
        super().__init__([window if (window is not None and window > 0) else 0])
        self.window = window or 0
        self.expanding = expanding or (window is None) or (window <= 0)
        self.strategic_levels = tuple(strategic_levels)

        self._buffer: deque[float] = deque() if self.expanding else deque(maxlen=window)
        self.mean: float = 0.0
        self.std: float = 0.0
        self.z_score: float = 0.0
        self.bp: float = 0.5  # Buy position coefficient: 1 - Sigmoid(Z)
        self.sp: float = 0.5  # Sell position coefficient: Sigmoid(Z)
        self.target_points: dict[float, float] = {}

    @property
    def value(self) -> float:
        return self.z_score

    def handle_bar(self, bar: Bar) -> None:
        self.update_raw(bar.close.as_double())

    def handle_quote_tick(self, tick: Any) -> None:
        pass

    def handle_trade_tick(self, tick: Any) -> None:
        pass

    def update_raw(self, price: float) -> None:
        self._buffer.append(price)

        min_required = 2 if self.expanding else min(self.window, 30)
        if len(self._buffer) >= min_required:
            # Calculate rolling or expanding mean and std
            arr = np.array(self._buffer, dtype=np.float64)
            self.mean = float(np.mean(arr))
            self.std = float(np.std(arr))
            if self.std <= 1e-8:
                self.std = 1e-8

            self.z_score = (price - self.mean) / self.std

            # Sigmoid weights
            sig = sigmoid(self.z_score)
            self.bp = 1.0 - sig
            self.sp = sig

            # Calculate target points for each strategic level P
            self.target_points = {
                p: self.mean + p * self.std for p in self.strategic_levels
            }

            self._set_has_inputs(True)
            if self.expanding or len(self._buffer) >= self.window:
                self._set_initialized(True)
    def is_in_buy_zone(
        self,
        price: float,
        atr: float,
        tolerance_mult: float = 0.5,
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
        tolerance_mult: float = 0.5,
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
        self.mean = 0.0
        self.std = 0.0
        self.z_score = 0.0
        self.bp = 0.5
        self.sp = 0.5
        self.target_points.clear()
