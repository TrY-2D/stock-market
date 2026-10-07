from __future__ import annotations

from collections import deque
import math
from typing import Any

import numpy as np
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

class DirectionalMovementIndex(Indicator):
    """
    Directional Movement Index (DMI) & Average Directional Index (ADX)
    with Wilder's smoothing, trend exhaustion peak detection, and an
    Adaptive Trend Filter (T_t).

    Mathematical Framework
    ----------------------
    1. Instantaneous Raw Trend:
        x_t = DI+_t - DI-_t
        - x_t > 0 : Bullish
        - x_t < 0 : Bearish
        - |x_t|   : Degree of divergence between buyers and sellers.

    2. ADX as Trend Confidence:
        ADX measures trend conviction/strength regardless of direction.

    3. Dynamic Alpha and Half-life:
        - Mode 'half_life' (recommended):
            HL_t = HL_base * (30 / ADX_t)
            alpha_t = 1 - 2^(-1 / HL_t)
        - Mode 'soft':
            alpha_t = ADX_t / (ADX_t + C)
        - Mode 'simple':
            alpha_t = ADX_t / 100

    4. Adaptive Trend Filter:
        T_t = alpha_t * x_t + (1 - alpha_t) * T_{t-1}
        - ADX low  -> small alpha -> slow trend decay (filters noise in chop).
        - ADX high -> large alpha -> fast adaptation (captures strong momentum).
    """
    def __init__(
        self,
        period: int = 14,
        adx_period: int = 14,
        adx_peak_threshold: float = 35.0,
        hl_base: float = 7.0,
        soft_c: float = 25.0,
        alpha_mode: str = "half_life",
    ):
        super().__init__([period, adx_period])
        self.period = period
        self.adx_period = adx_period
        self.adx_peak_threshold = adx_peak_threshold
        self.hl_base = float(hl_base)
        self.soft_c = float(soft_c)
        self.alpha_mode = alpha_mode
        # Current values
        self.plus_di: float = 0.0
        self.minus_di: float = 0.0
        self.dx: float = 0.0
        self.adx: float = 0.0

        # Previous values for crossover detection
        self.prev_plus_di: float = 0.0
        self.prev_minus_di: float = 0.0
        self.prev_adx: float = 0.0

        # Peaking detection state
        self.adx_peak_detected: bool = False
        self.adx_peak_val: float = 0.0
        self._adx_history: deque[float] = deque(maxlen=20)
        self._minus_di_history: deque[float] = deque(maxlen=10)
        self._plus_di_history: deque[float] = deque(maxlen=10)


        # Adaptive Trend Filter state
        self.trend_score: float = 0.0
        self.prev_trend_score: float = 0.0
        self.trend_alpha: float = 0.0
        self.half_life: float = 0.0
        self._trend_initialized: bool = False
        self._trend_history: deque[float] = deque(maxlen=50)
        # Internal Wilder smoothing variables
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._prev_close: float | None = None

        self._smoothed_tr: float = 0.0
        self._smoothed_plus_dm: float = 0.0
        self._smoothed_minus_dm: float = 0.0

        self._dx_history: list[float] = []
        self._count: int = 0

    @property
    def value(self) -> float:
        """Default indicator value is ADX."""
        return self.adx


    @property
    def raw_trend(self) -> float:
        """Instantaneous raw trend x_t = +DI - -DI."""
        return self.plus_di - self.minus_di

    @property
    def trend(self) -> float:
        """Alias for adaptive trend score T_t."""
        return self.trend_score

    @property
    def is_bullish(self) -> bool:
        """True if adaptive trend score T_t > 0."""
        return self.trend_score > 0.0

    @property
    def is_bearish(self) -> bool:
        """True if adaptive trend score T_t < 0."""
        return self.trend_score < 0.0

    @property
    def trend_strength(self) -> float:
        """Absolute value of adaptive trend score: |T_t|."""
        return abs(self.trend_score)

    def compute_alpha(self, adx_val: float, mode: str | None = None) -> tuple[float, float]:
        """
        Computes (alpha, half_life) from ADX according to the configured mode.

        Parameters
        ----------
        adx_val : float
            Current ADX value.
        mode : str | None
            'half_life', 'soft', or 'simple'. Defaults to self.alpha_mode.

        Returns
        -------
        tuple[float, float]
            (alpha_t, half_life_t)
        """
        mode = mode or self.alpha_mode
        adx_clamped = max(float(adx_val), 1e-4)

        if mode == "half_life":
            hl = self.hl_base * (30.0 / adx_clamped)
            hl = max(hl, 1e-4)
            alpha = 1.0 - math.pow(2.0, -1.0 / hl)
        elif mode == "soft":
            alpha = adx_clamped / (adx_clamped + self.soft_c)
            denom = max(1.0 - alpha, 1e-12)
            hl = math.log(2.0) / (-math.log(denom))
        elif mode == "simple":
            alpha = min(max(adx_clamped / 100.0, 0.0), 1.0)
            denom = max(1.0 - alpha, 1e-12)
            hl = math.log(2.0) / (-math.log(denom)) if alpha < 1.0 else 0.0
        else:
            raise ValueError(f"Unknown alpha_mode '{mode}', expected 'half_life', 'soft', or 'simple'")

        alpha = min(max(alpha, 1e-6), 1.0 - 1e-6)
        return alpha, hl
    def handle_bar(self, bar: Bar) -> None:
        high = bar.high.as_double()
        low = bar.low.as_double()
        close = bar.close.as_double()
        self.update_raw(high, low, close)

    def handle_quote_tick(self, tick: Any) -> None:
        pass

    def handle_trade_tick(self, tick: Any) -> None:
        pass

    def update_raw(self, high: float, low: float, close: float) -> None:
        if self._prev_high is None:
            self._prev_high = high
            self._prev_low = low
            self._prev_close = close
            return

        tr = max(
            high - low,
            abs(high - self._prev_close),
            abs(low - self._prev_close),
        )

        up_move = high - self._prev_high
        down_move = self._prev_low - low

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        self._prev_high = high
        self._prev_low = low
        self._prev_close = close
        self._count += 1

        self.prev_plus_di = self.plus_di
        self.prev_minus_di = self.minus_di
        self.prev_adx = self.adx
        self.prev_trend_score = self.trend_score
        # Initial accumulation phase
        if self._count <= self.period:
            self._smoothed_tr += tr
            self._smoothed_plus_dm += plus_dm
            self._smoothed_minus_dm += minus_dm

            if self._count == self.period:
                self.plus_di = 100.0 * (self._smoothed_plus_dm / self._smoothed_tr) if self._smoothed_tr > 0 else 0.0
                self.minus_di = 100.0 * (self._smoothed_minus_dm / self._smoothed_tr) if self._smoothed_tr > 0 else 0.0
                di_sum = self.plus_di + self.minus_di
                self.dx = 100.0 * abs(self.plus_di - self.minus_di) / di_sum if di_sum > 0 else 0.0
                self._dx_history.append(self.dx)
        else:
            # Wilder's Smoothing
            self._smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self.period) + tr
            self._smoothed_plus_dm = self._smoothed_plus_dm - (self._smoothed_plus_dm / self.period) + plus_dm
            self._smoothed_minus_dm = self._smoothed_minus_dm - (self._smoothed_minus_dm / self.period) + minus_dm

            self.plus_di = 100.0 * (self._smoothed_plus_dm / self._smoothed_tr) if self._smoothed_tr > 0 else 0.0
            self.minus_di = 100.0 * (self._smoothed_minus_dm / self._smoothed_tr) if self._smoothed_tr > 0 else 0.0
            di_sum = self.plus_di + self.minus_di
            self.dx = 100.0 * abs(self.plus_di - self.minus_di) / di_sum if di_sum > 0 else 0.0

            if len(self._dx_history) < self.adx_period:
                self._dx_history.append(self.dx)
                if len(self._dx_history) == self.adx_period:
                    self.adx = float(np.mean(self._dx_history))
                    self._set_has_inputs(True)
                    self._set_initialized(True)
            else:
                self.adx = (self.adx * (self.adx_period - 1) + self.dx) / self.adx_period
                self._set_has_inputs(True)
                self._set_initialized(True)

        # Track histories
        self._adx_history.append(self.adx)
        self._minus_di_history.append(self.minus_di)
        self._plus_di_history.append(self.plus_di)

        # ADX Peak Detection
        self._check_adx_peak()

        # -------------------------------------------------------------
        # Adaptive Trend Filter (T_t)
        # -------------------------------------------------------------
        if self.initialized:
            self.trend_alpha, self.half_life = self.compute_alpha(self.adx)
            if not self._trend_initialized:
                self.trend_score = self.raw_trend
                self._trend_initialized = True
            else:
                self.trend_score = (
                    self.trend_alpha * self.raw_trend
                    + (1.0 - self.trend_alpha) * self.trend_score
                )
            self._trend_history.append(self.trend_score)
        else:
            self.trend_score = self.raw_trend

    def _check_adx_peak(self) -> None:
        """
        Detects if ADX has exceeded threshold and begun sụt giảm (turning downward).
        """
        if len(self._adx_history) < 3:
            return

        recent_max = max(self._adx_history)
        current = self._adx_history[-1]
        prev = self._adx_history[-2]

        if recent_max >= self.adx_peak_threshold:
            if current < prev:
                self.adx_peak_detected = True
                self.adx_peak_val = recent_max
            elif current >= self.adx_peak_val:
                # If ADX makes a new high, reset peak until it turns down again
                self.adx_peak_detected = False
                self.adx_peak_val = current
        else:
            if current < 25.0:
                self.adx_peak_detected = False
                self.adx_peak_val = 0.0

    # -------------------------------------------------------------
    # Buy Tranche Trigger Conditions
    # -------------------------------------------------------------

    def is_minus_di_cooling(self, bars_count: int = 2) -> bool:
        """Đợt 1 Buy: -DI hạ nhiệt, sụt giảm liên tiếp."""
        if len(self._minus_di_history) < bars_count + 1:
            return False
        for i in range(1, bars_count + 1):
            if self._minus_di_history[-i] >= self._minus_di_history[-i - 1]:
                return False
        return True

    def is_minus_di_crossed_below_adx(self) -> bool:
        """Đợt 2 Buy: -DI cắt xuống dưới đường ADX (khi ADX đã peaked)."""
        cross_down = (self.prev_minus_di >= self.prev_adx) and (self.minus_di < self.adx)
        return cross_down and self.adx_peak_detected

    def is_plus_di_crossed_above_minus_di(self) -> bool:
        """Đợt 3 Buy: +DI cắt lên trên -DI."""
        return (self.prev_plus_di <= self.prev_minus_di) and (self.plus_di > self.minus_di)

    def is_plus_di_crossed_above_adx(self) -> bool:
        """Đợt 4 Buy: +DI cắt lên trên đường ADX."""
        return (self.prev_plus_di <= self.prev_adx) and (self.plus_di > self.adx)

    # -------------------------------------------------------------
    # Sell Tranche Trigger Conditions
    # -------------------------------------------------------------

    def is_plus_di_cooling(self, bars_count: int = 2) -> bool:
        """Đợt 1 Sell: +DI hạ nhiệt, sụt giảm liên tiếp."""
        if len(self._plus_di_history) < bars_count + 1:
            return False
        for i in range(1, bars_count + 1):
            if self._plus_di_history[-i] >= self._plus_di_history[-i - 1]:
                return False
        return True

    def is_plus_di_crossed_below_adx(self) -> bool:
        """Đợt 2 Sell: +DI cắt xuống dưới đường ADX (khi ADX đã peaked)."""
        cross_down = (self.prev_plus_di >= self.prev_adx) and (self.plus_di < self.adx)
        return cross_down and self.adx_peak_detected

    def is_minus_di_crossed_above_plus_di(self) -> bool:
        """Đợt 3 Sell: -DI cắt lên trên +DI."""
        return (self.prev_minus_di <= self.prev_plus_di) and (self.minus_di > self.plus_di)

    def is_minus_di_crossed_above_adx(self) -> bool:
        """Đợt 4 Sell: -DI cắt lên trên đường ADX."""
        return (self.prev_minus_di <= self.prev_adx) and (self.minus_di > self.adx)


    # -------------------------------------------------------------
    # Adaptive Trend Filter Crossover Conditions
    # -------------------------------------------------------------

    def is_trend_bullish_cross(self) -> bool:
        """Adaptive trend score T_t cắt lên trên 0 (chuyển từ bearish sang bullish)."""
        return (self.prev_trend_score <= 0.0) and (self.trend_score > 0.0)

    def is_trend_bearish_cross(self) -> bool:
        """Adaptive trend score T_t cắt xuống dưới 0 (chuyển từ bullish sang bearish)."""
        return (self.prev_trend_score >= 0.0) and (self.trend_score < 0.0)
    def _reset(self) -> None:
        self.plus_di = 0.0
        self.minus_di = 0.0
        self.dx = 0.0
        self.adx = 0.0
        self.adx_peak_detected = False
        self.adx_peak_val = 0.0
        self._adx_history.clear()
        self._minus_di_history.clear()
        self._plus_di_history.clear()
        self._dx_history.clear()
        self._count = 0
        self._prev_high = None
        self._prev_low = None
        self._prev_close = None
        self._smoothed_tr = 0.0
        self._smoothed_plus_dm = 0.0
        self._smoothed_minus_dm = 0.0
        self.trend_score = 0.0
        self.prev_trend_score = 0.0
        self.trend_alpha = 0.0
        self.half_life = 0.0
        self._trend_initialized = False
        self._trend_history.clear()
