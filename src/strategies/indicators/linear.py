from __future__ import annotations

from collections import deque
from typing import Any, Sequence

import math
import numpy as np

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class LinearRegressionChannel(Indicator):
    """
    Linear Regression Channel with sample-size shrinkage.

    Core model
    ----------
    Raw OLS:
        y = raw_slope * x + raw_intercept

    Shrinkage:
        weight = n / (n + k)

    Adjusted model:
        y_adj = mean + weight * (raw_slope * x + raw_intercept - mean)

    Therefore:
        adjusted_slope     = raw_slope * weight
        adjusted_intercept = mean + weight * (raw_intercept - mean)

    When n is small:
        weight -> 0
        model -> mean

    When n becomes large:
        weight -> 1
        model -> OLS

    Premium
    -------
        premium_growth   = slope / price
        premium_discount = (baseline - price) / price
        premium           = premium_growth + premium_discount

    Equivalent:
        premium = (slope + baseline - price) / price

    Model uncertainty
    -----------------
        model_uncertainty = RMSE / price

    Note:
        This measures the relative uncertainty / dispersion of the
        regression model compared with the current price.

    z_reg
    -----
        z_reg = (price - baseline) / RMSE

    Strategic targets
    -----------------
        target(P) = baseline + P * RMSE
    """

    def __init__(
        self,
        window: int | None = None,
        strategic_levels: Sequence[float] = (
            2.0,
            1.144,
            0.472,
            0.0,
            -0.472,
            -1.144,
            -2.0,
        ),
        alpha: float | None = None,
        beta: float | None = None,
        rmse: float | None = None,
        k: float = 10.0,
    ):
        super().__init__(
            [window if (window is not None and window > 0) else 0]
        )

        self.window = window or 2
        self.strategic_levels = tuple(strategic_levels)

        # ------------------------------------------------------------------
        # Configuration
        # ------------------------------------------------------------------

        self.fixed_alpha = alpha
        self.fixed_beta = beta
        self.fixed_rmse = rmse

        # Shrinkage strength.
        #
        # k = 10 gives:
        #   n=2   -> 0.167
        #   n=10  -> 0.500
        #   n=50  -> 0.833
        #   n=100 -> 0.909
        self.k = max(float(k), 0.0)

        # ------------------------------------------------------------------
        # Price buffer
        # ------------------------------------------------------------------

        if window is None or window <= 0:
            # Expanding window.
            self._buffer: deque[float] = deque()
            self.expanding = True
        else:
            # Rolling window.
            self._buffer = deque(maxlen=self.window)
            self.expanding = False

        self.current_t: int = 0

        # ------------------------------------------------------------------
        # Regression state
        # ------------------------------------------------------------------

        self.raw_slope: float = 0.0
        self.raw_intercept: float = 0.0

        self.slope: float = 0.0
        self.intercept: float = 0.0

        self.mean: float = 0.0
        self.weight: float = 0.0

        self.baseline_f: float = 0.0

        # ------------------------------------------------------------------
        # Regression uncertainty
        # ------------------------------------------------------------------

        self.rmse: float = 0.0
        self.model_uncertainty: float = 0.0
        self.z_reg: float = 0.0

        # ------------------------------------------------------------------
        # Premium decomposition
        # ------------------------------------------------------------------

        self.premium_growth: float = 0.0
        self.premium_discount: float = 0.0
        self.premium: float = 0.0

        # ------------------------------------------------------------------
        # Buy / sell probabilities
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
        """Regression z-score."""
        return self.z_reg

    # ----------------------------------------------------------------------
    # Aliases
    # ----------------------------------------------------------------------

    @property
    def baseline(self) -> float:
        """Current regression baseline."""
        return self.baseline_f

    # ======================================================================
    # Data handling
    # ======================================================================

    def handle_bar(self, bar: Bar) -> None:
        self.update_raw(bar.close.as_double())

    def handle_quote_tick(self, tick: Any) -> None:
        pass

    def handle_trade_tick(self, tick: Any) -> None:
        pass

    # ======================================================================
    # Main calculation
    # ======================================================================

    def update_raw(self, price: float) -> None:
        price = float(price)

        if not math.isfinite(price):
            return

        self._buffer.append(price)
        self.current_t += 1

        n = len(self._buffer)

        # ==================================================================
        # Fixed / pre-fitted regression
        # ==================================================================

        if (
            self.fixed_alpha is not None
            and self.fixed_beta is not None
            and self.fixed_rmse is not None
        ):
            self._update_fixed_model(price)

        # ==================================================================
        # Dynamic regression
        # ==================================================================

        else:
            self._update_dynamic_model(price)

        # ==================================================================
        # Derived metrics
        # ==================================================================

        self._update_premium(price)
        self._update_probability()
        self._update_target_points()

        # ==================================================================
        # Nautilus Trader state
        # ==================================================================

        self._set_has_inputs(True)

        init_threshold = (
            2
            if self.expanding
            else min(self.window, 100)
        )

        if n >= init_threshold:
            self._set_initialized(True)

    # ======================================================================
    # Fixed model
    # ======================================================================

    def _update_fixed_model(self, price: float) -> None:
        """
        Update using externally supplied regression parameters.

        The fixed model is assumed to already represent the desired
        long-term regression, so no sample-size shrinkage is applied.
        """

        self.raw_slope = float(self.fixed_alpha)
        self.raw_intercept = float(self.fixed_beta)

        self.slope = self.raw_slope
        self.intercept = self.raw_intercept

        self.mean = self.slope * self.current_t + self.intercept

        self.weight = 1.0

        self.baseline_f = (
            self.slope * self.current_t
            + self.intercept
        )

        self.rmse = max(
            abs(float(self.fixed_rmse)),
            1e-12,
        )

        self.z_reg = (
            price - self.baseline_f
        ) / self.rmse

    # ======================================================================
    # Dynamic model
    # ======================================================================

    def _update_dynamic_model(self, price: float) -> None:
        """
        Calculate OLS and apply sample-size shrinkage.
        """

        prices = np.asarray(
            self._buffer,
            dtype=np.float64,
        )

        n = len(prices)

        # ------------------------------------------------------------------
        # Not enough data for a meaningful regression.
        #
        # We still maintain a valid state instead of producing NaN.
        # ------------------------------------------------------------------

        if n < 2:
            self.raw_slope = 0.0
            self.raw_intercept = price

            self.slope = 0.0
            self.intercept = price

            self.mean = price
            self.weight = 0.0

            self.baseline_f = price

            self.rmse = 1e-12
            self.z_reg = 0.0

            return

        # ------------------------------------------------------------------
        # Independent variable
        # ------------------------------------------------------------------

        t = np.arange(
            n,
            dtype=np.float64,
        )

        t_mean = float(np.mean(t))
        p_mean = float(np.mean(prices))

        t_dev = t - t_mean
        p_dev = prices - p_mean

        # ------------------------------------------------------------------
        # OLS
        # ------------------------------------------------------------------

        var_t = float(
            np.sum(t_dev * t_dev)
        )

        cov_tp = float(
            np.sum(t_dev * p_dev)
        )

        if var_t > 0.0:
            raw_slope = cov_tp / var_t
        else:
            raw_slope = 0.0

        raw_intercept = (
            p_mean
            - raw_slope * t_mean
        )

        self.raw_slope = raw_slope
        self.raw_intercept = raw_intercept

        # ------------------------------------------------------------------
        # Shrinkage
        #
        # weight = n / (n + k)
        # ------------------------------------------------------------------

        if self.k <= 0.0:
            weight = 1.0
        else:
            weight = n / (n + self.k)

        self.weight = float(weight)

        # ------------------------------------------------------------------
        # Shrunk regression
        #
        # y_adj =
        #     mean + weight * (raw_model - mean)
        #
        # Therefore:
        #
        # slope_adj =
        #     raw_slope * weight
        #
        # intercept_adj =
        #     mean + weight * (raw_intercept - mean)
        # ------------------------------------------------------------------

        slope = raw_slope * weight

        intercept = (
            p_mean
            + weight * (
                raw_intercept - p_mean
            )
        )

        self.slope = float(slope)
        self.intercept = float(intercept)
        self.mean = p_mean

        # ------------------------------------------------------------------
        # Current baseline
        #
        # Use the last point in the current regression sample.
        # ------------------------------------------------------------------

        x_current = float(n - 1)

        baseline = (
            slope * x_current
            + intercept
        )

        self.baseline_f = float(baseline)

        # ------------------------------------------------------------------
        # RMSE of the SHRUNK model
        #
        # This is intentional.
        #
        # RMSE should measure how well the actual prices fit the model
        # that we are actually using, rather than the raw OLS model.
        # ------------------------------------------------------------------

        fitted = (
            slope * t
            + intercept
        )

        residuals = prices - fitted

        rmse = float(
            np.sqrt(
                np.mean(
                    residuals * residuals
                )
            )
        )

        self.rmse = max(
            rmse,
            1e-12,
        )

        # ------------------------------------------------------------------
        # Regression z-score
        # ------------------------------------------------------------------

        self.z_reg = (
            price - self.baseline_f
        ) / self.rmse

    # ======================================================================
    # Premium
    # ======================================================================

    def _update_premium(self, price: float) -> None:
        """
        Calculate preliminary return potential.

        premium_growth:
            slope / price

        premium_discount:
            (baseline - price) / price

        premium:
            premium_growth + premium_discount

        Equivalent:
            (slope + baseline - price) / price

        Interpretation
        --------------
        premium_growth:
            Growth embedded in the regression trend.

        premium_discount:
            Current price deviation below/above the regression baseline.

        premium:
            Combined preliminary upside potential.

        Note:
            RMSE is deliberately NOT included here.

            RMSE is kept separately as "model uncertainty".
        """

        price_safe = max(
            abs(float(price)),
            1e-12,
        )

        self.premium_growth = (
            self.slope / price_safe
        )

        self.premium_discount = (
            (self.baseline_f - price)
            / price_safe
        )

        self.premium = (
            self.premium_growth
            + self.premium_discount
        )

        # --------------------------------------------------------------
        # Relative regression uncertainty.
        # --------------------------------------------------------------

        self.model_uncertainty = self.rmse / price_safe

    # ======================================================================
    # Probability
    # ======================================================================

    def _update_probability(self) -> None:
        """
        Convert z_reg into a simple buy/sell probability pair.
        """

        sig = _sigmoid(self.z_reg)

        self.bp = 1.0 - sig
        self.sp = sig

    # ======================================================================
    # Strategic levels
    # ======================================================================

    def _update_target_points(self) -> None:
        """
        Target(P) = baseline + P * RMSE
        """

        self.target_points = {
            p: self.baseline_f + p * self.rmse
            for p in self.strategic_levels
        }

    # ======================================================================
    # Buy zone
    # ======================================================================

    def is_in_buy_zone(
        self,
        price: float,
        atr: float,
        tolerance_mult: float = 1.0,
        sma_filter: float | None = None,
    ) -> bool:
        """
        Check whether price is slightly above one of the lower strategic
        target levels.

        Conditions
        ----------
        0 < price - target <= tolerance_mult * ATR

        Only strategic levels with P <= 0 are considered.

        If sma_filter is provided:
            sma_filter > target

        This attempts to avoid buying when the broader trend is still
        below the target level.
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
        tolerance_mult: float = 1.0,
        sma_filter: float | None = None,
    ) -> bool:
        """
        Check whether price is slightly below one of the upper strategic
        target levels.

        Conditions
        ----------
        -tolerance_mult * ATR <= price - target < 0

        Only strategic levels with P >= 0 are considered.

        If sma_filter is provided:
            sma_filter < target

        This attempts to avoid selling when the broader trend remains
        above the target level.
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

        self.current_t = 0

        # Regression
        self.raw_slope = 0.0
        self.raw_intercept = 0.0

        self.slope = 0.0
        self.intercept = 0.0

        self.mean = 0.0
        self.weight = 0.0

        self.baseline_f = 0.0

        # Uncertainty
        self.rmse = 0.0
        self.model_uncertainty = 0.0
        self.z_reg = 0.0

        # Premium
        self.premium_growth = 0.0
        self.premium_discount = 0.0
        self.premium = 0.0

        # Probability
        self.bp = 0.5
        self.sp = 0.5

        # Targets
        self.target_points.clear()


# ==========================================================================
# Helpers
# ==========================================================================

def _sigmoid(x: float) -> float:
    """
    Numerically stable sigmoid.
    """

    x = float(x)

    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)

    z = math.exp(x)
    return z / (1.0 + z)
