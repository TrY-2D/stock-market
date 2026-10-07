from __future__ import annotations

from collections import deque
import math
from typing import Any, Sequence

import numpy as np

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class MultivariateLinearRegression(Indicator):
    """
    Rolling Multivariate Linear Regression using Gradient Descent.

    Model
    -----
        target_change =
            intercept
            + beta_0 * feature_0_change
            + beta_1 * feature_1_change
            + ...
            + error
    Input
    -----
    update_raw(
        target_price,
        feature_0_price,
        feature_1_price,
        ...
    )

    Each price series is converted into percentage change:

        change = (price_t / price_{t-1}) - 1

    The regression is then updated using the latest rolling window.

    Main method
    -----------
    predict(*feature_changes)

    Predict the percentage change of the target from percentage changes
    of the explanatory variables.

    Example
    -------
        model.update_raw(
            fpt_price,
            vnindex_price,
            usd_vnd_price,
            nasdaq_price,
        )

        predicted_change = model.predict(
            vnindex_change,
            usd_vnd_change,
            nasdaq_change,
        )

    Interpretation
    --------------
    coefficients:
        Sensitivity of target %change to each feature %change.

    intercept:
        Baseline target %change when all feature changes are zero.

    predicted_change:
        Model prediction of target %change.

    residual:
        Actual target %change - predicted %change.

    model_uncertainty:
        RMSE of residuals.

    r_squared:
        Rolling explanatory power of the model.

    Notes
    -----
    The model operates on percentage changes rather than absolute prices.
    Therefore coefficients describe short-term sensitivity between returns.

    Gradient descent is used instead of solving the normal equation from scratch
    on every bar because the model is intended to be updated incrementally as new
    observations arrive.
    """

    def __init__(
        self,
        n_features: int,
        window: int | None = 1500,
        learning_rate: float = 0.01,
        epochs: int = 10,
        l2: float = 0.0,
        expanding: bool = False,
    ):
        if n_features <= 0:
            raise ValueError(
                "n_features must be greater than 0"
            )

        if learning_rate <= 0:
            raise ValueError(
                "learning_rate must be greater than 0"
            )

        if epochs <= 0:
            raise ValueError(
                "epochs must be greater than 0"
            )

        if l2 < 0:
            raise ValueError(
                "l2 must be >= 0"
            )

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

        self.n_features = int(n_features)

        self.window = (
            int(window)
            if window is not None
            and window > 0
            else 0
        )

        self.expanding = (
            expanding
            or window is None
            or window <= 0
        )

        self.learning_rate = float(
            learning_rate
        )

        self.epochs = int(epochs)

        self.l2 = float(l2)
        # ------------------------------------------------------------------
        # Price history
        # ------------------------------------------------------------------

        self._previous_target_price: (
            float | None
        ) = None

        self._previous_feature_prices: (
            np.ndarray | None
        ) = None

        # ------------------------------------------------------------------
        # Percentage-change observations
        # ------------------------------------------------------------------
        maxlen = (
            None
            if self.expanding
            else self.window
        )

        self._target_changes: deque[
            float
        ] = deque(maxlen=maxlen)

        self._feature_changes: deque[
            np.ndarray
        ] = deque(maxlen=maxlen)

        # ------------------------------------------------------------------
        # Regression parameters
        #
        # beta[0] = intercept
        # beta[1:] = feature coefficients
        # ------------------------------------------------------------------

        self.beta = np.zeros(
            self.n_features + 1,
            dtype=np.float64,
        )

        # ------------------------------------------------------------------
        # Current model outputs
        # ------------------------------------------------------------------

        self.predicted_change: float = 0.0

        self.actual_change: float = 0.0

        self.residual: float = 0.0

        self.model_uncertainty: float = 0.0

        self.r_squared: float = 0.0

        self.sse: float = 0.0
        self.sst: float = 0.0

        self.n_observations: int = 0

        self.feature_changes = np.zeros(
            self.n_features,
            dtype=np.float64,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------


    @property
    def value(self) -> float:
        """
        Current predicted target %change.
        """
        return self.predicted_change

    @property
    def coefficients(self) -> np.ndarray:
        """
        Feature coefficients only.

        Excludes the intercept.
        """
        return self.beta[1:].copy()

    @property
    def intercept(self) -> float:
        """
        Regression intercept.
        """
        return float(self.beta[0])

    @property
    def baseline(self) -> float:
        """
        Current regression baseline.

        Equivalent to the intercept because the regression operates
        on percentage changes.
        """
        return self.intercept

    # ------------------------------------------------------------------
    # Nautilus handlers
    # ------------------------------------------------------------------

    def handle_bar(
        self,
        bar: Bar,
    ) -> None:
        """
        Target-only Nautilus handler.

        Multivariate updates require feature prices, therefore normal
        usage should call update_raw() directly or through a custom
        integration layer.
        """
        pass

    def handle_quote_tick(
        self,
        tick: Any,
    ) -> None:
        pass

    def handle_trade_tick(
        self,
        tick: Any,
    ) -> None:
        pass

    # ------------------------------------------------------------------
    # Main update method
    # ------------------------------------------------------------------

    def update_raw(
        self,
        target_price: float,
        *feature_prices: float,
    ) -> None:
        """
        Update the model with new prices.

        Parameters
        ----------
        target_price:
            Current price of target X.

        feature_prices:
            Current prices of a, b, c, ...

        Example
        -------
            model.update_raw(
                x_price,
                a_price,
                b_price,
                c_price,
            )
        """


        if len(feature_prices) != self.n_features:
            raise ValueError(
                f"Expected {self.n_features} feature prices, "
                f"got {len(feature_prices)}"
            )

        target_price = float(
            target_price
        )

        feature_prices_array = np.asarray(
            feature_prices,
            dtype=np.float64,
        )

        if not math.isfinite(
            target_price
        ):
            return

        if not np.all(
            np.isfinite(
                feature_prices_array
            )
        ):
            return
        if target_price == 0.0:
            return

        if np.any(
            feature_prices_array == 0.0
        ):
            return
        # --------------------------------------------------------------
        # First observation only initializes the previous prices.
        # --------------------------------------------------------------

        if (
            self._previous_target_price
            is None
        ):
            self._previous_target_price = (
                target_price
            )

            self._previous_feature_prices = (
                feature_prices_array.copy()
            )

            return

        # --------------------------------------------------------------
        # Calculate percentage changes.
        # --------------------------------------------------------------

        target_change = (
            target_price
            / self._previous_target_price
            - 1.0
        )

        feature_changes = (
            feature_prices_array
            / self._previous_feature_prices
            - 1.0
        )
        # Update previous prices immediately.
        self._previous_target_price = (
            target_price
        )

        self._previous_feature_prices = (
            feature_prices_array.copy()
        )

        if not math.isfinite(
            target_change
        ):
            return

        if not np.all(
            np.isfinite(feature_changes)
        ):
            return

        # --------------------------------------------------------------
        # Store observation.
        # --------------------------------------------------------------

        self._target_changes.append(
            float(target_change)
        )

        self._feature_changes.append(
            feature_changes.copy()
        )

        self.actual_change = float(
            target_change
        )

        self.feature_changes = (
            feature_changes.copy()
        )

        self.n_observations = len(
            self._target_changes
        )

        # --------------------------------------------------------------
        # Need enough observations before fitting.
        # --------------------------------------------------------------

        min_required = max(
            self.n_features + 2,
            10,
        )

        if self.n_observations < min_required:
            return

        # --------------------------------------------------------------
        # Fit model.
        # --------------------------------------------------------------

        self._fit_gradient_descent()

        # --------------------------------------------------------------
        # Evaluate current observation.
        # --------------------------------------------------------------

        self.predicted_change = (
            self._predict_array(
                feature_changes
            )
        )

        self.residual = (
            self.actual_change
            - self.predicted_change
        )

        self._update_statistics()

        self._set_has_inputs(True)

        if (
            self.expanding
            or self.n_observations >= self.window
        ):
            self._set_initialized(True)

    # ------------------------------------------------------------------
    # Gradient descent
    # ------------------------------------------------------------------

    def _fit_gradient_descent(
        self,
    ) -> None:
        """
        Batch gradient descent over the current rolling window.

        Model:

            y_hat = X @ beta

        Loss:

            MSE + L2 regularization
        """

        y = np.asarray(
            self._target_changes,
            dtype=np.float64,
        )

        features = np.asarray(
            self._feature_changes,
            dtype=np.float64,
        )
        n = len(y)

        if n == 0:
            return



        # Add intercept.
        X = np.column_stack(
            (
                np.ones(n),
                features,
            )
        )

        # Initialize beta with least-squares on first fit if uninitialized
        if np.all(self.beta == 0.0):
            try:
                self.beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            except Exception:
                pass

        beta = self.beta.copy()

        for _ in range(self.epochs):
            prediction = X @ beta

            error = (
                prediction - y
            )

            gradient = (
                X.T @ error
            ) / n

            # L2 regularization on feature
            # coefficients only.
            if self.l2 > 0.0:
                gradient[1:] += (
                    self.l2
                    * beta[1:]
                )

            beta -= (
                self.learning_rate
                * gradient
            )
        self.beta = beta

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def _predict_array(
        self,
        feature_changes: np.ndarray,
    ) -> float:
        """
        Predict target %change from feature %changes.
        """
        if len(feature_changes) != (
            self.n_features
        ):
            raise ValueError(
                f"Expected "
                f"{self.n_features} feature changes, "
                f"got {len(feature_changes)}"
            )

        x = np.empty(
            self.n_features + 1,
            dtype=np.float64,
        )

        x[0] = 1.0
        x[1:] = feature_changes

        return float(
            x @ self.beta
        )

    def predict(
        self,
        *feature_changes: float,
    ) -> float:
        """
        Predict target %change.

        Parameters
        ----------
        feature_changes:
            Percentage changes of a, b, c, ...

        Example
        -------
            prediction = model.predict(
                0.01,
                -0.005,
                0.02,
            )

        Means:

            a +1.0%
            b -0.5%
            c +2.0%

        Returns
        -------
        float
            Predicted target percentage change
            in decimal form.

            0.012 means +1.2%.
        """

        if len(feature_changes) != (
            self.n_features
        ):
            raise ValueError(
                f"Expected "
                f"{self.n_features} feature changes, "
                f"got {len(feature_changes)}"
            )

        changes = np.asarray(
            feature_changes,
            dtype=np.float64,
        )

        if not np.all(
            np.isfinite(changes)
        ):
            raise ValueError(
                "feature_changes must be finite"
            )

        return self._predict_array(
            changes
        )

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def _update_statistics(
        self,
    ) -> None:
        """
        Calculate rolling model uncertainty and R².
        """

        y = np.asarray(
            self._target_changes,
            dtype=np.float64,
        )

        features = np.asarray(
            self._feature_changes,
            dtype=np.float64,
        )

        if len(y) == 0:
            return

        X = np.column_stack(
            (
                np.ones(len(y)),
                features,
            )
        )

        predictions = X @ self.beta

        residuals = (
            y - predictions
        )

        self.sse = float(
            np.sum(
                residuals ** 2
            )
        )

        mean_y = float(
            np.mean(y)
        )

        self.sst = float(
            np.sum(
                (y - mean_y) ** 2
            )
        )

        if self.sst > 1e-16:
            self.r_squared = max(
                0.0,
                1.0
                - self.sse
                / self.sst,
            )
        else:
            self.r_squared = 0.0

        # RMSE of target percentage change.
        self.model_uncertainty = float(
            math.sqrt(
                np.mean(
                    residuals ** 2
                )
            )
        )

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def predict_percent(
        self,
        *feature_changes_percent: float,
    ) -> float:
        """
        Predict target change in percentage points.

        Example
        -------
            predict_percent(
                1.0,
                -0.5,
                2.0,
            )

        means:

            a +1.0%
            b -0.5%
            c +2.0%

        Returns:
            1.25 means +1.25%.
        """

        changes = (
            np.asarray(
                feature_changes_percent,
                dtype=np.float64,
            )
            / 100.0
        )

        return (
            self.predict(*changes)
            * 100.0
        )
    def contribution(
        self,
        *feature_changes: float,
    ) -> np.ndarray:
        """
        Return contribution of each feature
        to the predicted target change.

        Excludes intercept.

        contribution_i =
            beta_i * feature_change_i
        """

        if len(feature_changes) != (
            self.n_features
        ):
            raise ValueError(
                f"Expected "
                f"{self.n_features} feature changes, "
                f"got {len(feature_changes)}"
            )

        changes = np.asarray(
            feature_changes,
            dtype=np.float64,
        )

        return (
            self.beta[1:]
            * changes
        )

    def feature_sensitivity(
        self,
    ) -> np.ndarray:
        """
        Return regression sensitivity of each
        feature.

        beta_i = expected target %change
                 from a 1.0 unit change
                 in feature %change.

        Example:
            beta = 0.8

        means approximately:

            feature +1%
            -> target +0.8%
        """

        return self.beta[1:].copy()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        self._previous_target_price = None

        self._previous_feature_prices = None

        self._target_changes.clear()
        self._feature_changes.clear()

        self.beta.fill(0.0)

        self.predicted_change = 0.0
        self.actual_change = 0.0
        self.residual = 0.0

        self.model_uncertainty = 0.0
        self.r_squared = 0.0

        self.sse = 0.0
        self.sst = 0.0

        self.n_observations = 0

        self.feature_changes.fill(0.0)