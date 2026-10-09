"""Demo Backtest Chiến Lược Giao Dịch Định Lượng

Triển khai đầy đủ theo tài liệu:
I. Dữ liệu đầu vào:
   - Giá thị trường OHLCV (FPT)
   - Khối lượng giao dịch (Volume)
   - Số lượng cổ phiếu lưu hành (Shares)
   - Cổ tức (Dividends)
   - EURUSD, DXY, USDVND
   - Lạm phát (CPI), Lợi suất trái phiếu chính phủ 10Y

II. Mô hình sử dụng:
   - DMI: xác định thời điểm mua/bán và sức mạnh xu hướng.
   - Hồi quy tuyến tính (LRC): xác định vùng giá, lợi nhuận dự phóng dài hạn Pt và RMSE.
   - SMA (Rolling Statistics): xác định vùng giá, lợi nhuận dự phóng trung hạn Pr và RMSE.
   - BETA: ước lượng tương quan đa biến giữa cụm vĩ mô Q và giá thị trường P.
   - Mô hình nến đơn: nhận diện tín hiệu đảo chiều.

III. Chiến lược giao dịch:
   1. Dự phóng lợi nhuận E = 0.42*Pqr + 0.18*Pqt + 0.28*Pr + 0.12*Pt + D
   2. Chỉ số bổ trợ: Chiết khấu từ đỉnh ATH (U), Tỷ lệ loser 3 năm (L).
   3. Chuẩn hóa z-score và sigmoid chuyển về 0-1 cho 5 luận điểm.
   4. Quản lý vốn theo dãy Fibonacci: 1, 1, 2, 3, 5.
   5. Vùng mua: P_suggest + 1 ATR (tối thiểu 3/5 luận điểm).
   6. Vùng bán: P_suggest - 1 ATR.

Usage:
    # 1. Chạy với dữ liệu trực tuyến SSI + Yahoo + TradingEconomics
    python3 demo/demo_backtest.py

    # 2. Chạy offline với dữ liệu giả lập chuẩn hóa 3 năm (~750 phiên)
    python3 demo/demo_backtest.py --synthetic

    # 3. Chạy và lưu biểu đồ kết quả
    python3 demo/demo_backtest.py --synthetic --save demo/backtest_result.png
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from src.backtest import (
    BacktestResult,
    NautilusBacktestRunner,
    QuantitativeBacktestEngine,
    load_strategy_dataset,
)

def print_backtest_report(result: BacktestResult, symbol: str) -> None:
    """In báo cáo định lượng chi tiết ra màn hình console."""
    print("\n" + "=" * 84)
    print(f"BÁO CÁO KẾT QUẢ BACKTEST CHIẾN LƯỢC ĐỊNH LƯỢNG — MÃ: {symbol}")
    print("=" * 84)

    print("\n1. HIỆU SUẤT TĂNG TRƯỞNG DANH MỤC:")
    print("-" * 84)
    print(f"  * Vốn ban đầu (Initial NAV)          : {result.initial_nav:>18,.0f} VNĐ")
    print(f"  * Giá trị danh mục cuối (Final NAV)  : {result.final_nav:>18,.0f} VNĐ")
    print(f"  * Tổng tỷ suất sinh lời (Return)     : {result.total_return_pct:>18.2f} %")
    print(f"  * Lợi nhuận gộp hàng năm (CAGR)      : {result.cagr_pct:>18.2f} %/năm")
    print(f"  * Benchmark Buy & Hold Return        : {result.benchmark_return_pct:>18.2f} %")
    alpha = result.total_return_pct - result.benchmark_return_pct
    print(f"  * Tỷ suất sinh lời vượt trội (Alpha) : {alpha:>18.2f} %")

    print("\n2. ĐỘ ĐO RỦI RO & HIỆU QUẢ ĐIỀU CHỈNH RỦI RO:")
    print("-" * 84)
    print(f"  * Mức sụt giảm tối đa (Max Drawdown) : {result.max_drawdown_pct:>18.2f} %")
    print(f"  * Hệ số Sharpe Ratio (Rf = 5%/năm)   : {result.sharpe_ratio:>18.4f}")
    print(f"  * Hệ số Sortino Ratio                : {result.sortino_ratio:>18.4f}")
    print(f"  * Hệ số Calmar Ratio (CAGR / MDD)    : {result.calmar_ratio:>18.4f}")

    print("\n3. THỐNG KÊ LỆNH & GIAO DỊCH FIBONACCI:")
    print("-" * 84)
    print(f"  * Tổng số lệnh thực thi              : {result.total_trades:>18d} lệnh")
    print(f"  * Số lệnh MUA (Fibonacci 1,1,2,3,5)  : {result.buy_trades:>18d} lệnh")
    print(f"  * Số lệnh BÁN (Fibonacci 5,3,2,1,1)  : {result.sell_trades:>18d} lệnh")
    print(f"  * Tỷ lệ lệnh chốt lời (Win Rate)     : {result.win_rate_pct:>18.2f} %")
    print(f"  * Hệ số Lợi nhuận / Rủi ro (PF)      : {result.profit_factor:>18.2f}")

    print("\n4. NHẬT KÝ 10 GIAO DỊCH GẦN NHẤT (TRADE LOG):")
    print("-" * 84)
    print(f"  {'Ngày':<12} | {'Loại':<5} | {'Giá (VNĐ)':<9} | {'KL':<7} | {'Factor':<6} | {'Luận điểm':<9} | {'NAV Sau Lệnh'}")
    print("  " + "-" * 82)
    for t in result.trades_log[-10:]:
        print(
            f"  {t.date:<12} | {t.action:<5} | {t.price:>9,.0f} | {t.shares:>7,d} | "
            f"{t.factor:>6d} | {t.theses_count:>7d}/5 | {t.nav_after:>16,.0f} VNĐ"
        )
    print("=" * 84)


def plot_backtest_dashboard(
    result: BacktestResult,
    symbol: str,
    save_path: str | None = None,
) -> None:
    """Vẽ bảng điều khiển đồ thị kết quả backtest 4 tầng trực quan."""
    eq_df = result.equity_curve
    dates = pd.to_datetime(eq_df["date"])

    fig, axs = plt.subplots(4, 1, figsize=(14, 13), sharex=True)

    # -----------------------------------------------------------------
    # Tầng 1: Giá Cổ Phiếu, Vùng Mua / Bán (+/- 1 ATR) & Điểm Khớp Lệnh
    # -----------------------------------------------------------------
    ax0 = axs[0]
    ax0.plot(dates, eq_df["price"], label=f"{symbol} Close Price", color="black", lw=1.5)
    ax0.plot(dates, eq_df["p_suggest"], label="P_suggest (Mean LRC & SMA)", color="blue", ls="--", lw=1.2)
    ax0.plot(dates, eq_df["buy_threshold"], label="Buy Zone Upper (P_suggest + 1 ATR)", color="green", ls=":", alpha=0.8)
    ax0.plot(dates, eq_df["sell_threshold"], label="Sell Zone Lower (P_suggest - 1 ATR)", color="red", ls=":", alpha=0.8)

    ax0.fill_between(dates, eq_df["buy_threshold"], eq_df["price"], where=eq_df["price"] <= eq_df["buy_threshold"], color="green", alpha=0.1)
    ax0.fill_between(dates, eq_df["price"], eq_df["sell_threshold"], where=eq_df["price"] >= eq_df["sell_threshold"], color="red", alpha=0.1)

    # Điểm Mua / Bán
    buy_dates, buy_prices = [], []
    sell_dates, sell_prices = [], []
    for t in result.trades_log:
        t_dt = pd.to_datetime(t.date)
        if t.action == "BUY":
            buy_dates.append(t_dt)
            buy_prices.append(t.price)
        else:
            sell_dates.append(t_dt)
            sell_prices.append(t.price)

    if buy_dates:
        ax0.scatter(buy_dates, buy_prices, color="green", marker="^", s=90, label="BUY Execution (Fibonacci)", zorder=5)
    if sell_dates:
        ax0.scatter(sell_dates, sell_prices, color="red", marker="v", s=90, label="SELL Execution (Fibonacci)", zorder=5)

    ax0.set_title(f"1. {symbol} Stock Price, Suggested Action Zones (+/- 1 ATR) & Execution Points", fontsize=11, fontweight="bold")
    ax0.legend(loc="upper left")
    ax0.grid(True, alpha=0.3)

    # -----------------------------------------------------------------
    # Tầng 2: Điểm Số Luận Điểm & Lợi Nhuận Dự Phóng Kỳ Vọng (E)
    # -----------------------------------------------------------------
    ax1 = axs[1]
    ax1_twin = ax1.twinx()

    ax1.plot(dates, eq_df["expected_return"] * 100.0, label="Expected Return E (%/year)", color="purple", lw=1.4)
    ax1.axhline(0.0, color="gray", lw=0.8, ls="--")

    ax1_twin.step(dates, eq_df["theses_count"], label="Valid Theses Count (out of 5)", color="orange", lw=1.2, where="mid")
    ax1_twin.axhline(3.0, color="darkgreen", ls=":", lw=1.5, label="Buy Trigger Threshold (3/5 Theses)")
    ax1_twin.set_ylim(-0.5, 5.5)

    ax1.set_title("2. Comprehensive Expected Return E & 5-Thesis Score Evaluation", fontsize=11, fontweight="bold")
    ax1.legend(loc="upper left")
    ax1_twin.legend(loc="upper right")
    ax1.grid(True, alpha=0.3)

    # -----------------------------------------------------------------
    # Tầng 3: Phân Bổ Cổ Phiếu Theo Fibonacci & Tiền Mặt
    # -----------------------------------------------------------------
    ax2 = axs[2]
    ax2_twin = ax2.twinx()

    ax2.bar(dates, eq_df["shares_held"], label="Shares Held (Fibonacci Tranches)", color="steelblue", alpha=0.5, width=1.5)
    ax2_twin.plot(dates, eq_df["cash"] / 1e6, label="Cash Balance (Million VNĐ)", color="darkgreen", lw=1.2, ls="--")

    ax2.set_title("3. Fibonacci Tranche Asset Accumulation & Portfolio Cash Balance", fontsize=11, fontweight="bold")
    ax2.legend(loc="upper left")
    ax2_twin.legend(loc="upper right")
    ax2.grid(True, alpha=0.3)

    # -----------------------------------------------------------------
    # Tầng 4: Đường Cong Tăng Trưởng NAV (Equity Curve) vs Benchmark
    # -----------------------------------------------------------------
    ax3 = axs[3]
    nav_mil = eq_df["nav"] / 1e6
    bench_mil = eq_df["benchmark_nav"] / 1e6

    ax3.plot(dates, nav_mil, label=f"Strategy Equity Curve (NAV: {result.total_return_pct:+.1f}%)", color="darkblue", lw=2.0)
    ax3.plot(dates, bench_mil, label=f"Benchmark Buy & Hold ({result.benchmark_return_pct:+.1f}%)", color="gray", lw=1.2, ls=":")

    ax3.set_title("4. Portfolio Net Asset Value (NAV in Million VNĐ) vs Buy & Hold Benchmark", fontsize=11, fontweight="bold")
    ax3.legend(loc="upper left")
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, bbox_inches="tight", dpi=150)
        print(f"\n  => Đã lưu thành công biểu đồ backtest tại: {save_path}")

    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy Backtest Chiến Lược Giao Dịch Định Lượng Toàn Diện")
    parser.add_argument("--symbol", type=str, default="FPT", help="Mã cổ phiếu kiểm thử (mặc định: FPT)")
    parser.add_argument("--start", type=str, default="2021-01-01", help="Ngày bắt đầu (mặc định: 2021-01-01)")
    parser.add_argument("--end", type=str, default="2024-07-31", help="Ngày kết thúc (mặc định: 2024-07-31)")
    parser.add_argument("--initial-cash", type=float, default=1_000_000_000.0, help="Vốn tiền mặt ban đầu (VNĐ, mặc định: 1 tỷ)")
    parser.add_argument("--base-nav-pct", type=float, default=0.04, help="Tỷ trọng NAV cơ sở N% cho factor=1 (mặc định: 0.04 = 4%)")
    parser.add_argument("--synthetic", action="store_true", help="Bắt buộc sử dụng dữ liệu giả lập 3 năm (~750 phiên)")
    parser.add_argument("--plot", action="store_true", help="Hiển thị giao diện đồ thị kết quả")
    parser.add_argument("--save", type=str, default=None, help="Đường dẫn lưu file ảnh biểu đồ (ví dụ: demo/backtest.png)")
    parser.add_argument("--window", type=int, default=30, help="Cửa sổ trượt mặc định (mặc định: 30)")
    parser.add_argument("--linear-window", type=int, default=None, help="Độ dài đường hồi quy tuyến tính LRC")
    parser.add_argument("--sma-window", type=int, default=None, help="Độ dài đường SMA thống kê")
    parser.add_argument("--beta-window", type=int, default=None, help="Độ dài cửa sổ hồi quy đa biến Beta")
    parser.add_argument("--z-score-window", type=int, default=120, help="Độ dài cửa sổ chuẩn hóa Z-Score")
    parser.add_argument("--sma20-period", type=int, default=20, help="Chu kỳ SMA bộ lọc xu hướng")
    parser.add_argument("--atr-mult", type=float, default=1.0, help="Hệ số nhân ATR vùng mua/bán")
    parser.add_argument("--min-theses", type=int, default=3, help="Số luận điểm tối thiểu để kích hoạt Mua (1-5)")
    parser.add_argument("--expanding", action="store_true", help="Sử dụng cửa sổ mở rộng expanding (không giới hạn window)")
    parser.add_argument("--all-history", action="store_true", help="Backtest toàn bộ dữ liệu lịch sử (từ năm 2000 đến nay)")
    parser.add_argument(
        "--engine",
        choices=["nautilus", "direct"],
        default="nautilus",
        help="Nền tảng backtest: 'nautilus' (Nautilus Trader Engine - Mặc định) hoặc 'direct'",
    )
    args = parser.parse_args()
    print("=" * 84)
    print("KHỞI CHẠY BACKTEST CHIẾN LƯỢC GIAO DỊCH ĐỊNH LƯỢNG")
    print(f"Mã: {args.symbol} | Nền tảng: {args.engine.upper()} | Vốn: {args.initial_cash:,.0f} VNĐ | Lô cơ sở: {args.base_nav_pct:.1%}")
    print("=" * 84)

    # 1. Nạp và chuẩn hóa dữ liệu 9 yếu tố đầu vào
    market_df, shares_out, div_history, is_syn = load_strategy_dataset(
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        force_synthetic=args.synthetic,
        all_history=args.all_history,
    )

    print(f"  * Số phiên kiểm thử              : {len(market_df)} phiên ({market_df.iloc[0]['date']} -> {market_df.iloc[-1]['date']})")
    print(f"  * Số cổ phiếu lưu hành           : {shares_out:,.0f} cổ phiếu")
    print(f"  * Lịch sử cổ tức 5 năm gần nhất   : {[int(x) for x in div_history]} VNĐ/CP")
    print(f"  * Nguồn dữ liệu                  : {'Synthetic (Giả lập chuẩn hóa)' if is_syn else 'Live (SSI + Yahoo + TradingEconomics)'}")

    # 2. Khởi tạo Engine và thực thi
    if args.engine == "nautilus":
        print("\n  [Execution] Đang chạy mô phỏng giao dịch qua Nautilus Trader BacktestEngine...")
        result = NautilusBacktestRunner.run(
            market_data=market_df,
            symbol=args.symbol,
            venue_str="HOSE",
            currency_str="VND",
            initial_cash=args.initial_cash,
            base_nav_pct=args.base_nav_pct,
            lot_size=100,
            window=args.window,
            linear_window=args.linear_window,
            sma_window=args.sma_window,
            beta_window=args.beta_window,
            z_score_window=args.z_score_window,
            sma20_period=args.sma20_period,
            atr_multiplier=args.atr_mult,
            min_theses=args.min_theses,
            expanding=args.expanding,
            shares_outstanding=shares_out,
            dividend_history=div_history,
        )
    else:
        print("\n  [Execution] Đang chạy mô phỏng giao dịch bar-by-bar...")
        engine = QuantitativeBacktestEngine(
            initial_cash=args.initial_cash,
            base_nav_pct=args.base_nav_pct,
            lot_size=100,
            sma20_period=args.sma20_period,
            window=args.window,
            linear_window=args.linear_window,
            sma_window=args.sma_window,
            beta_window=args.beta_window,
            z_score_window=args.z_score_window,
            atr_multiplier=args.atr_mult,
            min_theses=args.min_theses,
            expanding=args.expanding,
        )
        result = engine.run(
            market_data=market_df,
            shares_outstanding=shares_out,
            dividend_history=div_history,
        )

    # 3. In báo cáo hiệu suất
    print_backtest_report(result, symbol=args.symbol)

    # 4. Vẽ đồ thị nếu được yêu cầu hoặc có file lưu
    if args.plot or args.save:
        try:
            plot_backtest_dashboard(result, symbol=args.symbol, save_path=args.save)
        except Exception as exc:
            print(f"  [Cảnh báo biểu đồ] Không thể mở cửa sổ GUI ({exc}).")


if __name__ == "__main__":
    main()
