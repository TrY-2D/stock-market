from __future__ import annotations

import numpy as np
import pytest

from src.strategies.indicators.beta import MultivariateLinearRegression


def test_multivariate_linear_regression_pct_calculation():
    """Kiểm tra mô hình tính toán trên phần trăm thay đổi (%change / returns)."""
    model = MultivariateLinearRegression(n_features=2, window=30, learning_rate=0.01, epochs=30)

    # Quan sát 1: Chỉ lưu giá khởi tạo
    model.update_raw(1000.0, 100.0, 50.0)
    assert model.n_observations == 0

    # Quan sát 2: Phần trăm thay đổi:
    # Target %change = 1020 / 1000 - 1 = +0.02 (+2%)
    # Feature 0 %change = 105 / 100 - 1 = +0.05 (+5%)
    # Feature 1 %change = 48 / 50 - 1 = -0.04 (-4%)
    model.update_raw(1020.0, 105.0, 48.0)
    assert model.n_observations == 1
    assert pytest.approx(model.actual_change, rel=1e-5) == 0.02
    np.testing.assert_allclose(model.feature_changes, np.array([0.05, -0.04]), rtol=1e-5)


def test_multivariate_linear_regression_convergence():
    """Kiểm tra độ hội tụ của hệ số beta với quan hệ sinh lợi suất thực tế."""
    np.random.seed(42)
    n_features = 2
    true_intercept = 0.0002
    true_beta = np.array([1.25, -0.35])

    model = MultivariateLinearRegression(
        n_features=n_features,
        window=40,
        learning_rate=0.02,
        epochs=40,
    )

    curr_target = 1000.0
    curr_f0 = 100.0
    curr_f1 = 50.0

    model.update_raw(curr_target, curr_f0, curr_f1)

    for _ in range(50):
        r_f0 = np.random.normal(0.0005, 0.01)
        r_f1 = np.random.normal(-0.0002, 0.003)
        r_target = true_intercept + true_beta[0] * r_f0 + true_beta[1] * r_f1 + np.random.normal(0, 0.001)

        curr_target *= (1.0 + r_target)
        curr_f0 *= (1.0 + r_f0)
        curr_f1 *= (1.0 + r_f1)

        model.update_raw(curr_target, curr_f0, curr_f1)

    assert model.initialized
    coefs = model.coefficients
    assert len(coefs) == 2
    # Hệ số ước lượng phải tiệm cận giá trị thực
    assert pytest.approx(coefs[0], abs=0.1) == true_beta[0]
    assert pytest.approx(coefs[1], abs=0.1) == true_beta[1]
    assert pytest.approx(model.intercept, abs=0.001) == true_intercept

    # Kiểm tra predict & predict_percent
    pred = model.predict(0.01, -0.005)
    expected_pred = model.intercept + coefs[0] * 0.01 + coefs[1] * (-0.005)
    assert pytest.approx(pred, abs=1e-5) == expected_pred

    pred_pct = model.predict_percent(1.0, -0.5)
    assert pytest.approx(pred_pct, abs=1e-3) == pred * 100.0


def test_multivariate_linear_regression_reset():
    model = MultivariateLinearRegression(n_features=2, window=20)
    for i in range(25):
        model.update_raw(100.0 + i, 50.0 + i * 0.5, 20.0 - i * 0.2)

    assert model.initialized
    assert model.n_observations > 0

    model._reset()
    assert model.n_observations == 0
    assert model.predicted_change == 0.0
    assert model.actual_change == 0.0
    assert model.residual == 0.0
    assert np.all(model.beta == 0.0)
    assert model._previous_target_price is None
    assert model._previous_feature_prices is None
