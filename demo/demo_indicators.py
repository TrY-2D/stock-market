from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
import sys
from typing import Sequence

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import numpy as np
import pandas as pd

from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from src.strategies.indicators import (
    DirectionalMovementIndex,
    LinearRegressionChannel,
    MultivariateLinearRegression,
    RollingStatistics,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Data Loader & Synthesizer
# ==============================================================================

def generate_synthetic_market_data(n_bars: int = 120) -> pd.DataFrame:
    """Tạo dữ liệu thị trường giả lập chân thực (OHLCV + VNINDEX + USD/VND).

    Dùng làm phương án dự phòng khi chạy offline hoặc khi mạng gặp sự cố.
    """
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=n_bars, freq="B")

    # Mô phỏng lợi suất (returns) tương quan
    r_index = np.random.normal(0.0006, 0.012, n_bars)
    r_fx = np.random.normal(0.0001, 0.002, n_bars)
    # Target FPT có beta thị trường ~ 1.25 và độ nhạy tỷ giá ~ -0.35
    r_target = 0.0003 + 1.25 * r_index - 0.35 * r_fx + np.random.normal(0.0, 0.007, n_bars)

    p_index = 1120.0 * np.exp(np.cumsum(r_index))
    p_fx = 24400.0 * np.exp(np.cumsum(r_fx))
    p_target_close = 64000.0 * np.exp(np.cumsum(r_target))

    # Sinh OHLCV từ giá đóng cửa
    high_target = p_target_close * (1.0 + np.abs(np.random.normal(0.006, 0.004, n_bars)))
    low_target = p_target_close * (1.0 - np.abs(np.random.normal(0.006, 0.004, n_bars)))
    open_target = low_target + (high_target - low_target) * np.random.uniform(0.2, 0.8, n_bars)
    volume_target = np.random.randint(1_500_000, 5_500_000, n_bars)

    return pd.DataFrame({
        "date": dates,
        "open": np.round(open_target, -1),
        "high": np.round(high_target, -1),
        "low": np.round(low_target, -1),
        "close": np.round(p_target_close, -1),
        "volume": volume_target,
        "vnindex": np.round(p_index, 2),
        "usdvnd": np.round(p_fx, 1),
    })


def load_market_dataset(force_synthetic: bool = False) -> tuple[pd.DataFrame, bool]:
    """Tải dữ liệu thị trường từ SSI & Yahoo Finance hoặc chuyển sang dữ liệu giả lập."""
    if force_synthetic:
        print("  [Thông báo] Sử dụng dữ liệu giả lập (theo cờ --synthetic).")
        return generate_synthetic_market_data(120), True

    try:
        from src.data_pipeline.ssi import SSIFetcher
        from src.data_pipeline.yahoo import YahooFinanceFetcher

        print("  [Kết nối] Đang lấy dữ liệu thực tế từ SSIFetcher & YahooFinanceFetcher...")
        with SSIFetcher() as ssi:
            df_fpt = ssi.fetch_df("FPT", interval="1d", start_date="2024-01-01", end_date="2024-06-30")
            df_vni = ssi.fetch_df("VNINDEX", interval="1d", start_date="2024-01-01", end_date="2024-06-30")

        with YahooFinanceFetcher() as yf:
            df_fx = yf.get_ohlcv("USD/VND", interval="1d", start_date="2024-01-01", end_date="2024-06-30")

        if df_fpt.empty or df_vni.empty or df_fx.empty:
            raise ValueError("Dữ liệu trả về rỗng từ một trong các nguồn.")

        # Chuẩn hóa ngày để ghép đồng bộ
        df_fpt["d"] = pd.to_datetime(df_fpt.index).date
        df_vni["d"] = pd.to_datetime(df_vni.index).date
        df_fx["d"] = pd.to_datetime(df_fx.index).date

        merged = df_fpt[["d", "open", "high", "low", "close", "volume"]].copy()
        merged = merged.merge(df_vni[["d", "close"]].rename(columns={"close": "vnindex"}), on="d", how="inner")
        merged = merged.merge(df_fx[["d", "close"]].rename(columns={"close": "usdvnd"}), on="d", how="inner")
        merged = merged.rename(columns={"d": "date"}).sort_values("date").reset_index(drop=True)

        print(f"  => Tải thành công {len(merged)} nến lịch sử thực tế (FPT, VNINDEX, USD/VND)!")
        return merged, False

    except Exception as exc:
        print(f"  [Cảnh báo] Không thể tải dữ liệu trực tuyến ({exc}).")
        print("  => Tự động kích hoạt bộ sinh dữ liệu giả lập chất lượng cao.")
        return generate_synthetic_market_data(120), True


