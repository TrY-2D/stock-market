from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.strategies.execution import ExecutionResult, FibonacciExecuteEngine, PositionLevel
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
    level: int = 1
    pnl: float = 0.0
    surplus_after: float = 0.0


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

    Tích hợp toàn diện theo đặc tả Execute Engine:
    - ExpectedReturnEngine: Dự phóng lợi nhuận (A), 6 Luận điểm định lượng, Reversal Indicator (DMI, Nến, Linear, SMA).
    - FibonacciExecuteEngine: Quản lý vị thế đa cấp độc lập M = [1, 1, 2, 3, 5, 8], sức chứa tối đa V_max = 21 * V0.
    - Logic MUA: Cấp thấp nhất chưa mở L1 -> L6, ràng buộc P_buy,i < P_buy,prev.
    - Logic BÁN: Cấp cao nhất hiện có L6 -> L1, PnL Barrier (PnL > 0 hoặc |PnL| <= Surplus).
    - Hạch toán phí giao dịch, thuế, cổ tức và quỹ thặng dư tích lũy.
    """

    FIBONACCI_MULTIPLIERS: tuple[int, ...] = (1, 1, 2, 3, 5, 8)
    BUY_FACTORS: tuple[int, ...] = FIBONACCI_MULTIPLIERS
    SELL_FACTORS: tuple[int, ...] = (8, 5, 3, 2, 1, 1)

    def __init__(
        self,
        initial_cash: float = 1_000_000_000.0,  # 1 tỷ VNĐ
        base_nav_pct: float = 0.04,             # N% NAV cơ sở cho factor = 1 (4%)
        v0: int | None = None,                  # Khối lượng lệnh sơ cấp V0
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
        self.initial_cash = float(initial_cash)
        self.base_nav_pct = float(base_nav_pct)
        self.v0 = v0
        self.lot_size = int(lot_size)
        self.buy_fee_rate = float(buy_fee_rate)
        self.sell_fee_tax_rate = float(sell_fee_tax_rate)
        self.sma20_period = int(sma20_period)
        self.window = int(window)
        self.linear_window = linear_window
        self.sma_window = min(int(sma_window), 1500) if sma_window is not None else 1500
        self.beta_window = beta_window or window
        self.z_score_window = z_score_window
        self.atr_period = int(atr_period)
        self.atr_multiplier = float(atr_multiplier)
        self.linear_k = float(linear_k)
        self.min_theses = int(min_theses)
        self.expanding = bool(expanding)

    def run(
        self,
        market_data: pd.DataFrame,
        shares_outstanding: float = 1_000_000_000.0,
        dividend_history: Sequence[float] | None = None,
    ) -> BacktestResult:
        """Thực thi backtest trên toàn bộ chuỗi dữ liệu lịch sử."""
        div_5y = list(dividend_history) if dividend_history else [1500.0, 1500.0, 2000.0, 2000.0, 2500.0]

        # Khởi tạo mô hình định giá E và 6 luận điểm
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

        # Khởi tạo Execute Engine quản lý lệnh đa cấp Fibonacci
        init_v0 = self.v0 or max(self.lot_size, 100)
        execute_engine = FibonacciExecuteEngine(
            v0=init_v0,
            initial_cash=self.initial_cash,
            initial_surplus=0.0,
            buy_fee_rate=self.buy_fee_rate,
            sell_fee_tax_rate=self.sell_fee_tax_rate,
            lot_size=self.lot_size,
            net_pnl=True,
        )

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
            # Cập nhật chu kỳ thanh toán bù trừ T+ và số luận điểm K
            execute_engine.advance_settlement(d_str)
            execute_engine.update_theses_count(snapshot.theses_count)

            # 4. Tự động tính toán lại V0 khi vị thế = 0 (nếu không cố định v0 từ config)
            if execute_engine.total_holding_shares == 0 and self.v0 is None and c > 0:
                current_nav = execute_engine.total_nav(c)
                raw_v0 = (self.base_nav_pct * current_nav) / c
                computed_v0 = max(self.lot_size, int(math.floor(raw_v0 / self.lot_size) * self.lot_size))
                while computed_v0 > self.lot_size and (21 * computed_v0 * c * (1.0 + self.buy_fee_rate) > current_nav):
                    computed_v0 -= self.lot_size
                try:
                    execute_engine.set_v0(computed_v0)
                except ValueError:
                    pass

            # 5. Xử lý Mua / Bán trực tiếp theo Số Luận Điểm K và V_order
            # Thêm 1 luận điểm -> Thêm khối lượng cổ phiếu; Bớt 1 luận điểm -> Bớt khối lượng cổ phiếu
            change_rate = getattr(snapshot, "change_rate", 1) or 1
            execute_engine.sync_theses_demand(snapshot.theses_count)

            v_action, v_level, v_order = execute_engine.calculate_v_order(change_rate=change_rate)

            if v_action == "BUY" and v_order >= self.lot_size:
                exec_res = execute_engine.execute_buy(
                    price=c,
                    volume=v_order,
                    timestamp=d_str,
                    metadata={"theses_count": snapshot.theses_count},
                )
                if exec_res.success and exec_res.level is not None:
                    multiplier = self.FIBONACCI_MULTIPLIERS[exec_res.level - 1]
                    trades.append(
                        TradeRecord(
                            date=d_str,
                            action="BUY",
                            price=c,
                            shares=exec_res.volume,
                            amount=exec_res.volume * c,
                            fee_tax=exec_res.fee_tax,
                            factor=multiplier,
                            theses_count=snapshot.theses_count,
                            reason=exec_res.reason,
                            cash_after=execute_engine.cash,
                            shares_after=execute_engine.total_holding_shares,
                            nav_after=execute_engine.total_nav(c),
                            level=exec_res.level,
                            pnl=0.0,
                            surplus_after=execute_engine.surplus,
                        )
                    )

            elif v_action == "SELL" and v_order >= self.lot_size:
                exec_res = execute_engine.execute_sell(
                    price=c,
                    volume=v_order,
                    timestamp=d_str,
                )
                if exec_res.success and exec_res.level is not None:
                    multiplier = self.FIBONACCI_MULTIPLIERS[exec_res.level - 1]
                    trades.append(
                        TradeRecord(
                            date=d_str,
                            action="SELL",
                            price=c,
                            shares=exec_res.volume,
                            amount=exec_res.volume * c,
                            fee_tax=exec_res.fee_tax,
                            factor=multiplier,
                            theses_count=snapshot.theses_count,
                            reason=exec_res.reason,
                            cash_after=execute_engine.cash,
                            shares_after=execute_engine.total_holding_shares,
                            nav_after=execute_engine.total_nav(c),
                            level=exec_res.level,
                            pnl=exec_res.pnl,
                            surplus_after=execute_engine.surplus,
                        )
                    )
            # Ghi nhận trạng thái Equity Curve hàng ngày
            benchmark_val = benchmark_shares * c
            current_nav = execute_engine.total_nav(c)
            equity_records.append({
                "date": d_str,
                "price": c,
                "cash": execute_engine.cash,
                "shares_held": execute_engine.total_holding_shares,
                "stock_value": execute_engine.total_holding_shares * c,
                "nav": current_nav,
                "benchmark_nav": benchmark_val,
                "p_suggest": snapshot.p_suggest,
                "support": snapshot.support,
                "resistance": snapshot.resistance,
                "buy_threshold": snapshot.buy_threshold,
                "sell_threshold": snapshot.sell_threshold,
                "theses_count": snapshot.theses_count,
                "expected_return": snapshot.expected_return,
                "loser_ratio": snapshot.loser_ratio,
                "discount": snapshot.discount,
                "pqr": snapshot.pqr,
                "pqt": snapshot.pqt,
                "pr": snapshot.pr,
                "pt": snapshot.pt,
                "dividend_yield": snapshot.dividend_yield,
                "score_e": snapshot.score_e,
                "score_u": snapshot.score_u,
                "score_l": snapshot.score_l,
                "surplus": execute_engine.surplus,
                "signal": snapshot.signal,
                "trend": snapshot.trend,
                "plus_di": snapshot.plus_di,
                "minus_di": snapshot.minus_di,
                "adx": snapshot.adx,
                "position_shares": execute_engine.total_holding_shares,
                "position_level": max(execute_engine.open_levels, default=0),
            })

        # -------------------------------------------------------------
        # 7. Phân tích kết quả và số liệu hiệu suất (Performance)
        # -------------------------------------------------------------
        eq_df = pd.DataFrame(equity_records)
        final_nav = float(eq_df["nav"].iloc[-1])
        total_return_pct = (final_nav - self.initial_cash) / self.initial_cash * 100.0

        n_days = max(len(eq_df), 1)
        years = n_days / 252.0
        cagr_pct = ((final_nav / self.initial_cash) ** (1.0 / max(years, 0.01)) - 1.0) * 100.0

        p_last = float(market_data.iloc[-1]["close"])
        benchmark_final = benchmark_shares * p_last
        benchmark_return_pct = (benchmark_final - self.initial_cash) / self.initial_cash * 100.0

        # Max Drawdown
        cummax = eq_df["nav"].cummax()
        drawdowns = (eq_df["nav"] - cummax) / cummax
        max_drawdown_pct = float(abs(drawdowns.min())) * 100.0

        # Sharpe & Sortino
        daily_returns = eq_df["nav"].pct_change().dropna()
        rf_daily = 0.05 / 252.0

        if len(daily_returns) > 1 and daily_returns.std() > 1e-12:
            excess_returns = daily_returns - rf_daily
            sharpe_ratio = float(np.mean(excess_returns) / np.std(daily_returns) * np.sqrt(252))
            downside_returns = daily_returns[daily_returns < 0]
            downside_std = float(np.std(downside_returns)) if len(downside_returns) > 1 else 1e-6
            sortino_ratio = float(np.mean(excess_returns) / max(downside_std, 1e-6) * np.sqrt(252))
        else:
            sharpe_ratio = 0.0
            sortino_ratio = 0.0

        calmar_ratio = cagr_pct / max(max_drawdown_pct, 1e-4)

        # Thống kê lệnh
        total_trades = len(trades)
        buy_trades = sum(1 for t in trades if t.action == "BUY")
        sell_trades = sum(1 for t in trades if t.action == "SELL")

        # Win rate và Profit Factor tính theo kết quả từ ExecuteEngine
        sell_records = [t for t in trades if t.action == "SELL"]
        win_trades = sum(1 for t in sell_records if t.pnl > 0)
        win_rate_pct = (win_trades / max(len(sell_records), 1)) * 100.0 if sell_records else 0.0

        gains = sum(t.pnl for t in sell_records if t.pnl > 0)
        losses = sum(abs(t.pnl) for t in sell_records if t.pnl < 0)
        profit_factor = (gains / losses) if losses > 1e-6 else (100.0 if gains > 0 else 1.0)

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
            total_trades=total_trades,
            buy_trades=buy_trades,
            sell_trades=sell_trades,
            trades_log=trades,
            equity_curve=eq_df,
        )
