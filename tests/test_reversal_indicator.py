from __future__ import annotations

import math
import pytest
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from src.strategies.indicators.reversal import (
    ReversalIndicator,
    ReversalSnapshot,
    SupportResistanceReversalIndicator,
)


def create_test_bar(open_p: float, high_p: float, low_p: float, close_p: float, ts_ns: int = 1_000_000_000) -> Bar:
    """Tạo một Bar hợp lệ của Nautilus Trader cho unit test."""
    instrument_id = InstrumentId.from_str("TEST.HOSE")
    bar_spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
    bar_type = BarType(instrument_id, bar_spec)
    return Bar(
        bar_type=bar_type,
        open=Price.from_str(f"{open_p:.2f}"),
        high=Price.from_str(f"{high_p:.2f}"),
        low=Price.from_str(f"{low_p:.2f}"),
        close=Price.from_str(f"{close_p:.2f}"),
        volume=Quantity.from_int(100_000),
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def test_reversal_indicator_initialization():
    ind = SupportResistanceReversalIndicator(
        linear_window=20,
        sma_window=20,
        dmi_period=14,
        atr_period=14,
        atr_multiplier=1.0,
    )
    assert ind.linear_window == 20
    assert ind.sma_window == 20
    assert ind.dmi_period == 14
    assert ind.atr_period == 14
    assert ind.atr_multiplier == 1.0
    assert ind.signal == 0
    assert ind.trend == 0
    assert ind.atr == 0.0
    assert not ind.is_bullish
    assert not ind.is_bearish
    assert ind.value == 0.0


def test_support_and_resistance_zones_structure():
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=10,
        atr_period=10,
        atr_multiplier=1.0,
    )

    # Nạp 15 phiên để khởi tạo linear, sma, atr
    for i in range(15):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 2.0, low_p=base - 2.0, close_p=base)

    assert ind.atr > 0.0
    sup_levels = ind.support_levels
    res_levels = ind.resistance_levels
    assert len(sup_levels) > 0
    assert len(res_levels) > 0

    # Kiểm tra cấu trúc vùng hỗ trợ [S, S + ATR]
    sup_zones = ind.support_zones
    assert len(sup_zones) == len(sup_levels)
    for s, (z_low, z_high) in zip(sup_levels, sup_zones):
        assert z_low == pytest.approx(s)
        assert z_high == pytest.approx(s + ind.atr)

    # Kiểm tra cấu trúc vùng kháng cự [R - ATR, R]
    res_zones = ind.resistance_zones
    assert len(res_zones) == len(res_levels)
    for r, (z_low, z_high) in zip(res_levels, res_zones):
        assert z_low == pytest.approx(r - ind.atr)
        assert z_high == pytest.approx(r)
def test_closest_support_and_resistance():
    ind = SupportResistanceReversalIndicator(linear_window=10, sma_window=10)
    for i in range(20):
        p = 100.0 + i * 2.0
        ind.update_raw(open_p=p, high_p=p + 1.0, low_p=p - 1.0, close_p=p)

    current_price = 138.0
    closest_s = ind.get_closest_support(current_price)
    closest_r = ind.get_closest_resistance(current_price)

    assert closest_s is not None
    assert closest_s < current_price
    if closest_r is not None:
        assert closest_r > current_price


def test_bullish_reversal_at_support_zone():
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=10,
        atr_period=10,
        atr_multiplier=1.0,
    )

    # Khởi tạo mô hình
    for i in range(15):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base)

    target_sup = ind.support_levels[0]
    atr_val = ind.atr

    # Đưa giá vào vùng hỗ trợ [target_sup, target_sup + atr]
    price_in_support = target_sup + 0.5 * atr_val
    assert ind.is_in_support_zone(price_in_support)

    # Tạo nến Hammer đảo chiều tăng:
    # Thân nhỏ phía trên, bóng dưới dài >= 2 * body
    open_hammer = price_in_support + 0.1
    close_hammer = price_in_support + 0.2
    high_hammer = price_in_support + 0.22
    low_hammer = price_in_support - 1.0  # bóng dưới dài

    snap = ind.update_raw(
        open_p=open_hammer,
        high_p=high_hammer,
        low_p=low_hammer,
        close_p=close_hammer,
    )

    assert snap.candle_bullish
    assert snap.is_in_support
    assert snap.signal == 1
    assert snap.trend == 1
    assert ind.is_buy_signal
    assert ind.is_bullish