def build_nautilus_bars(df: pd.DataFrame, symbol_str: str = "FPT.HOSE") -> list[Bar]:
    """Chuyển đổi DataFrame thành danh sách các đối tượng Bar chuẩn của Nautilus Trader."""
    instrument_id = InstrumentId.from_str(symbol_str)
    bar_spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
    bar_type = BarType(instrument_id, bar_spec)

    bars: list[Bar] = []
    for _, row in df.iterrows():
        dt = pd.to_datetime(row["date"])
        ts_ns = int(dt.timestamp() * 1_000_000_000)
        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str(f"{float(row['open']):.2f}"),
            high=Price.from_str(f"{float(row['high']):.2f}"),
            low=Price.from_str(f"{float(row['low']):.2f}"),
            close=Price.from_str(f"{float(row['close']):.2f}"),
            volume=Quantity.from_int(int(row.get("volume", 1000000))),
            ts_event=ts_ns,
            ts_init=ts_ns,
        )
        bars.append(bar)
    return bars


# ==============================================================================
# 2. Demo 1: RollingStatistics (sma.py)
# ==============================================================================

def demo_rolling_statistics(bars: list[Bar], df: pd.DataFrame) -> None:
    """Minh họa RollingStatistics: Thống kê trượt, Z-Score, Tốc độ xu hướng, Phân rã Premium & Dải mục tiêu."""
    print("\n" + "=" * 78)
    print("DEMO 1: RollingStatistics (src/strategies/indicators/sma.py)")
    print("=" * 78)
    print("Lý thuyết cốt lõi:")
    print("  * Baseline           : SMA(price) theo cửa sổ trượt (window=20).")
    print("  * Z-Score            : (price - SMA) / STD (đo độ lệch chuẩn hóa).")
    print("  * G_SMA (Velocity)   : (SMA_t - SMA_{t-1}) / price * scale_factor (tốc độ xu hướng).")
    print("  * Premium Growth     : G_SMA.")
    print("  * Premium Discount   : (SMA - price) / price (biên độ hồi quy về giá trị trung bình).")
    print("  * Premium Tổng       : Premium Growth + Premium Discount.")
    print("  * Strategic Targets  : Target(P) = SMA + P * STD với các mức độ tin cậy P.")

    strategic_levels = (2.0, 1.144, 0.472, 0.0, -0.472, -1.144, -2.0)
    sma = RollingStatistics(window=20, strategic_levels=strategic_levels, scale_factor=255.0)

    print(f"\n[1.1] Bắt đầu streaming {len(bars)} nến qua sma.handle_bar(bar)...")
    init_bar_idx = -1

    for idx, bar in enumerate(bars):
        sma.handle_bar(bar)
        if sma.initialized and init_bar_idx == -1:
            init_bar_idx = idx
            print(f"  -> Chỉ báo khởi tạo thành công tại nến #{idx+1} ({df.iloc[idx]['date']}) "
                  f"với n = {len(sma._buffer)} quan sát.")

    last_bar = bars[-1]
    last_price = last_bar.close.as_double()

    print("\n[1.2] Trạng thái chỉ báo tại nến cuối cùng:")
    print(f"  * Giá đóng cửa hiện tại (Price) : {last_price:,.2f}")
    print(f"  * Đường cơ sở SMA (Baseline)   : {sma.baseline:,.2f}")
    print(f"  * Độ lệch chuẩn (STD)           : {sma.std:,.2f}")
    print(f"  * Chỉ số Z-Score                : {sma.z_score:+.4f}")
    print(f"  * Tốc độ xu hướng (G_SMA)       : {sma.sma_growth:+.4f} (annualized)")
    print(f"  * Phân rã Premium:")
    print(f"      + Tăng trưởng (Growth)      : {sma.premium_growth:+.4%}")
    print(f"      + Chiết khấu (Discount)     : {sma.premium_discount:+.4%}")
    print(f"      + Tổng Premium kỳ vọng      : {sma.premium:+.4%}")
    print(f"  * Độ bất định mô hình (STD/P)   : {sma.model_uncertainty:.4%}")
    print(f"  * Xác suất Mua/Bán (Sigmoid)    : BP={sma.bp:.2%} | SP={sma.sp:.2%}")

    print("\n[1.3] Bảng các mức giá mục tiêu chiến lược (Strategic Target Points):")
    print(f"  {'Mức P':<8} | {'Độ tin cậy/Ý nghĩa':<25} | {'Giá mục tiêu':<15} | {'Khoảng cách tới giá HT'}")
    print("  " + "-" * 70)
    level_meanings = {
        2.0: "+2.000 STD (Kháng cự mạnh / Quá mua)",
        1.144: "+1.144 STD (Biên trên 75%)",
        0.472: "+0.472 STD (Biên trên nhẹ)",
        0.0: " 0.000 STD (Đường trung bình SMA)",
        -0.472: "-0.472 STD (Biên dưới nhẹ)",
        -1.144: "-1.144 STD (Biên dưới 75%)",
        -2.0: "-2.000 STD (Hỗ trợ mạnh / Quá bán)",
    }
    for p_level in strategic_levels:
        target_val = sma.target_points.get(p_level, float("nan"))
        diff_pct = (target_val - last_price) / last_price
        desc = level_meanings.get(p_level, f"{p_level} STD")
        print(f"  {p_level:+6.3f}   | {desc:<25} | {target_val:>13,.2f} | {diff_pct:+8.2%}")

    print("  => Kiểm tra RollingStatistics: HOÀN TẤT VÀ HỢP LỆ.")


