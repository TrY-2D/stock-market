from __future__ import annotations

import math
import pytest
from src.strategies.indicators.dmi import DirectionalMovementIndex


def test_dmi_adaptive_trend_initialization():
    dmi = DirectionalMovementIndex(period=14, adx_period=14, hl_base=7.0, soft_c=25.0, alpha_mode="half_life")
    assert dmi.period == 14
    assert dmi.adx_period == 14
    assert dmi.hl_base == 7.0
    assert dmi.soft_c == 25.0
    assert dmi.alpha_mode == "half_life"

    assert dmi.trend_score == 0.0
    assert dmi.prev_trend_score == 0.0
    assert dmi.raw_trend == 0.0
    assert dmi.trend_alpha == 0.0
    assert dmi.half_life == 0.0
    assert not dmi.is_bullish
    assert not dmi.is_bearish
    assert dmi.trend_strength == 0.0


def test_dmi_alpha_computation_modes():
    dmi = DirectionalMovementIndex(hl_base=7.0, soft_c=25.0)

    # 1. Mode Half-Life (Recommended)
    # ADX = 30 -> HL = 7 * (30 / 30) = 7.0 -> alpha = 1 - 2^(-1/7)
    expected_hl = 7.0
    expected_alpha = 1.0 - math.pow(2.0, -1.0 / expected_hl)
    alpha_hl, hl_hl = dmi.compute_alpha(30.0, mode="half_life")
    assert pytest.approx(hl_hl, rel=1e-5) == expected_hl
    assert pytest.approx(alpha_hl, rel=1e-5) == expected_alpha

    # 2. Mode Soft (C=25)
    # ADX = 25 -> alpha = 25 / (25 + 25) = 0.5
    alpha_soft, _ = dmi.compute_alpha(25.0, mode="soft")
    assert pytest.approx(alpha_soft, rel=1e-5) == 0.5

    # 3. Mode Simple
    # ADX = 40 -> alpha = 40 / 100 = 0.4
    alpha_simp, _ = dmi.compute_alpha(40.0, mode="simple")
    assert pytest.approx(alpha_simp, rel=1e-5) == 0.4


def test_dmi_adaptive_trend_streaming_and_crossovers():
    dmi = DirectionalMovementIndex(period=5, adx_period=5, hl_base=7.0)

    # Bullish trend sequence
    for i in range(25):
        base = 100.0 + i * 2.0
        dmi.update_raw(high=base + 1.5, low=base - 0.5, close=base + 1.0)

    assert dmi.initialized
    assert dmi.plus_di > dmi.minus_di
    assert dmi.raw_trend > 0.0
    assert dmi.trend_score > 0.0
    assert dmi.is_bullish
    assert not dmi.is_bearish

    # Bearish trend reversal sequence
    crossed_bearish = False
    for i in range(25):
        base = 150.0 - i * 3.0
        dmi.update_raw(high=base + 0.5, low=base - 2.0, close=base - 1.5)
        if dmi.is_trend_bearish_cross():
            crossed_bearish = True

    assert crossed_bearish
    assert dmi.minus_di > dmi.plus_di
    assert dmi.raw_trend < 0.0
    assert dmi.trend_score < 0.0
    assert dmi.is_bearish


def test_dmi_reset():
    dmi = DirectionalMovementIndex(period=5, adx_period=5)
    for i in range(20):
        base = 100.0 + i
        dmi.update_raw(high=base + 1.0, low=base - 1.0, close=base)

    assert dmi.initialized
    dmi._reset()
    assert dmi.trend_score == 0.0
    assert dmi.raw_trend == 0.0
    assert dmi.half_life == 0.0
    assert dmi.trend_alpha == 0.0
    assert len(dmi._trend_history) == 0
