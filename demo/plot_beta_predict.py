"""Demo trực quan hóa & so sánh Dự báo phần trăm thay đổi (Predict target %change)
với Giá thực tế (Actual Price) sử dụng MultivariateLinearRegression và src/utils/plot.py.

Kịch bản so sánh:
1. Actual %Change (r_t) vs Predicted %Change (r_hat_t).
2. Actual Price (P_t) vs One-step Ahead Predicted Price (P_hat_t = P_{t-1} * (1 + r_hat_t)).
3. Actual Price Trajectory vs Cumulative Model Price (P_0 * prod(1 + r_hat)).
4. Sai lệch dự báo: Residuals (r_t - r_hat_t) và Sai lệch giá (P_t - P_hat_t).
5. Hệ số Beta động theo thời gian: Market Beta (VN-Index) & Currency Beta (USD/VND).

Usage:
    # 1. Chạy với dữ liệu trực tuyến thực tế (FPT, VN-Index, USD/VND)
    python3 demo/plot_beta_predict.py

    # 2. Chạy offline với dữ liệu giả lập (synthetic)
    python3 demo/plot_beta_predict.py --synthetic

    # 3. Lưu ảnh biểu đồ phân tích ra file
    python3 demo/plot_beta_predict.py --save demo/beta_predict_comparison.png
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import numpy as np
import pandas as pd

from demo.demo_indicators import load_market_dataset
from src.strategies.indicators.beta import MultivariateLinearRegression
from src.utils.plot import plot_series_groups


def run_beta_prediction_analysis(
    df: pd.DataFrame,
    window: int = 30,
    learning_rate: float = 0.02,
    epochs: int = 30,
    l2: float = 1e-4,
) -> tuple[dict[str, pd.Series], dict[str, float]]:
    """Chạy mô hình hồi quy đa biến trực tuyến trên chuỗi dữ liệu,
    trích xuất các chuỗi so sánh và tính toán các chỉ số thống kê định lượng.
    """
    dt_index = pd.to_datetime(df["date"])
    model = MultivariateLinearRegression(
        n_features=2,
        window=window,
        learning_rate=learning_rate,
        epochs=epochs,
        l2=l2,
    )

    actual_prices: list[float] = []
    pred_prices_1step: list[float] = []
    cum_model_prices: list[float] = []
    actual_returns: list[float] = []
    pred_returns: list[float] = []
    residuals: list[float] = []
    price_errors: list[float] = []

    beta_vni: list[float] = []
    beta_fx: list[float] = []
    r_squared_list: list[float] = []

    p_init = float(df.iloc[0]["close"])
    cum_p = p_init

    for idx, row in df.iterrows():
        p_target = float(row["close"])
        p_vni = float(row["vnindex"])
        p_fx = float(row["usdvnd"])

        model.update_raw(p_target, p_vni, p_fx)
        actual_prices.append(p_target)

        if model.initialized:
            r_act = model.actual_change
            r_pred = model.predicted_change
            actual_returns.append(r_act)
            pred_returns.append(r_pred)
            residuals.append(model.residual)

            # Giá dự báo 1 bước: P_hat_t = P_{t-1} * (1 + r_hat_t)
            p_prev = float(df.iloc[idx - 1]["close"])
            p_hat_1step = p_prev * (1.0 + r_pred)
            pred_prices_1step.append(p_hat_1step)
            price_errors.append(p_target - p_hat_1step)

            # Quỹ đạo giá tích lũy theo mô hình: P_model_t = P_prev_model * (1 + r_hat_t)
            cum_p = cum_p * (1.0 + r_pred)
            cum_model_prices.append(cum_p)

            # Betas & R2
            coefs = model.coefficients
            beta_vni.append(float(coefs[0]))
            beta_fx.append(float(coefs[1]))
            r_squared_list.append(model.r_squared)
        else:
            actual_returns.append(np.nan)
            pred_returns.append(np.nan)
            residuals.append(np.nan)
            pred_prices_1step.append(np.nan)
            price_errors.append(np.nan)
            cum_model_prices.append(np.nan)
            beta_vni.append(np.nan)
            beta_fx.append(np.nan)
            r_squared_list.append(np.nan)

    # Đóng gói Series
    series_dict = {
        # Giá
        "actual_price": pd.Series(actual_prices, index=dt_index, name="Actual Price (FPT)"),
        "pred_price_1step": pd.Series(pred_prices_1step, index=dt_index, name="Pred Price (1-Step Ahead)"),
        "cum_model_price": pd.Series(cum_model_prices, index=dt_index, name="Cum Model Price Trajectory"),
        # Tỷ suất sinh lời (%change)
        "actual_return_pct": pd.Series(np.array(actual_returns) * 100.0, index=dt_index, name="Actual %Change (%)"),
        "pred_return_pct": pd.Series(np.array(pred_returns) * 100.0, index=dt_index, name="Pred %Change (%)"),
        # Sai lệch
        "return_residual_pct": pd.Series(np.array(residuals) * 100.0, index=dt_index, name="Return Residual (%)"),
        "price_error_vnd": pd.Series(price_errors, index=dt_index, name="Price Error (P - P_hat, VNĐ)"),
        # Hệ số nhạy cảm Beta
        "beta_vni": pd.Series(beta_vni, index=dt_index, name="Beta VN-Index"),
        "beta_fx": pd.Series(beta_fx, index=dt_index, name="Beta USD/VND"),
        "r_squared": pd.Series(r_squared_list, index=dt_index, name="Rolling R-Squared"),
    }

    # Thống kê hiệu năng
    valid_mask = ~np.isnan(pred_returns)
    r_act_arr = np.array(actual_returns)[valid_mask]
    r_pred_arr = np.array(pred_returns)[valid_mask]
    p_act_arr = np.array(actual_prices)[valid_mask]
    p_pred_arr = np.array(pred_prices_1step)[valid_mask]

    corr = float(np.corrcoef(r_act_arr, r_pred_arr)[0, 1]) if len(r_act_arr) > 1 else 0.0
    hit_rate = float(np.mean(np.sign(r_act_arr) == np.sign(r_pred_arr)))
    mae_pct = float(np.mean(np.abs(r_act_arr - r_pred_arr)))
    rmse_pct = float(np.sqrt(np.mean((r_act_arr - r_pred_arr) ** 2)))
    mae_price = float(np.mean(np.abs(p_act_arr - p_pred_arr)))
    rmse_price = float(np.sqrt(np.mean((p_act_arr - p_pred_arr) ** 2)))
    mean_r2 = float(np.nanmean(r_squared_list))
    mean_beta_vni = float(np.nanmean(beta_vni))
    mean_beta_fx = float(np.nanmean(beta_fx))

    metrics = {
        "sample_size": float(len(r_act_arr)),
        "correlation": corr,
        "hit_rate": hit_rate,
        "mae_pct": mae_pct,
        "rmse_pct": rmse_pct,
        "mae_price": mae_price,
        "rmse_price": rmse_price,
        "mean_r2": mean_r2,
        "mean_beta_vni": mean_beta_vni,
        "mean_beta_fx": mean_beta_fx,
    }

    return series_dict, metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo plot & so sánh Predict target %change VS Price (MultivariateLinearRegression)"
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Sử dụng dữ liệu giả lập (offline mode)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=30,
        help="Cửa sổ trượt rolling window (mặc định: 30 phiên)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=0.02,
        help="Tốc độ học gradient descent (mặc định: 0.02)",
    )

    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Đường dẫn lưu file ảnh (ví dụ: demo/beta_predict_chart.png)",
    )
    parser.add_argument(
        "--width",
        type=float,
        default=12.0,
        help="Chiều rộng biểu đồ (inches)",
    )
    parser.add_argument(
        "--height",
        type=float,
        default=13.0,
        help="Chiều cao biểu đồ (inches)",
    )
    args = parser.parse_args()

    print("=" * 82)
    print("DEMO TRỰC QUAN HÓA & SO SÁNH: PREDICT TARGET %CHANGE VS ACTUAL PRICE")
    print("              (MultivariateLinearRegression & src/utils/plot.py)")
    print("=" * 82)

    # 1. Nạp dữ liệu
    df, is_synthetic = load_market_dataset(force_synthetic=args.synthetic)
    print(f"  Dữ liệu thị trường: {len(df)} phiên ({df.iloc[0]['date']} -> {df.iloc[-1]['date']}).")

    # 2. Chạy mô hình và trích xuất dữ liệu so sánh
    print("  Đang chạy mô hình hồi quy đa biến và tái thiết lập chuỗi giá...")
    series_dict, metrics = run_beta_prediction_analysis(
        df=df,
        window=args.window,
        learning_rate=args.lr,
        epochs=30,
    )

    # 3. In bảng thống kê định lượng
    print("\n" + "-" * 82)
    print("BẢNG ĐÁNH GIÁ ĐỘ CHÍNH XÁC & TƯƠNG QUAN DỰ BÁO:")
    print("-" * 82)
    print(f"  * Số phiên kiểm định có dự báo          : {int(metrics['sample_size'])} phiên")
    print(f"  * Hệ số tương quan Corr(r, r_hat)      : {metrics['correlation']:+.4f} (đo độ nhạy theo đà thị trường)")
    print(f"  * Tỷ lệ dự báo đúng hướng (Hit Rate)   : {metrics['hit_rate']:.2%} (xác suất đoán đúng phiên TĂNG/GIẢM)")
    print(f"  * Hệ số giải thích R-Squared trung bình : {metrics['mean_r2']:.4f}")
    print(f"  * Sai số tuyệt đối MAE theo % sinh lời : {metrics['mae_pct']:.4%}")
    print(f"  * Sai số chuẩn RMSE theo % sinh lời    : {metrics['rmse_pct']:.4%}")
    print(f"  * Sai số tuyệt đối MAE theo Giá (VNĐ)  : {metrics['mae_price']:,.1f} VNĐ / phiên")
    print(f"  * Sai số chuẩn RMSE theo Giá (VNĐ)     : {metrics['rmse_price']:,.1f} VNĐ / phiên")
    print(f"  * Market Beta trung bình (VN-Index)    : {metrics['mean_beta_vni']:+.4f}")
    print(f"  * Currency Beta trung bình (USD/VND)   : {metrics['mean_beta_fx']:+.4f}")

    # 4. In bảng so sánh chi tiết 8 phiên gần nhất
    print("\n" + "-" * 82)
    print("BẢNG SO SÁNH CHI TIẾT 8 PHIÊN GẦN NHẤT (GIÁ & %CHANGE):")
    print("-" * 82)
    print(f"  {'Ngày':<12} | {'Giá Thực':<10} | {'Giá Dự Báo':<10} | {'Lệch Giá (VNĐ)':<14} | {'%Thực':<8} | {'%Dự Báo':<8} | {'Hướng'}")
    print("  " + "-" * 82)

    tail_indices = df.index[-8:]
    for idx in tail_indices:
        d_str = str(df.iloc[idx]["date"])
        p_act = series_dict["actual_price"].iloc[idx]
        p_pred = series_dict["pred_price_1step"].iloc[idx]
        err_vnd = series_dict["price_error_vnd"].iloc[idx]
        r_act_pct = series_dict["actual_return_pct"].iloc[idx]
        r_pred_pct = series_dict["pred_return_pct"].iloc[idx]

        same_direction = (r_act_pct * r_pred_pct >= 0) if (not np.isnan(r_act_pct) and not np.isnan(r_pred_pct)) else False
        dir_icon = "ĐÚNG" if same_direction else "SAI"

        print(f"  {d_str:<12} | {p_act:>10,.0f} | {p_pred:>10,.0f} | {err_vnd:>+14,.0f} | "
              f"{r_act_pct:>+7.2f}% | {r_pred_pct:>+7.2f}% | {dir_icon}")

    # 5. Cấu hình các tầng đồ thị hiển thị qua plot_series_groups
    print("\n" + "-" * 82)
    print("KHỞI TẠO BIỂU ĐỒ 4 TẦNG SO SÁNH VỚI src/utils/plot.py...")
    print("-" * 82)

    # Tầng 1: So sánh Giá (Giá thực tế vs Giá dự báo 1 bước vs Quỹ đạo giá mô hình)
    row1 = [
        [
            series_dict["actual_price"],
            series_dict["pred_price_1step"],
            series_dict["cum_model_price"],
        ]
    ]

    # Tầng 2: So sánh Tỷ suất sinh lời %Change (Actual %Change vs Pred %Change)
    row2 = [
        [
            series_dict["actual_return_pct"],
            series_dict["pred_return_pct"],
        ]
    ]

    # Tầng 3: Sai lệch dự báo (Phần dư Return Residual % bên trái, Sai số giá VNĐ bên phải twinx)
    row3 = [
        series_dict["return_residual_pct"],
        series_dict["price_error_vnd"],
    ]

    # Tầng 4: Độ nhạy Factor Betas (Market Beta VN-Index bên trái, Currency Beta USD/VND bên phải twinx)
    row4 = [
        series_dict["beta_vni"],
        series_dict["beta_fx"],
    ]

    figsize = (args.width, args.height)
    plot_series_groups(
        row1,
        row2,
        row3,
        row4,
        figsize=figsize,
        save_path=args.save,
    )

    if args.save:
        print(f"  => Đã lưu thành công biểu đồ phân tích so sánh tại: {args.save}")
    print("=" * 82)
    print("HOÀN THÀNH DEMO SO SÁNH PREDICT TARGET %CHANGE VS PRICE!")
    print("=" * 82)


if __name__ == "__main__":
    main()