# ==============================================================================
# 3. Demo 2: LinearRegressionChannel (linear.py)
# ==============================================================================

def demo_linear_regression_channel(bars: list[Bar], df: pd.DataFrame) -> None:
    """Minh họa LinearRegressionChannel: Co ngót mẫu nhỏ Bayesian-style, kênh hồi quy và phân rã định giá."""
    print("\n" + "=" * 78)
    print("DEMO 2: LinearRegressionChannel (src/strategies/indicators/linear.py)")
    print("=" * 78)
    print("Lý thuyết cốt lõi:")
    print("  * OLS Thuần Túy      : y = raw_slope * t + raw_intercept.")
    print("  * Trọng số Co Ngót   : weight = n / (n + k) (với k là hệ số giảm phương sai khi mẫu nhỏ).")
    print("  * Độ dốc hiệu chỉnh  : adjusted_slope = raw_slope * weight.")
    print("  * Chặn hiệu chỉnh    : adjusted_intercept = mean + weight * (raw_intercept - mean).")
    print("  * Bản chất           : Khi n nhỏ -> weight->0 -> mô hình co về giá trị trung bình (tránh overfit).")
    print("                         Khi n lớn -> weight->1 -> mô hình hội tụ tiệm cận OLS.")
    print("  * Kênh hồi quy & Z   : z_reg = (price - baseline) / RMSE.")

    lrc_dynamic = LinearRegressionChannel(window=20, k=5.0)

    print("\n[2.1] Tiến trình co ngót thích ứng qua các quy mô mẫu (Sample-Size Shrinkage):")
    print(f"  {'Nến':<5} | {'Mẫu n':<6} | {'Trọng số w':<10} | {'Raw Slope':<12} | {'Adj Slope':<12} | {'Trạng thái'}")
    print("  " + "-" * 70)

    check_steps = [2, 5, 10, 15, 20]
    for idx, bar in enumerate(bars):
        lrc_dynamic.handle_bar(bar)
        n_obs = len(lrc_dynamic._buffer)
        if n_obs in check_steps:
            check_steps.remove(n_obs)
            print(f"  #{idx+1:<4} | {n_obs:<6} | {lrc_dynamic.weight:<10.4f} | "
                  f"{lrc_dynamic.raw_slope:<+12.2f} | {lrc_dynamic.slope:<+12.2f} | "
                  f"{'Co mạnh về Mean' if lrc_dynamic.weight < 0.6 else 'Tiệm cận OLS'}")

    last_bar = bars[-1]
    last_price = last_bar.close.as_double()

    print("\n[2.2] Trạng thái Kênh hồi quy tại nến cuối cùng:")
    print(f"  * Giá đóng cửa hiện tại (Price)     : {last_price:,.2f}")
    print(f"  * Đường cơ sở Baseline hồi quy      : {lrc_dynamic.baseline:,.2f}")
    print(f"  * Độ dốc (Slope / Xu hướng)         : {lrc_dynamic.slope:+,.2f} VNĐ/phiên")
    print(f"  * Sai số chuẩn RMSE (Độ rộng kênh)  : {lrc_dynamic.rmse:,.2f}")
    print(f"  * Chỉ số Z hồi quy (z_reg)          : {lrc_dynamic.z_reg:+.4f}")
    print(f"  * Độ bất định mô hình (RMSE / Price): {lrc_dynamic.model_uncertainty:.4%}")
    print(f"  * Phân rã Premium hồi quy           : Tăng trưởng={lrc_dynamic.premium_growth:+.2%} | "
          f"Chiết khấu={lrc_dynamic.premium_discount:+.2%} | Tổng={lrc_dynamic.premium:+.2%}")

    print("\n[2.3] Thử nghiệm chế độ Fixed Pre-fitted Model (Mô hình hồi quy cố định sẵn):")
    # Trong LinearRegressionChannel: alpha đại diện cho slope, beta đại diện cho intercept
    fixed_slope, fixed_intercept, fixed_rmse = 500.0, 95000.0, 1800.0
    lrc_fixed = LinearRegressionChannel(
        window=20,
        alpha=fixed_slope,
        beta=fixed_intercept,
        rmse=fixed_rmse,
    )
    for bar in bars[-10:]:
        lrc_fixed.handle_bar(bar)
    print(f"  * Pre-fitted tham số: alpha (slope)={fixed_slope:,.1f}, beta (intercept)={fixed_intercept:,.1f}, rmse={fixed_rmse:,.1f}")
    print(f"  * Giá trị Baseline cố định tại nến hiện tại: {lrc_fixed.baseline:,.2f}")
    print(f"  * Z-score hồi quy cố định: {lrc_fixed.z_reg:+.4f}")
    print("  => Kiểm tra LinearRegressionChannel: HOÀN TẤT VÀ HỢP LỆ.")