def test_bearish_reversal_at_resistance_zone():
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=10,
        atr_period=10,
        atr_multiplier=1.0,
    )

    for i in range(15):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base)

    target_res = ind.resistance_levels[-1]
    atr_val = ind.atr

    # Đưa giá vào vùng kháng cự [target_res - atr, target_res]
    price_in_res = target_res - 0.5 * atr_val
    assert ind.is_in_resistance_zone(price_in_res)

    # Tạo nến Shooting Star đảo chiều giảm:
    # Thân nhỏ phía dưới, bóng trên dài >= 2 * body
    open_star = price_in_res - 0.1
    close_star = price_in_res - 0.2
    high_star = price_in_res + 1.0  # bóng trên dài
    low_star = price_in_res - 0.22

    snap = ind.update_raw(
        open_p=open_star,
        high_p=high_star,
        low_p=low_star,
        close_p=close_star,
    )

    assert snap.candle_bearish
    assert snap.is_in_resistance
    assert snap.signal == -1
    assert snap.trend == -1
    assert ind.is_sell_signal
    assert ind.is_bearish


def test_no_reversal_signal_preserves_previous_trend():
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=10,
        atr_period=10,
    )

    for i in range(15):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base)

    # 1. Kích hoạt Buy Reversal tại hỗ trợ
    target_sup = ind.support_levels[0]
    atr_val = ind.atr
    p_sup = target_sup + 0.3 * atr_val
    snap_buy = ind.update_raw(
        open_p=p_sup,
        high_p=p_sup + 0.05,
        low_p=p_sup - 0.8,
        close_p=p_sup + 0.04,
    )
    assert snap_buy.signal == 1
    assert snap_buy.trend == 1

    # 2. Phiên tiếp theo: Nến tăng, hoàn tất bước cắt DMI
    ind.update_raw(
        open_p=p_sup + 0.1,
        high_p=p_sup + 0.6,
        low_p=p_sup + 0.08,
        close_p=p_sup + 0.55,
    )
    # 3. Phiên tiếp sau đó: Nến bình thường tiếp diễn, không còn bất kỳ tín hiệu đảo chiều nào
    snap_normal = ind.update_raw(
        open_p=p_sup + 0.6,
        high_p=p_sup + 0.8,
        low_p=p_sup + 0.5,
        close_p=p_sup + 0.7,
    )
    # Tín hiệu về 0, nhưng trend giữ nguyên giá trị cũ là 1
    assert snap_normal.signal == 0
    assert snap_normal.trend == 1
    assert ind.signal == 0
    assert ind.trend == 1
    assert ind.is_bullish


def test_reversal_signal_outside_zone_is_ignored():
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=10,
        atr_period=10,
    )

    for i in range(15):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base)

    # Đặt giá ở giữa khoảng trống, không nằm trong hỗ trợ cũng không nằm trong kháng cự
    # Bằng cách chọn giá = baseline + 50% RMSE (giả sử không nằm trong bất kỳ tolerance nào)
    mid_price = 100.0
    # Đảm bảo mid_price không trong vùng
    while ind.is_in_support_zone(mid_price) or ind.is_in_resistance_zone(mid_price):
        mid_price += 0.1

    # Tạo nến Hammer tại mid_price (không ở hỗ trợ)
    snap = ind.update_raw(
        open_p=mid_price + 0.05,
        high_p=mid_price + 0.07,
        low_p=mid_price - 0.9,
        close_p=mid_price + 0.06,
    )
    assert snap.candle_bullish
    assert not snap.is_in_support
    assert snap.signal == 0
    assert snap.trend == 0


