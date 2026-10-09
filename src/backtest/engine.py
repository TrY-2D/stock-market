from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.strategies.indicators.candlestick import CandlestickPatternDetector
from src.strategies.valuation import ExpectedReturnEngine, ValuationSnapshot


@dataclass
class TradeRecord:
    """Bản ghi chi tiết một lệnh giao dịch đã thực thi."""
    date: str
    action: str  # "BUY" hoặc "SELL"
    price: float
    shares: int
    amount: float
    fee_tax: float
    factor: int
    theses_count: int
    reason: str
    cash_after: float
    shares_after: int
    nav_after: float


@dataclass
class BacktestResult:
    """Kết quả tổng hợp và phân tích hiệu suất backtest."""
    initial_nav: float
    final_nav: float
    total_return_pct: float
    cagr_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    buy_trades: int
    sell_trades: int
    trades_log: list[TradeRecord]
    equity_curve: pd.DataFrame


class QuantitativeBacktestEngine:
    """Engine mô phỏng và kiểm thử chiến lược định lượng (Direct Vector Backtesting Engine).

    Tích hợp toàn diện:
    - ExpectedReturnEngine (E, Q, Beta, LRC, SMA, D)
    - 5 Luận điểm (Theses scoring >= 3/5)
    - Nhận diện nến đảo chiều (CandlestickPatternDetector)
    - DMI Trigger & Trend Confirmation (Delay khi trend_strength > 30)
    - Quản lý vốn Tranche Fibonacci (1, 1, 2, 3, 5 cho Mua; 5, 3, 2, 1, 1 cho Bán)
    - Hạch toán phí giao dịch, thuế và cổ tức tiền mặt
    """

    BUY_FACTORS: tuple[int, ...] = (1, 1, 2, 3, 5)
    SELL_FACTORS: tuple[int, ...] = (5, 3, 2, 1, 1)

    def __init__(
        self,
        initial_cash: float = 1_000_000_000.0,  # 1 tỷ VNĐ
        base_nav_pct: float = 0.04,             # N% NAV cơ sở cho factor = 1 (4%)
        lot_size: int = 100,                    # Chuẩn lô tối thiểu sàn HOSE/HNX
        buy_fee_rate: float = 0.0015,           # Phí mua 0.15%
        sell_fee_tax_rate: float = 0.0025,      # Phí 0.15% + Thuế 0.10% = 0.25%
        sma20_period: int = 20,
        window: int = 30,
        linear_window: int | None = None,
        sma_window: int | None = None,
        beta_window: int | None = None,
        z_score_window: int = 120,
        atr_period: int = 14,
        atr_multiplier: float = 1.0,
        linear_k: float = 5.0,
        min_theses: int = 3,
        expanding: bool = False,
    ):
        self.initial_cash = initial_cash
        self.base_nav_pct = base_nav_pct
        self.lot_size = lot_size
        self.buy_fee_rate = buy_fee_rate
        self.sell_fee_tax_rate = sell_fee_tax_rate
        self.sma20_period = sma20_period
        self.window = window
        self.linear_window = linear_window or window
        self.sma_window = sma_window or window
        self.beta_window = beta_window or window
        self.z_score_window = z_score_window
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.linear_k = linear_k
        self.min_theses = min_theses
        self.expanding = expanding
    def run(
        self,
        market_data: pd.DataFrame,
        shares_outstanding: float = 1_000_000_000.0,
        dividend_history: Sequence[float] | None = None,
    ) -> BacktestResult:
        """Thực thi backtest trên toàn bộ chuỗi dữ liệu lịch sử."""
        div_5y = list(dividend_history) if dividend_history else [1500.0, 1500.0, 2000.0, 2000.0, 2500.0]

        # Khởi tạo mô hình định giá và trạng thái danh mục
        engine = ExpectedReturnEngine(
            window=self.window,
            linear_window=self.linear_window,
            sma_window=self.sma_window,
            beta_window=self.beta_window,
            z_score_window=self.z_score_window,
            atr_period=self.atr_period,
            atr_multiplier=self.atr_multiplier,
            linear_k=self.linear_k,
            expanding=self.expanding,
        )
        cash = self.initial_cash
        shares_held = 0
        total_bought_shares = 0
        total_bought_cost = 0.0

        buy_tranche_idx = 0
        sell_tranche_idx = 0

        trades: list[TradeRecord] = []
        equity_records: list[dict[str, Any]] = []

        prev_open: float | None = None
        prev_close: float | None = None
        sma20_buffer: list[float] = []

        # Benchmark Buy & Hold
        p_first = float(market_data.iloc[0]["close"])
        benchmark_shares = math.floor(self.initial_cash / (p_first * (1.0 + self.buy_fee_rate) * self.lot_size)) * self.lot_size

        for idx, row in market_data.iterrows():
            d_str = str(row["date"])
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            v = float(row.get("volume", 1_000_000))

            vni = float(row.get("vnindex", 1200.0))
            eur = float(row.get("eurusd", 1.08))
            dxy = float(row.get("dxy", 104.0))
            fx = float(row.get("usdvnd", 25000.0))
            inf = float(row.get("inflation", 3.5))
            by = float(row.get("bond_yield_10y", 2.5))

            # 1. Cập nhật SMA20 của cổ phiếu
            sma20_buffer.append(c)
            sma20 = float(np.mean(sma20_buffer[-self.sma20_period:]))

            # 2. Nhận diện tín hiệu nến đảo chiều
            candle_sig = CandlestickPatternDetector.analyze(
                open_p=o,
                high_p=h,
                low_p=l,
                close_p=c,
                prev_open=prev_open,
                prev_close=prev_close,
            )
            prev_open = o
            prev_close = c

            # 3. Cập nhật ExpectedReturnEngine
            snapshot = engine.update(
                stock_open=o,
                stock_high=h,
                stock_low=l,
                stock_close=c,
                stock_volume=v,
                shares_outstanding=shares_outstanding,
                dividend_5y_history=div_5y,
                eurusd_close=eur,
                dxy_close=dxy,
                usdvnd_close=fx,
                inflation_rate=inf,
                bond_yield_10y=by,
            )

            current_nav = cash + shares_held * c
            dmi = engine.stock_dmi

            # 4. Kiểm tra điều kiện DMI & Đảo chiều (với delay khi trend_strength > 30)
            dmi_buy_signal = dmi.check_buy_reversal_signal(candle_sig.is_bullish)
            dmi_sell_signal = dmi.check_sell_reversal_signal(candle_sig.is_bearish)

            executed = False

            # =========================================================
            # 5. Quy tắc MUA (Section III.4 & III.5)
            # =========================================================
            if (
                snapshot.theses_count >= self.min_theses
                and c <= snapshot.buy_threshold
                and dmi_buy_signal
                and sma20 > snapshot.p_suggest
                and buy_tranche_idx < len(self.BUY_FACTORS)
            ):
                factor = self.BUY_FACTORS[buy_tranche_idx]
                target_value = factor * self.base_nav_pct * current_nav
                raw_shares = target_value / c
                shares_to_buy = int(math.floor(raw_shares / self.lot_size) * self.lot_size)

                # Kiểm tra đủ tiền mặt (bao gồm phí mua)
                cost_needed = shares_to_buy * c * (1.0 + self.buy_fee_rate)
                if cost_needed > cash and c > 0:
                    max_affordable = cash / (c * (1.0 + self.buy_fee_rate))
                    shares_to_buy = int(math.floor(max_affordable / self.lot_size) * self.lot_size)
                    cost_needed = shares_to_buy * c * (1.0 + self.buy_fee_rate)

                if shares_to_buy >= self.lot_size:
                    trade_amt = shares_to_buy * c
                    fee = trade_amt * self.buy_fee_rate
                    cash -= (trade_amt + fee)
                    shares_held += shares_to_buy
                    total_bought_shares += shares_to_buy
                    total_bought_cost += (trade_amt + fee)

                    current_nav = cash + shares_held * c
                    reason_desc = (
                        f"Theses: {snapshot.theses_count}/5 | In BuyZone (<{snapshot.buy_threshold:,.0f}) | "
                        f"Reversal Trigger (TS={dmi.trend_strength:.1f}) | SMA20>{snapshot.p_suggest:,.0f}"
                    )

                    trades.append(
                        TradeRecord(
                            date=d_str,
                            action="BUY",
                            price=c,
                            shares=shares_to_buy,
                            amount=trade_amt,
                            fee_tax=fee,
                            factor=factor,
                            theses_count=snapshot.theses_count,
                            reason=reason_desc,
                            cash_after=cash,
                            shares_after=shares_held,
                            nav_after=current_nav,
                        )
                    )
                    buy_tranche_idx += 1
                    # Sau khi mua, mở lại chu kỳ bán nếu đã chốt trước đó
                    sell_tranche_idx = 0
                    dmi.pending_buy_reversal = False
                    executed = True

            # =========================================================
            # 6. Quy tắc BÁN (Section III.4 & III.6)
            # =========================================================
            if (
                not executed
                and shares_held >= self.lot_size
                and c >= snapshot.sell_threshold
                and dmi_sell_signal
                and sma20 < snapshot.p_suggest
                and sell_tranche_idx < len(self.SELL_FACTORS)
            ):
                factor = self.SELL_FACTORS[sell_tranche_idx]
                sell_ratio = min(1.0, factor / sum(self.SELL_FACTORS[sell_tranche_idx:]))
                raw_shares = shares_held * sell_ratio
                shares_to_sell = int(math.floor(raw_shares / self.lot_size) * self.lot_size)

                if sell_tranche_idx == len(self.SELL_FACTORS) - 1 or shares_held - shares_to_sell < self.lot_size:
                    shares_to_sell = shares_held

                if shares_to_sell >= self.lot_size:
                    trade_amt = shares_to_sell * c
                    fee_tax = trade_amt * self.sell_fee_tax_rate
                    cash += (trade_amt - fee_tax)
                    shares_held -= shares_to_sell

                    current_nav = cash + shares_held * c
                    reason_desc = (
                        f"In SellZone (>{snapshot.sell_threshold:,.0f}) | "
                        f"Reversal Trigger (TS={dmi.trend_strength:.1f}) | SMA20<{snapshot.p_suggest:,.0f}"
                    )

                    trades.append(
                        TradeRecord(
                            date=d_str,
                            action="SELL",
                            price=c,
                            shares=shares_to_sell,
                            amount=trade_amt,
                            fee_tax=fee_tax,
                            factor=factor,
                            theses_count=snapshot.theses_count,
                            reason=reason_desc,
                            cash_after=cash,
                            shares_after=shares_held,
                            nav_after=current_nav,
                        )
                    )
                    sell_tranche_idx += 1
                    if shares_held == 0:
                        buy_tranche_idx = 0
                    dmi.pending_sell_reversal = False
                    executed = True

            # Ghi nhận trạng thái Equity Curve hàng ngày
            benchmark_val = benchmark_shares * c
            equity_records.append({
                "date": d_str,
                "price": c,
                "cash": cash,
                "shares_held": shares_held,
                "stock_value": shares_held * c,
                "nav": current_nav,
                "benchmark_nav": benchmark_val,
                "p_suggest": snapshot.p_suggest,
                "buy_threshold": snapshot.buy_threshold,
                "sell_threshold": snapshot.sell_threshold,
                "theses_count": snapshot.theses_count,
                "expected_return": snapshot.expected_return,
                "pqr": snapshot.pqr,
                "pqt": snapshot.pqt,
                "pr": snapshot.pr,
                "pt": snapshot.pt,
                "dividend_yield": snapshot.dividend_yield,
                "score_e": snapshot.score_e,
                "score_u": snapshot.score_u,
                "score_l": snapshot.score_l,
            })

        # -------------------------------------------------------------
        # 7. Phân tích kết quả và số liệu hiệu suất (Performance)
        # -------------------------------------------------------------
        eq_df = pd.DataFrame(equity_records)
        final_nav = float(eq_df["nav"].iloc[-1])
        total_return_pct = (final_nav - self.initial_cash) / self.initial_cash * 100.0

        p_last = float(market_data.iloc[-1]["close"])
        benchmark_final = benchmark_shares * p_last
        benchmark_return_pct = (benchmark_final - self.initial_cash) / self.initial_cash * 100.0

        n_days = max(len(eq_df), 1)
        years = max(n_days / 252.0, 1.0 / 252.0)
        cagr_pct = ((final_nav / self.initial_cash) ** (1.0 / years) - 1.0) * 100.0 if final_nav > 0 else -100.0

        rolling_max = eq_df["nav"].cummax()
        drawdown_series = (eq_df["nav"] - rolling_max) / rolling_max
        max_drawdown_pct = float(abs(drawdown_series.min())) * 100.0

        daily_returns = eq_df["nav"].pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 1e-12:
            rf_daily = 0.05 / 252.0
            excess_returns = daily_returns - rf_daily
            sharpe_ratio = float(math.sqrt(252.0) * excess_returns.mean() / daily_returns.std())

            neg_returns = daily_returns[daily_returns < 0]
            downside_std = neg_returns.std() if len(neg_returns) > 1 else daily_returns.std()
            sortino_ratio = float(math.sqrt(252.0) * excess_returns.mean() / max(downside_std, 1e-8))
        else:
            sharpe_ratio = 0.0
            sortino_ratio = 0.0

        calmar_ratio = cagr_pct / max(max_drawdown_pct, 1e-4)

        buy_trades_count = sum(1 for t in trades if t.action == "BUY")
        sell_trades_count = sum(1 for t in trades if t.action == "SELL")

        pnl_list: list[float] = []
        cost_queue: deque[tuple[int, float]] = deque()
        for t in trades:
            if t.action == "BUY":
                cost_queue.append((t.shares, t.price * (1.0 + self.buy_fee_rate)))
            elif t.action == "SELL":
                shares_to_match = t.shares
                sale_revenue = t.amount - t.fee_tax
                matched_cost = 0.0
                while shares_to_match > 0 and cost_queue:
                    q_shares, q_price = cost_queue.popleft()
                    if q_shares <= shares_to_match:
                        matched_cost += q_shares * q_price
                        shares_to_match -= q_shares
                    else:
                        matched_cost += shares_to_match * q_price
                        cost_queue.appendleft((q_shares - shares_to_match, q_price))
                        shares_to_match = 0
                trade_pnl = sale_revenue - matched_cost
                pnl_list.append(trade_pnl)

        wins = [p for p in pnl_list if p > 0]
        losses = [abs(p) for p in pnl_list if p < 0]
        win_rate_pct = (len(wins) / len(pnl_list) * 100.0) if pnl_list else 0.0
        profit_factor = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (10.0 if wins else 0.0)

        return BacktestResult(
            initial_nav=self.initial_cash,
            final_nav=final_nav,
            total_return_pct=total_return_pct,
            cagr_pct=cagr_pct,
            benchmark_return_pct=benchmark_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            total_trades=len(trades),
            buy_trades=buy_trades_count,
            sell_trades=sell_trades_count,
            trades_log=trades,
            equity_curve=eq_df,
        )
