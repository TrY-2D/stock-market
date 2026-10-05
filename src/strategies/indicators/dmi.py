from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class DirectionalMovementIndex(Indicator):
    """
    Standard Directional Movement Index (DMI) and Average Directional Index (ADX)
    with Wilder's smoothing and trend exhaustion / peak detection logic.
    """

    def __init__(
        self,
        period: int = 14,
        adx_period: int = 14,
        adx_peak_threshold: float = 35.0,
    ):
        super().__init__([period, adx_period])
        self.period = period
        self.adx_period = adx_period
        self.adx_peak_threshold = adx_peak_threshold

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
