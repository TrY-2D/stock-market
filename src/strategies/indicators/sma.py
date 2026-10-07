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
    Rolling / Expanding SMA Statistics.

    Core model
    ----------
    baseline:
        SMA(price)

    sma_diff:
        SMA(t) - SMA(t-1)

    G_SMA:
        sma_diff / price * scale_factor

    premium_discount:
        (SMA - price) / price

    premium:
        G_SMA + premium_discount

    model_uncertainty:
        STD / price

    z_score:
        (price - SMA) / STD

    Strategic target:
        target(P) = SMA + P * STD


    Interpretation
    --------------
    G_SMA
        Annualized trend velocity of the SMA relative to current price.

    premium_discount
        Mean-reversion component:
        positive when price is below SMA.

    premium
        Combined preliminary return potential.

    model_uncertainty
        Relative dispersion of price around the SMA.

        This is NOT financial leverage.
    """

    def __init__(
        self,
        window: int | None = 1500,
        strategic_levels: Sequence[float] = (
            2.0,
            1.144,
            0.472,
            0.0,
            -0.472,
            -1.144,
            -2.0,
        ),
        expanding: bool = False,
        scale_factor: float = 255.0,
    ):
        super().__init__(
            [
                window
                if (
                    window is not None
                    and window > 0
                )
                else 0
            ]
        )

        # ------------------------------------------------------------------
        # Configuration
        # ------------------------------------------------------------------

        self.window = window or 0

        self.expanding = (
            expanding
            or window is None
            or window <= 0
        )

        self.strategic_levels = tuple(
            strategic_levels
        )

        self.scale_factor = max(
            float(scale_factor),
            0.0,
        )

        # ------------------------------------------------------------------
        # Price buffer
        # ------------------------------------------------------------------

        self._buffer: deque[float] = (
            deque()
            if self.expanding
            else deque(maxlen=self.window)
        )

        # ------------------------------------------------------------------
        # SMA statistics
        # ------------------------------------------------------------------

        self.mean: float = 0.0

        self.std: float = 0.0

        self.z_score: float = 0.0

        # ------------------------------------------------------------------
        # SMA trend
        # ------------------------------------------------------------------

        self.previous_mean: float = 0.0

        self.sma_diff: float = 0.0

        self.sma_growth: float = 0.0

        # ------------------------------------------------------------------
        # Premium decomposition
        # ------------------------------------------------------------------

        self.premium_growth: float = 0.0

        self.premium_discount: float = 0.0

        self.premium: float = 0.0

        # ------------------------------------------------------------------
        # Model uncertainty
        # ------------------------------------------------------------------

        self.model_uncertainty: float = 0.0

        # ------------------------------------------------------------------
        # Buy / sell coefficients
        # ------------------------------------------------------------------

        self.bp: float = 0.5

        self.sp: float = 0.5

        # ------------------------------------------------------------------
        # Strategic target points
        # ------------------------------------------------------------------

        self.target_points: dict[float, float] = {}

    # ======================================================================
    # Public properties
    # ======================================================================

    @property
    def value(self) -> float:
        """Current SMA z-score."""
        return self.z_score

    @property
    def baseline(self) -> float:
        """Current SMA baseline."""
        return self.mean

    # ======================================================================
    # Data handling
    # ======================================================================

    def handle_bar(self, bar: Bar) -> None:
        self.update_raw(
            bar.close.as_double()
        )

    def handle_quote_tick(self, tick: Any) -> None:
        pass

    def handle_trade_tick(self, tick: Any) -> None:
        pass

    # ======================================================================
    # Main update
    # ======================================================================

    def update_raw(self, price: float) -> None:
        """
        Update rolling / expanding SMA statistics.
        """

        price = float(price)

        if not math.isfinite(price):
            return

        self._buffer.append(price)

        n = len(self._buffer)

        # ------------------------------------------------------------------
        # Minimum observations
        # ------------------------------------------------------------------

        min_required = (
            2
            if self.expanding
            else min(self.window, 30)
        )

        if n < min_required:
            return

        # ------------------------------------------------------------------
        # Price array
        # ------------------------------------------------------------------

        arr = np.asarray(
            self._buffer,
            dtype=np.float64,
        )

        # ------------------------------------------------------------------
        # Previous SMA
        #
        # Store the previous value before updating the current SMA.
        # ------------------------------------------------------------------

        previous_mean = self.mean

        # ------------------------------------------------------------------
        # SMA
        # ------------------------------------------------------------------

        self.mean = float(
            np.mean(arr)
        )

        self.previous_mean = (
            previous_mean
        )

        # ------------------------------------------------------------------
        # SMA difference
        # ------------------------------------------------------------------

        self.sma_diff = (
            self.mean
            - self.previous_mean
        )

        # ------------------------------------------------------------------
        # Standard deviation
        # ------------------------------------------------------------------

        self.std = float(
            np.std(
                arr,
                ddof=0,
            )
        )

        self.std = max(
            self.std,
            1e-8,
        )

        # ------------------------------------------------------------------
        # Z-score
        # ------------------------------------------------------------------

        self.z_score = (
            price - self.mean
        ) / self.std

        # ------------------------------------------------------------------
        # Derived metrics
        # ------------------------------------------------------------------

        self._update_sma_growth(price)

        self._update_premium(price)

        self._update_model_uncertainty(price)

        self._update_probability()

        self._update_target_points()

        # ------------------------------------------------------------------
        # Nautilus Trader state
        # ------------------------------------------------------------------

        self._set_has_inputs(True)

        if (
            self.expanding
            or n >= self.window
        ):
            self._set_initialized(True)

    # ======================================================================
    # SMA growth
    # ======================================================================

    def _update_sma_growth(
        self,
        price: float,
    ) -> None:
        """
        Calculate annualized SMA trend velocity.

            G_SMA =
                diff(SMA) / price * scale_factor

        Example for daily data:

            scale_factor = 255

        If:

            SMA(t-1) = 100
            SMA(t)   = 100.10
            price    = 100

        then:

            G_SMA
                = 0.10 / 100 * 255
                = 0.255

        i.e. approximately +25.5% annualized linear trend velocity.
        """

        price_safe = max(
            abs(price),
            1e-12,
        )

        self.sma_growth = (
            self.sma_diff
            / price_safe
            * self.scale_factor
        )

    # ======================================================================
    # Premium
    # ======================================================================

    def _update_premium(
        self,
        price: float,
    ) -> None:
        """
        Calculate preliminary return potential.

        Premium is decomposed into:

            premium_growth
                = G_SMA

            premium_discount
                = (SMA - price) / price

            premium
                = premium_growth + premium_discount
        """

        price_safe = max(
            abs(price),
            1e-12,
        )

        # ------------------------------------------------------------------
        # Trend component
        # ------------------------------------------------------------------

        self.premium_growth = (
            self.sma_growth
        )

        # ------------------------------------------------------------------
        # Mean-reversion / discount component
        # ------------------------------------------------------------------

        self.premium_discount = (
            self.mean - price
        ) / price_safe

        # ------------------------------------------------------------------
        # Combined premium
        # ------------------------------------------------------------------

        self.premium = (
            self.premium_growth
            + self.premium_discount
        )

    # ======================================================================
    # Model uncertainty
    # ======================================================================

    def _update_model_uncertainty(
        self,
        price: float,
    ) -> None:
        """
        Relative price dispersion around SMA.

            model_uncertainty = STD / price

        This is deliberately independent from premium.
        """

        price_safe = max(
            abs(price),
            1e-12,
        )

        self.model_uncertainty = (
            self.std
            / price_safe
        )

    # ======================================================================
    # Probability
    # ======================================================================

    def _update_probability(self) -> None:
        """
        Convert z-score into buy / sell coefficients.
        """

        sig = sigmoid(
            self.z_score
        )

        self.bp = 1.0 - sig
        self.sp = sig

    # ======================================================================
    # Strategic target points
    # ======================================================================

    def _update_target_points(self) -> None:
        """
        Target(P) = SMA + P * STD
        """

        self.target_points = {
            p: self.mean + p * self.std
            for p in self.strategic_levels
        }

    # ======================================================================
    # Buy zone
    # ======================================================================

    def is_in_buy_zone(
        self,
        price: float,
        atr: float,
        tolerance_mult: float = 0.5,
        sma_filter: float | None = None,
    ) -> bool:
        """
        Conditions:

            0 < price - target <= tolerance_mult * ATR

        Only P <= 0 levels are considered.

        Optional SMA filter:

            sma_filter > target
        """

        if atr < 0:
            return False

        tolerance = (
            float(tolerance_mult)
            * float(atr)
        )

        for p, target in self.target_points.items():
            if p <= 0.0:
                dist = price - target

                if (
                    0.0 < dist
                    <= tolerance
                ):
                    if (
                        sma_filter is not None
                        and sma_filter <= target
                    ):
                        continue

                    return True

        return False

    # ======================================================================
    # Sell zone
    # ======================================================================

    def is_in_sell_zone(
        self,
        price: float,
        atr: float,
        tolerance_mult: float = 0.5,
        sma_filter: float | None = None,
    ) -> bool:
        """
        Conditions:

            -tolerance_mult * ATR
                <= price - target < 0

        Only P >= 0 levels are considered.

        Optional SMA filter:

            sma_filter < target
        """

        if atr < 0:
            return False

        tolerance = (
            float(tolerance_mult)
            * float(atr)
        )

        for p, target in self.target_points.items():
            if p >= 0.0:
                dist = price - target

                if (
                    -tolerance
                    <= dist
                    < 0.0
                ):
                    if (
                        sma_filter is not None
                        and sma_filter >= target
                    ):
                        continue

                    return True

        return False

    # ======================================================================
    # Reset
    # ======================================================================

    def _reset(self) -> None:
        self._buffer.clear()

        # SMA
        self.mean = 0.0
        self.previous_mean = 0.0
        self.std = 0.0
        self.z_score = 0.0

        # SMA trend
        self.sma_diff = 0.0
        self.sma_growth = 0.0

        # Premium
        self.premium_growth = 0.0
        self.premium_discount = 0.0
        self.premium = 0.0

        # Model uncertainty
        self.model_uncertainty = 0.0

        # Probability
        self.bp = 0.5
        self.sp = 0.5

        # Targets
        self.target_points.clear()