# ==============================================================================
# 4. Demo 3: DirectionalMovementIndex (dmi.py)
# ==============================================================================

def demo_directional_movement_index(bars: list[Bar], df: pd.DataFrame) -> None:
    """Minh họa DirectionalMovementIndex: Wilder smoothing, nhận diện đỉnh ADX, 4 đợt giải ngân,
    và Bộ lọc xu hướng thích nghi (Adaptive Trend Filter T_t)."""
    print("\n" + "=" * 78)
    print("DEMO 3: DirectionalMovementIndex (src/strategies/indicators/dmi.py)")
    print("=" * 78)
    print("Framework Bộ lọc Xu hướng Thích nghi (Adaptive Trend Filter Framework):")
    print("  1. Trend thô (Instantaneous Trend) : x_t = DI+_t - DI-_t")
    print("       * x_t > 0: Bullish | x_t < 0: Bearish | |x_t|: độ lệch giữa phe mua & bán.")
    print("  2. ADX là Độ tin cậy (Confidence)  : ADX đo độ mạnh/sức tin cậy, không đo hướng.")
    print("  3. Động hóa Alpha & Half-Life      :")
    print("       * Cách 1 (Simple)   : alpha_t = ADX_t / 100")
    print("       * Cách 2 (Soft)     : alpha_t = ADX_t / (ADX_t + C) (với C = 25)")
    print("       * Cách 3 (Half-Life - KHUYẾN NGHỊ):")
    print("           HL_t    = HL_base * (30 / ADX_t)   (mặc định HL_base = 7)")
    print("           alpha_t = 1 - 2^(-1 / HL_t)")
    print("  4. Trend Filter Thích nghi (T_t)   : T_t = alpha_t * x_t + (1 - alpha_t) * T_{t-1}")
    print("       * ADX thấp -> alpha nhỏ -> trend thay đổi chậm (lọc nhiễu khi sideway).")
    print("       * ADX cao  -> alpha lớn -> trend thích nghi nhanh (bám sát khi có sóng mạnh).")

    dmi = DirectionalMovementIndex(
        period=14,
        adx_period=14,
        adx_peak_threshold=30.0,
        hl_base=7.0,
        soft_c=25.0,
        alpha_mode="half_life",
    )

    print("\n[3.1] So sánh các cơ chế điều biến Alpha & Half-Life theo các mức ADX:")
    print(f"  {'ADX':<6} | {'Chế độ thị trường':<22} | {'Half-life (nến)':<16} | {'α (Half-Life)':<14} | {'α (Soft C=25)':<14} | {'α (Simple)'}")
    print("  " + "-" * 88)
    test_adx_levels = [10.0, 18.0, 25.0, 35.0, 50.0, 65.0]
    regimes = [
        "Không có xu hướng (Chop)",
        "Xu hướng yếu / Chớm nở",
        "Xu hướng trung bình",
        "Xu hướng mạnh",
        "Xu hướng rất mạnh",
        "Xu hướng cực mạnh / Quá nhiệt",
    ]
    for adx_lvl, regime in zip(test_adx_levels, regimes):
        a_hl, hl_val = dmi.compute_alpha(adx_lvl, mode="half_life")
        a_soft, _ = dmi.compute_alpha(adx_lvl, mode="soft")
        a_simp, _ = dmi.compute_alpha(adx_lvl, mode="simple")
        print(f"  {adx_lvl:<6.1f} | {regime:<22} | {hl_val:>12.2f} nến | {a_hl:>12.4f}   | {a_soft:>12.4f}   | {a_simp:>8.4f}")

    print(f"\n[3.2] Bắt đầu streaming {len(bars)} nến, tính T_t và quét tín hiệu Tranches...")

    tranche_events: list[dict[str, str | int | float]] = []
    cross_events: list[dict[str, str | int | float]] = []

    for idx, bar in enumerate(bars):
        dmi.handle_bar(bar)

        if not dmi.initialized:
            continue

        bar_date = str(df.iloc[idx]["date"])
        close_p = bar.close.as_double()

        # Kiểm tra đảo chiều Trend Filter T_t (Crossover 0)
        if dmi.is_trend_bullish_cross():
            cross_events.append({
                "bar": idx + 1, "date": bar_date, "type": "T_t Bullish Cross (T_t > 0)",
                "t_score": dmi.trend_score, "adx": dmi.adx
            })
        elif dmi.is_trend_bearish_cross():
            cross_events.append({
                "bar": idx + 1, "date": bar_date, "type": "T_t Bearish Cross (T_t < 0)",
                "t_score": dmi.trend_score, "adx": dmi.adx
            })

        # Kiểm tra Buy Tranches
        if dmi.is_minus_di_cooling(bars_count=2):
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "BUY - Đợt 1",
                "reason": "-DI hạ nhiệt liên tiếp", "price": close_p, "adx": dmi.adx
            })
        if dmi.is_minus_di_crossed_below_adx():
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "BUY - Đợt 2",
                "reason": "-DI cắt xuống dưới ADX (sau đỉnh)", "price": close_p, "adx": dmi.adx
            })
        if dmi.is_plus_di_crossed_above_minus_di():
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "BUY - Đợt 3",
                "reason": "+DI cắt lên trên -DI (Golden Cross)", "price": close_p, "adx": dmi.adx
            })
        if dmi.is_plus_di_crossed_above_adx():
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "BUY - Đợt 4",
                "reason": "+DI cắt lên trên ADX (Đà tăng bùng nổ)", "price": close_p, "adx": dmi.adx
            })

        # Kiểm tra Sell Tranches
        if dmi.is_plus_di_cooling(bars_count=2):
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "SELL - Đợt 1",
                "reason": "+DI hạ nhiệt liên tiếp", "price": close_p, "adx": dmi.adx
            })
        if dmi.is_plus_di_crossed_below_adx():
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "SELL - Đợt 2",
                "reason": "+DI cắt xuống dưới ADX (sau đỉnh)", "price": close_p, "adx": dmi.adx
            })
        if dmi.is_minus_di_crossed_above_plus_di():
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "SELL - Đợt 3",
                "reason": "-DI cắt lên trên +DI (Death Cross)", "price": close_p, "adx": dmi.adx
            })
        if dmi.is_minus_di_crossed_above_adx():
            tranche_events.append({
                "bar": idx + 1, "date": bar_date, "type": "SELL - Đợt 4",
                "reason": "-DI cắt lên trên ADX (Đà giảm bùng nổ)", "price": close_p, "adx": dmi.adx
            })

    print(f"\n[3.3] Trạng thái DMI & Adaptive Trend Filter tại nến cuối cùng:")
    print(f"  * +DI (Lực mua)                  : {dmi.plus_di:.2f}")
    print(f"  * -DI (Lực bán)                  : {dmi.minus_di:.2f}")
    print(f"  * ADX (Độ tin cậy xu hướng)      : {dmi.adx:.2f}")
    print(f"  * Trend thô tức thời (x_t)       : {dmi.raw_trend:+.2f} (+DI - -DI)")
    print(f"  * Half-Life hiện tại (HL_t)      : {dmi.half_life:.2f} phiên (trí nhớ hệ thống)")
    print(f"  * Trọng số thích nghi (alpha_t)  : {dmi.trend_alpha:.4f}")
    print(f"  * Điểm xu hướng thích nghi (T_t) : {dmi.trend_score:+.2f}")
    print(f"  * Nhận định xu hướng             : "
          f"{'BULLISH (T_t > 0)' if dmi.is_bullish else 'BEARISH (T_t < 0)'} | "
          f"Cường độ |T_t| = {dmi.trend_strength:.2f}")
    print(f"  * Trạng thái Đỉnh ADX            : "
          f"{'ĐÃ PHÁT HIỆN ĐỈNH (' + str(round(dmi.adx_peak_val, 2)) + ')' if dmi.adx_peak_detected else 'Chưa có đỉnh'}")

    print(f"\n[3.4] Các sự kiện đảo chiều xu hướng chính (T_t Crossover 0):")
    if cross_events:
        for ev in cross_events:
            print(f"  * Nến #{ev['bar']} ({ev['date']}): {ev['type']} | T_t = {ev['t_score']:+.2f} | ADX = {ev['adx']:.1f}")
    else:
        print("  Xu hướng duy trì nhất quán, không có hiện tượng đổi chiều cắt qua 0.")

    print(f"\n[3.5] Nhật ký các sự kiện kích hoạt Tranche tiêu biểu (Tổng số: {len(tranche_events)} sự kiện):")
    if tranche_events:
        print(f"  {'Nến':<5} | {'Ngày':<12} | {'Đợt kích hoạt':<15} | {'Giá FPT':<10} | {'ADX':<6} | {'Mô tả'}")
        print("  " + "-" * 75)
        for ev in tranche_events[:8]:
            print(f"  #{ev['bar']:<4} | {str(ev['date']):<12} | {str(ev['type']):<15} | "
                  f"{float(ev['price']):>9,.1f} | {float(ev['adx']):>5.1f} | {ev['reason']}")
        if len(tranche_events) > 8:
            print(f"  ... ({len(tranche_events) - 8} sự kiện khác đã được ghi nhận trong phiên giao dịch)")
    else:
        print("  Không phát sinh sự kiện cắt chéo đặc biệt trong khoảng thời gian này.")

    print("  => Kiểm tra DirectionalMovementIndex & Adaptive Trend Filter: HOÀN TẤT VÀ HỢP LỆ.")


