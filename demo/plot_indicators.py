"""Demo kiểm tra và trực quan hóa dữ liệu chỉ số kỹ thuật và thị trường
sử dụng tiện ích plot_series_groups từ src.utils.plot.

Usage:
    # 1. Chế độ kiểm tra toàn diện (mặc định)
    python3 demo/plot_indicators.py

    # 2. Lưu ảnh ra file
    python3 demo/plot_indicators.py --save demo/indicators_chart.png

    # 3. Chạy offline với dữ liệu giả lập
    python3 demo/plot_indicators.py --synthetic --save demo/synthetic_chart.png

    # 4. Các chế độ xem chuyên sâu:
    python3 demo/plot_indicators.py --mode dmi        # Kiểm tra riêng DMI & Adaptive Trend Filter
    python3 demo/plot_indicators.py --mode channels   # Kiểm tra Kênh SMA & Kênh hồi quy LRC
    python3 demo/plot_indicators.py --mode ohlcv      # Kiểm tra nến OHLCV & Volume
    python3 demo/plot_indicators.py --mode zscore     # Kiểm tra Z-Score & Premium
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import numpy as np
import pandas as pd

from src.strategies.indicators import (
    DirectionalMovementIndex,
    LinearRegressionChannel,
    MultivariateLinearRegression,
    RollingStatistics,
)
from src.utils.plot import plot_series_groups
from demo.demo_indicators import build_nautilus_bars, load_market_dataset


def extract_indicator_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Tính toán toàn bộ các chỉ báo kỹ thuật trên chuỗi dữ liệu
    và trả về dictionary chứa các pd.Series có nhãn rõ ràng để vẽ đồ thị.
    """
    bars = build_nautilus_bars(df, symbol_str="FPT.HOSE")
    dt_index = pd.to_datetime(df["date"])

    sma = RollingStatistics(
        window=20,
        strategic_levels=(2.0, 1.144, 0.472, 0.0, -0.472, -1.144, -2.0),
    )
    lrc = LinearRegressionChannel(window=20, k=5.0)
    dmi = DirectionalMovementIndex(
        period=14,
        adx_period=14,
        adx_peak_threshold=30.0,
        hl_base=7.0,
        soft_c=25.0,
        alpha_mode="half_life",
    )
    beta = MultivariateLinearRegression(
        n_features=2,
        window=30,
        learning_rate=0.02,
    )

    # Khởi tạo các mảng lưu trữ giá trị
    sma_baseline = []
    sma_std = []
    sma_z = []
    sma_growth = []
    sma_discount = []
    sma_premium = []
    sma_tgt_p2 = []
    sma_tgt_m2 = []
    sma_tgt_p1 = []
    sma_tgt_m1 = []

    lrc_baseline = []
    lrc_slope = []
    lrc_rmse = []
    lrc_z = []
    lrc_upper = []
    lrc_lower = []

    dmi_plus = []
    dmi_minus = []
    dmi_adx = []
    dmi_raw_trend = []
    dmi_t_score = []
    dmi_half_life = []
    dmi_alpha = []

    beta_residual = []
    beta_pred = []

    # Streaming từng nến qua các chỉ báo
    for idx, bar in enumerate(bars):
        row = df.iloc[idx]
        p_close = bar.close.as_double()
        p_index = float(row["vnindex"])
        p_fx = float(row["usdvnd"])

        sma.handle_bar(bar)
        lrc.handle_bar(bar)
        dmi.handle_bar(bar)
        beta.update_raw(p_close, p_index, p_fx)

        # 1. SMA
        sma_baseline.append(sma.baseline if sma.initialized else np.nan)
        sma_std.append(sma.std if sma.initialized else np.nan)
        sma_z.append(sma.z_score if sma.initialized else np.nan)
        sma_growth.append(sma.premium_growth if sma.initialized else np.nan)
        sma_discount.append(sma.premium_discount if sma.initialized else np.nan)
        sma_premium.append(sma.premium if sma.initialized else np.nan)
        sma_tgt_p2.append(sma.target_points.get(2.0, np.nan) if sma.initialized else np.nan)
        sma_tgt_m2.append(sma.target_points.get(-2.0, np.nan) if sma.initialized else np.nan)
        sma_tgt_p1.append(sma.target_points.get(1.144, np.nan) if sma.initialized else np.nan)
        sma_tgt_m1.append(sma.target_points.get(-1.144, np.nan) if sma.initialized else np.nan)

        # 2. LRC
        lrc_baseline.append(lrc.baseline if lrc.initialized else np.nan)
        lrc_slope.append(lrc.slope if lrc.initialized else np.nan)
        lrc_rmse.append(lrc.rmse if lrc.initialized else np.nan)
        lrc_z.append(lrc.z_reg if lrc.initialized else np.nan)
        lrc_upper.append(lrc.baseline + lrc.rmse if lrc.initialized else np.nan)
        lrc_lower.append(lrc.baseline - lrc.rmse if lrc.initialized else np.nan)

        # 3. DMI & Adaptive Trend
        dmi_plus.append(dmi.plus_di if dmi.initialized else np.nan)
        dmi_minus.append(dmi.minus_di if dmi.initialized else np.nan)
        dmi_adx.append(dmi.adx if dmi.initialized else np.nan)
        dmi_raw_trend.append(dmi.raw_trend if dmi.initialized else np.nan)
        dmi_t_score.append(dmi.trend_score if dmi.initialized else np.nan)
        dmi_half_life.append(dmi.half_life if dmi.initialized else np.nan)
        dmi_alpha.append(dmi.trend_alpha if dmi.initialized else np.nan)

        # 4. Beta
        beta_residual.append(beta.residual if beta.initialized else np.nan)
        beta_pred.append(beta.predicted_change if beta.initialized else np.nan)

    # Đóng gói thành dict các pd.Series
    return {
        # OHLCV
        "open": pd.Series(df["open"].values, index=dt_index, name="Open"),
        "high": pd.Series(df["high"].values, index=dt_index, name="High"),
        "low": pd.Series(df["low"].values, index=dt_index, name="Low"),
        "close": pd.Series(df["close"].values, index=dt_index, name="Close (FPT)"),
        "volume": pd.Series(df["volume"].values, index=dt_index, name="Volume"),
        # Macro
        "vnindex": pd.Series(df["vnindex"].values, index=dt_index, name="VN-Index"),
        "usdvnd": pd.Series(df["usdvnd"].values, index=dt_index, name="USD/VND"),
        # SMA
        "sma_baseline": pd.Series(sma_baseline, index=dt_index, name="SMA 20"),
        "sma_tgt_p2": pd.Series(sma_tgt_p2, index=dt_index, name="SMA +2.0 STD"),
        "sma_tgt_m2": pd.Series(sma_tgt_m2, index=dt_index, name="SMA -2.0 STD"),
        "sma_tgt_p1": pd.Series(sma_tgt_p1, index=dt_index, name="SMA +1.144 STD"),
        "sma_tgt_m1": pd.Series(sma_tgt_m1, index=dt_index, name="SMA -1.144 STD"),
        "sma_z": pd.Series(sma_z, index=dt_index, name="Z-Score (SMA)"),
        "sma_premium": pd.Series(sma_premium, index=dt_index, name="Total Premium"),
        "sma_growth": pd.Series(sma_growth, index=dt_index, name="Premium Growth"),
        "sma_discount": pd.Series(sma_discount, index=dt_index, name="Premium Discount"),
        # LRC
        "lrc_baseline": pd.Series(lrc_baseline, index=dt_index, name="LRC Baseline"),
        "lrc_upper": pd.Series(lrc_upper, index=dt_index, name="LRC Upper (+RMSE)"),
        "lrc_lower": pd.Series(lrc_lower, index=dt_index, name="LRC Lower (-RMSE)"),
        "lrc_z": pd.Series(lrc_z, index=dt_index, name="Z-Reg (LRC)"),
        "lrc_slope": pd.Series(lrc_slope, index=dt_index, name="LRC Slope"),
        # DMI & Adaptive Trend
        "plus_di": pd.Series(dmi_plus, index=dt_index, name="+DI (Buyer Momentum)"),
        "minus_di": pd.Series(dmi_minus, index=dt_index, name="-DI (Seller Momentum)"),
        "adx": pd.Series(dmi_adx, index=dt_index, name="ADX (Confidence)"),
        "raw_trend": pd.Series(dmi_raw_trend, index=dt_index, name="Raw Trend x_t"),
        "trend_score": pd.Series(dmi_t_score, index=dt_index, name="Adaptive Trend Score T_t"),
        "half_life": pd.Series(dmi_half_life, index=dt_index, name="Half-Life HL_t"),
        "trend_alpha": pd.Series(dmi_alpha, index=dt_index, name="Alpha_t"),
        # Beta
        "beta_residual": pd.Series(beta_residual, index=dt_index, name="Beta Residual"),
        "beta_pred": pd.Series(beta_pred, index=dt_index, name="Predicted Change"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo kiểm tra dữ liệu bằng tiện ích plot_series_groups (src/utils/plot.py)"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "dmi", "channels", "ohlcv", "zscore"],
        default="full",
        help="Chế độ trực quan hóa: full (toàn bộ 5 tầng), dmi, channels, ohlcv, zscore",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Sử dụng dữ liệu giả lập thay vì tải trực tuyến",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Đường dẫn lưu file ảnh (ví dụ: demo/plot_output.png)",
    )
    parser.add_argument(
        "--width",
        type=float,
        default=12.0,
        help="Chiều rộng hình vẽ (inches)",
    )
    parser.add_argument(
        "--height",
        type=float,
        default=None,
        help="Chiều cao hình vẽ (inches)",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("DEMO TRỰC QUAN HÓA & KIỂM TRA DỮ LIỆU VỚI src/utils/plot.py")
    print(f"Chế độ hiển thị: {args.mode.upper()} | Lưu file: {args.save or 'Không (chỉ hiển thị GUI)'}")
    print("=" * 78)

    # 1. Tải dữ liệu
    df, is_synthetic = load_market_dataset(force_synthetic=args.synthetic)
    print(f"  Dữ liệu đầu vào: {len(df)} hàng từ {df.iloc[0]['date']} đến {df.iloc[-1]['date']}.")

    # 2. Tính toán series
    print("  Đang tính toán các chuỗi chỉ báo kỹ thuật...")
    s = extract_indicator_series(df)

    # 3. Thiết lập nhóm đồ thị theo chế độ
    groups: list[list[pd.Series | list[pd.Series]]] = []
    default_h = 10.0

    if args.mode == "full":
        default_h = 14.0
        # Hàng 1: Giá + SMA + Kênh hồi quy LRC (trục chính), Volume (trục phụ twinx)
        row1 = [
            [s["close"], s["sma_baseline"], s["lrc_baseline"], s["sma_tgt_p2"], s["sma_tgt_m2"]],
            s["volume"],
        ]
        # Hàng 2: DMI (+DI, -DI trên trục chính, ADX trên trục phụ twinx)
        row2 = [
            [s["plus_di"], s["minus_di"]],
            s["adx"],
        ]
        # Hàng 3: Trend thô x_t & Trend lọc T_t (trục chính), Half-Life HL_t (trục phụ twinx)
        row3 = [
            [s["raw_trend"], s["trend_score"]],
            s["half_life"],
        ]
        # Hàng 4: Z-Scores (trục chính), Total Premium (trục phụ twinx)
        row4 = [
            [s["sma_z"], s["lrc_z"]],
            s["sma_premium"],
        ]
        # Hàng 5: VN-Index (trục chính) và USD/VND (trục phụ twinx)
        row5 = [
            s["vnindex"],
            s["usdvnd"],
        ]
        groups = [row1, row2, row3, row4, row5]

    elif args.mode == "dmi":
        default_h = 8.0
        # Kiểm tra chi tiết DMI và Bộ lọc xu hướng thích nghi
        row1 = [
            [s["plus_di"], s["minus_di"]],
            s["adx"],
        ]
        row2 = [
            [s["raw_trend"], s["trend_score"]],
            s["half_life"],
        ]
        groups = [row1, row2]

    elif args.mode == "channels":
        default_h = 10.0
        # So sánh chi tiết kênh SMA vs Kênh hồi quy LRC
        row1 = [
            [s["close"], s["sma_baseline"], s["sma_tgt_p2"], s["sma_tgt_m2"], s["sma_tgt_p1"], s["sma_tgt_m1"]],
        ]
        row2 = [
            [s["close"], s["lrc_baseline"], s["lrc_upper"], s["lrc_lower"]],
        ]
        row3 = [
            s["sma_z"],
            s["lrc_z"],
        ]
        groups = [row1, row2, row3]

    elif args.mode == "ohlcv":
        default_h = 8.0
        # Kiểm tra nến OHLC và Volume
        row1 = [
            [s["open"], s["high"], s["low"], s["close"]],
        ]
        row2 = [
            s["volume"],
        ]
        groups = [row1, row2]

    elif args.mode == "zscore":
        default_h = 8.0
        # Kiểm tra Z-score và Premium
        row1 = [
            [s["close"], s["sma_baseline"]],
        ]
        row2 = [
            [s["sma_z"], s["lrc_z"]],
            [s["sma_growth"], s["sma_discount"], s["sma_premium"]],
        ]
        groups = [row1, row2]

    figsize = (args.width, args.height if args.height is not None else default_h)

    # 4. Gọi hàm tiện ích plot_series_groups
    print(f"  Gọi plot_series_groups với {len(groups)} hàng đồ thị, kích thước {figsize}...")
    plot_series_groups(
        *groups,
        figsize=figsize,
        save_path=args.save,
    )

    if args.save:
        print(f"  => Đã lưu thành công biểu đồ kiểm tra dữ liệu tại: {args.save}")
    print("=" * 78)
    print("HOÀN TẤT KIỂM TRA DỮ LIỆU BẰNG BIỂU ĐỒ!")
    print("=" * 78)


if __name__ == "__main__":
    main()