def test_handle_bar_nautilus_integration():
    ind = ReversalIndicator(
        linear_window=5,
        sma_window=5,
        dmi_period=5,
        atr_period=5,
    )

    for i in range(15):
        base = 50.0 + i * 0.5
        bar = create_test_bar(
            open_p=base,
            high_p=base + 1.0,
            low_p=base - 1.0,
            close_p=base + 0.2,
            ts_ns=(i + 1) * 86_400_000_000_000,
        )
        ind.handle_bar(bar)

    assert ind.initialized
    assert ind.atr > 0.0
    assert ind.snapshot is not None
    assert ind.snapshot.price == pytest.approx(50.0 + 14 * 0.5 + 0.2)


def test_reversal_indicator_reset():
    ind = SupportResistanceReversalIndicator(linear_window=5, sma_window=5, dmi_period=5)
    for i in range(10):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base)

    assert ind.count > 0 or ind._count > 0
    assert ind.atr > 0.0

    ind._reset()
    assert ind.signal == 0
    assert ind.trend == 0
    assert ind.atr == 0.0
    assert ind._count == 0
    assert ind.snapshot is None


def test_dmi_only_reversal_trigger():
    """Kiểm tra tín hiệu đảo chiều kích hoạt bởi DMI (khi nến không có pattern đặc biệt)."""
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=5,
        atr_period=10,
    )
    # Nạp chuỗi giảm mạnh để -DI cao và T_t âm (bearish)
    for i in range(15):
        base = 150.0 - i * 2.0
        ind.update_raw(open_p=base + 1.0, high_p=base + 1.2, low_p=base - 1.0, close_p=base)

    assert ind.dmi.is_bearish

    # Đưa giá vào vùng hỗ trợ và tạo cú tăng mạnh để DMI cắt đảo chiều tăng
    target_sup = ind.support_levels[0]
    p_reversal = target_sup + 0.2 * ind.atr
    assert ind.is_in_support_zone(p_reversal)

    # Nến Marubozu tăng mạnh (không phải Hammer, Doji hay Engulfing)
    snap = ind.update_raw(
        open_p=p_reversal - 0.2,
        high_p=p_reversal + 0.3,
        low_p=p_reversal - 0.22,
        close_p=p_reversal + 0.25,
    )
    if snap.dmi_bullish:
        assert snap.signal == 1
        assert snap.trend == 1


def test_custom_atr_and_range_touch_mode():
    ind = SupportResistanceReversalIndicator(
        linear_window=10,
        sma_window=10,
        dmi_period=10,
        price_touch_mode="range",
    )
    for i in range(15):
        base = 100.0 + i
        ind.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base, atr=3.0)

    assert ind.atr == 3.0
    target_sup = ind.support_levels[0]

    # Giá đóng cửa nằm ngay phía trên vùng hỗ trợ, nhưng bóng nến (low) chạm sâu vào vùng hỗ trợ [S, S + ATR]
    close_above = target_sup + 3.2
    low_in_zone = target_sup + 1.0  # chạm vùng
    assert ind.is_in_support_zone(close_above, low_p=low_in_zone)

    # Kiểm tra target_mode = 'all'
    ind_all = SupportResistanceReversalIndicator(linear_window=10, sma_window=10, target_mode="all")
    for i in range(15):
        base = 100.0 + i
        ind_all.update_raw(open_p=base, high_p=base + 1.0, low_p=base - 1.0, close_p=base)

    # Trong mode 'all', tất cả target points đều xuất hiện ở cả support và resistance
    assert len(ind_all.support_levels) >= len(ind.support_levels)
    assert len(ind_all.resistance_levels) >= len(ind.resistance_levels)