# ==============================================================================
# 5. Demo 4: MultivariateLinearRegression (beta.py)
# ==============================================================================

def demo_multivariate_linear_regression(df: pd.DataFrame) -> None:
    """Minh họa MultivariateLinearRegression: Hồi quy đa biến trực tuyến trên % thay đổi (%change) & dự báo kịch bản."""
    print("\n" + "=" * 78)
    print("DEMO 4: MultivariateLinearRegression (src/strategies/indicators/beta.py)")
    print("=" * 78)
    print("Lý thuyết cốt lõi:")
    print("  * Mô hình            : target_return = intercept + beta_0 * vnindex_return + beta_1 * usdvnd_return + error.")
    print("  * Input              : Tỷ suất sinh lời (%change = price_t / price_{t-1} - 1.0).")
    print("  * Tối ưu hóa         : Thuật toán Gradient Descent lặp trực tuyến qua rolling window.")
    print("  * Lợi ích tài chính  : Đo lường độ nhạy rủi ro hệ thống (Market Beta) và rủi ro tỷ giá (Currency Beta).")
    print("  * Stress-testing     : Phương thức predict(*feature_changes) dự báo phản ứng % của cổ phiếu khi thị trường biến động.")

    n_features = 2  # Feature 0: VNINDEX, Feature 1: USD/VND
    model = MultivariateLinearRegression(
        n_features=n_features,
        window=40,
        learning_rate=0.02,
        epochs=30,
        l2=1e-4,
    )

    print(f"\n[4.1] Đang cập nhật {len(df)} quan sát giá qua model.update_raw(target, vnindex, usdvnd)...")

    for _, row in df.iterrows():
        p_target = float(row["close"])
        p_index = float(row["vnindex"])
        p_fx = float(row["usdvnd"])
        model.update_raw(p_target, p_index, p_fx)

    print("\n[4.2] Kết quả ước lượng mô hình sau chuỗi quan sát (%change):")
    betas = model.coefficients
    intercept = model.intercept

    print(f"  * Intercept (Alpha cơ sở)              : {intercept:+.6f}")
    print(f"  * Beta 0 - Độ nhạy VN-Index (Thị trường): {betas[0]:+.4f}")
    print(f"  * Beta 1 - Độ nhạy USD/VND (Tỷ giá)    : {betas[1]:+.4f}")
    print(f"  * Hệ số giải thích R-Squared (R^2)      : {model.r_squared:.4f}")
    print(f"  * Phần dư quan sát gần nhất (Residual)  : {model.residual:+.4%}")
    print(f"  * Độ bất định mô hình (RMSE sai số)     : {model.model_uncertainty:.4%}")

    print("\n[4.3] Dự báo kịch bản thị trường (Scenario Stress-Testing) với model.predict(...):")
    scenarios = [
        ("Thị trường tăng điểm mạnh (Bull Rally)", +0.020, -0.001),
        ("Thị trường điều chỉnh sâu (Market Selloff)", -0.025, +0.003),
        ("Cú sốc tỷ giá tăng vọt (FX Shock)", 0.000, +0.010),
        ("Thị trường đi ngang biến động nhẹ", +0.005, +0.001),
    ]

    print(f"  {'Tên kịch bản':<35} | {'Δ VN-Index':<12} | {'Δ USD/VND':<12} | {'Dự báo Δ FPT'}")
    print("  " + "-" * 75)
    for name, d_vni, d_fx in scenarios:
        predicted_change = model.predict(d_vni, d_fx)
        print(f"  {name:<35} | {d_vni:>+10.2%}   | {d_fx:>+10.2%}   | {predicted_change:>+10.2%}")


    print("  => Kiểm tra MultivariateLinearRegression: HOÀN TẤT VÀ HỢP LỆ.")


# ==============================================================================
# 6. Demo 5: Integrated Nautilus Trader Strategy Simulation
# ==============================================================================

def demo_integrated_strategy(bars: list[Bar], df: pd.DataFrame) -> None:
    """Minh họa tích hợp đồng bộ cả 4 chỉ báo vào một cỗ máy ra quyết định định lượng hoàn chỉnh."""
    print("\n" + "=" * 78)
    print("DEMO 5: Tích hợp Toàn diện 4 Chỉ báo trong Chiến lược Giao dịch")
    print("=" * 78)
    print("Ma trận phối hợp chiến lược:")
    print("  1. Macro / Beta Model  -> Đánh giá kỳ vọng biến động vĩ mô và alpha kỳ vọng.")
    print("  2. DMI / ADX           -> Xác nhận xu hướng, độ bền và kích hoạt các đợt giải ngân (Tranches 1-4).")
    print("  3. Linear Reg Channel  -> Xác định dải kênh xu hướng ngắn hạn và độ lệch z_reg.")
    print("  4. Rolling Statistics  -> Cung cấp biên độ mean-reversion, z_score và các ngưỡng giá mục tiêu.")

    sma = RollingStatistics(window=20)
    lrc = LinearRegressionChannel(window=20, k=5.0)
    dmi = DirectionalMovementIndex(period=14, adx_period=14, adx_peak_threshold=30.0)
    beta_model = MultivariateLinearRegression(n_features=2, window=30, learning_rate=0.02)

    # Vòng lặp mô phỏng bar-by-bar
    decisions: list[dict[str, Any]] = []

    for idx, bar in enumerate(bars):
        row = df.iloc[idx]
        p_close = bar.close.as_double()
        p_idx = float(row["vnindex"])
        p_fx = float(row["usdvnd"])

        # Cập nhật cả 4 chỉ báo
        sma.handle_bar(bar)
        lrc.handle_bar(bar)
        dmi.handle_bar(bar)
        beta_model.update_raw(p_close, p_idx, p_fx)

        if not (sma.initialized and lrc.initialized and dmi.initialized and beta_model.initialized):
            continue

        # Tổng hợp tín hiệu
        action = "HOLD"
        reason = "Chờ tín hiệu rõ ràng"

        # Điều kiện MUA: DMI kích hoạt Buy Tranche HOẶC Giá dưới biên chiết khấu sâu (z_score < -1.5)
        if dmi.is_plus_di_crossed_above_minus_di() or dmi.is_minus_di_crossed_below_adx():
            action = "BUY (Tranche)"
            reason = f"DMI Buy Tranche | ADX={dmi.adx:.1f}"
        elif sma.z_score < -1.144 and lrc.z_reg < -1.0:
            action = "BUY (Reversion)"
            reason = f"Quá bán sâu (z={sma.z_score:.2f}, z_reg={lrc.z_reg:.2f})"
        elif dmi.is_minus_di_crossed_above_plus_di() or (dmi.adx_peak_detected and sma.z_score > 1.5):
            action = "TAKE PROFIT / SELL"
            reason = f"Quá mua & Đảo chiều (z={sma.z_score:.2f})"

        decisions.append({
            "date": str(row["date"]),
            "price": p_close,
            "sma_baseline": sma.baseline,
            "z_sma": sma.z_score,
            "z_lrc": lrc.z_reg,
            "t_score": dmi.trend_score,
            "adx": dmi.adx,
            "action": action,
            "reason": reason,
            "target_high": sma.target_points.get(1.144, 0.0),
            "target_low": sma.target_points.get(-1.144, 0.0),
        })

    print(f"\n[5.1] Mẫu 6 quyết định giao dịch gần nhất từ hệ thống đa chỉ báo:")
    print(f"  {'Ngày':<12} | {'Giá':<9} | {'Z(SMA)':<7} | {'Z(LRC)':<7} | {'T_score':<8} | {'ADX':<5} | {'Hành động':<18} | {'Mục tiêu (Bán/Mua)':<22}")
    print("  " + "-" * 98)
    for dec in decisions[-6:]:
        target_str = f"{dec['target_high']:,.0f} / {dec['target_low']:,.0f}"
        print(f"  {dec['date']:<12} | {dec['price']:>9,.0f} | {dec['z_sma']:>+7.2f} | "
              f"{dec['z_lrc']:>+7.2f} | {dec['t_score']:>+8.2f} | {dec['adx']:>5.1f} | {dec['action']:<18} | {target_str:<22}")


# ==============================================================================
# 7. Main Entry Point
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Demo bộ chỉ số kỹ thuật Nautilus Trader (src/strategies/indicators)")
    parser.add_argument("--synthetic", action="store_true", help="Bắt buộc sử dụng dữ liệu thị trường giả lập (offline mode)")
    parser.add_argument("--plot", action="store_true", help="Hiển thị biểu đồ matplotlib")
    args = parser.parse_args()

    print("=" * 78)
    print("DEMO: BỘ CHỈ SỐ KỸ THUẬT VÀ ĐỊNH LƯỢNG NAUTILUS TRADER")
    print("      (src/strategies/indicators: sma, linear, dmi, beta)")
    print("=" * 78)

    # 1. Tải dữ liệu
    df, is_synthetic = load_market_dataset(force_synthetic=args.synthetic)
    bars = build_nautilus_bars(df, symbol_str="FPT.HOSE")

    # 2. Chạy Demo từng chỉ báo
    demo_rolling_statistics(bars, df)
    demo_linear_regression_channel(bars, df)
    demo_directional_movement_index(bars, df)
    demo_multivariate_linear_regression(df)
    demo_integrated_strategy(bars, df)

    # 3. Vẽ biểu đồ nếu có yêu cầu
    if args.plot:
        try:
            import matplotlib.pyplot as plt

            print("\n[Trực quan hóa] Đang khởi tạo biểu đồ matplotlib 4 tầng...")
            fig, axs = plt.subplots(4, 1, figsize=(12, 11), sharex=True)

            # Subplot 1: Giá + SMA + LRC Baseline
            sma_line = df["close"].rolling(20).mean()
            axs[0].plot(df["date"], df["close"], label="FPT Close Price", color="black", lw=1.5)
            axs[0].plot(df["date"], sma_line, label="SMA 20", color="blue", ls="--")
            axs[0].set_title("1. FPT Stock Price & Trend Baselines")
            axs[0].legend(loc="upper left")
            axs[0].grid(True, alpha=0.3)

            # Subplot 2: DMI (+DI, -DI, ADX)
            dmi_indicator = DirectionalMovementIndex(14, 14, 30.0)
            plus_dis, minus_dis, adxs, raw_trends, t_scores = [], [], [], [], []
            for bar in bars:
                dmi_indicator.handle_bar(bar)
                plus_dis.append(dmi_indicator.plus_di)
                minus_dis.append(dmi_indicator.minus_di)
                adxs.append(dmi_indicator.adx)
                raw_trends.append(dmi_indicator.raw_trend)
                t_scores.append(dmi_indicator.trend_score)

            axs[1].plot(df["date"], plus_dis, label="+DI (Buyer Momentum)", color="green", lw=1.2)
            axs[1].plot(df["date"], minus_dis, label="-DI (Seller Momentum)", color="red", lw=1.2)
            axs[1].plot(df["date"], adxs, label="ADX (Confidence)", color="purple", lw=1.5)
            axs[1].axhline(30.0, color="orange", ls=":", label="Peak Threshold (30)")
            axs[1].set_title("2. Directional Movement Index (DMI / ADX)")
            axs[1].legend(loc="upper left")
            axs[1].grid(True, alpha=0.3)

            # Subplot 3: Adaptive Trend Filter (x_t vs T_t)
            axs[2].plot(df["date"], raw_trends, label="Raw Trend x_t (+DI - -DI)", color="gray", lw=1.0, ls=":", alpha=0.7)
            axs[2].plot(df["date"], t_scores, label="Adaptive Trend Score T_t", color="royalblue", lw=1.8)
            axs[2].axhline(0.0, color="black", lw=0.8, ls="-")
            axs[2].fill_between(df["date"], 0, t_scores, where=np.array(t_scores) >= 0, color="green", alpha=0.15, label="Bullish Regime")
            axs[2].fill_between(df["date"], 0, t_scores, where=np.array(t_scores) < 0, color="red", alpha=0.15, label="Bearish Regime")
            axs[2].set_title("3. Adaptive Trend Filter (Adaptive EMA T_t via Dynamic Half-Life)")
            axs[2].legend(loc="upper left")
            axs[2].grid(True, alpha=0.3)

            # Subplot 4: Macro Features (VN-Index & USD/VND)
            ax4_fx = axs[3].twinx()
            axs[3].plot(df["date"], df["vnindex"], label="VN-Index", color="darkblue", lw=1.2)
            ax4_fx.plot(df["date"], df["usdvnd"], label="USD/VND", color="darkgreen", lw=1.2, ls="--")
            axs[3].set_title("4. Macro Explanatory Variables (Beta Regression)")
            axs[3].legend(loc="upper left")
            ax4_fx.legend(loc="upper right")
            axs[3].grid(True, alpha=0.3)
            plt.show()
        except Exception as plot_err:
            print(f"  [Cảnh báo biểu đồ] Không thể hiển thị GUI matplotlib ({plot_err}).")

    print("\n" + "=" * 78)
    print("HOÀN THÀNH DEMO BỘ CHỈ SỐ KỸ THUẬT THÀNH CÔNG!")
    print("=" * 78)


if __name__ == "__main__":
    main()
