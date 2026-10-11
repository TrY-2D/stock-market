from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from src.app.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestSummaryMetrics,
    CandleBar,
    ChartMarker,
    LinePoint,
    TradeItem,
)
from src.backtest import (
    BacktestResult,
    NautilusBacktestRunner,
    QuantitativeBacktestEngine,
    load_strategy_dataset,
)
logger = logging.getLogger(__name__)


class BacktestAppService:
    """Service điều phối và chuẩn hóa dữ liệu backtest cho Web UI."""

    VALID_SYMBOLS = [
        "FPT", "SSI", "HPG", "VNM", "VIC", "MWG", "VCB", "TCB", "MBB", "VHM", "STB", "ACB"
    ]

    @classmethod
    def get_symbols(cls) -> list[str]:
        return cls.VALID_SYMBOLS

    @classmethod
    def execute_backtest(cls, req: BacktestRunRequest) -> BacktestRunResponse:
        """Thực thi backtest và chuyển đổi dữ liệu phù hợp với TradingView Lightweight Charts."""
        start_date = "2000-01-01" if req.all_history else req.start_date
        end_date = pd.Timestamp.now().strftime("%Y-%m-%d") if req.all_history else req.end_date

        market_df, shares_out, div_hist, is_syn = load_strategy_dataset(
            symbol=req.symbol,
            start_date=start_date,
            end_date=end_date,
            force_synthetic=req.use_synthetic,
            all_history=req.all_history,
        )

        if req.engine_type == "nautilus":
            result: BacktestResult = NautilusBacktestRunner.run(
                market_data=market_df,
                symbol=req.symbol,
                venue_str="HOSE",
                currency_str="VND",
                initial_cash=req.initial_cash,
                base_nav_pct=req.base_nav_pct,
                lot_size=req.lot_size,
                window=req.window,
                linear_window=req.linear_window,
                sma_window=req.sma_window,
                beta_window=req.beta_window,
                z_score_window=req.z_score_window,
                sma20_period=req.sma20_period,
                atr_period=req.atr_period,
                atr_multiplier=req.atr_multiplier,
                min_theses=req.min_theses,
                expanding=req.expanding,
                shares_outstanding=shares_out,
                dividend_history=div_hist,
            )
        else:
            engine = QuantitativeBacktestEngine(
                initial_cash=req.initial_cash,
                base_nav_pct=req.base_nav_pct,
                lot_size=req.lot_size,
                buy_fee_rate=0.0015,
                sell_fee_tax_rate=0.0025,
                sma20_period=req.sma20_period,
                window=req.window,
                linear_window=req.linear_window,
                sma_window=req.sma_window,
                beta_window=req.beta_window,
                z_score_window=req.z_score_window,
                atr_period=req.atr_period,
                atr_multiplier=req.atr_multiplier,
                min_theses=req.min_theses,
                expanding=req.expanding,
            )
            result = engine.run(
                market_data=market_df,
                shares_outstanding=shares_out,
                dividend_history=div_hist,
            )

        eq_df = result.equity_curve

        # 1. Chuyển đổi nến OHLCV sang Unix timestamp seconds
        candles: list[CandleBar] = []
        p_suggest_line: list[LinePoint] = []
        support_line: list[LinePoint] = []
        resistance_line: list[LinePoint] = []
        plus_di_line: list[LinePoint] = []
        minus_di_line: list[LinePoint] = []
        adx_line: list[LinePoint] = []
        position_shares_line: list[LinePoint] = []
        position_level_line: list[LinePoint] = []
        buy_thresh_line: list[LinePoint] = []
        sell_thresh_line: list[LinePoint] = []
        sma20_line: list[LinePoint] = []
        exp_return_line: list[LinePoint] = []
        pqr_line: list[LinePoint] = []
        pqt_line: list[LinePoint] = []
        pr_line: list[LinePoint] = []
        pt_line: list[LinePoint] = []
        div_yield_line: list[LinePoint] = []
        theses_line: list[LinePoint] = []
        loser_ratio_line: list[LinePoint] = []
        equity_line: list[LinePoint] = []
        bench_line: list[LinePoint] = []
        drawdown_line: list[LinePoint] = []
        rolling_max_nav = req.initial_cash
        sma20_series = market_df["close"].rolling(req.sma20_period, min_periods=1).mean()

        seen_times: set[int] = set()
        date_to_timestamp: dict[str, int] = {}

        for idx, row in market_df.iterrows():
            d_val = row["date"]
            dt = pd.to_datetime(d_val)
            d_str = dt.strftime("%Y-%m-%d")
            t_sec = int(dt.timestamp())

            if t_sec in seen_times:
                continue
            seen_times.add(t_sec)
            date_to_timestamp[d_str] = t_sec

            candles.append(
                CandleBar(
                    time=t_sec,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 1_000_000)),
                )
            )

            # SMA20
            sma20_val = float(sma20_series.iloc[idx]) if idx < len(sma20_series) else float(row["close"])
            if not math.isfinite(sma20_val):
                sma20_val = float(row["close"])
            sma20_line.append(LinePoint(time=t_sec, value=round(sma20_val, 1)))

            # Lấy thông tin từ equity curve
            if idx < len(eq_df):
                eq_row = eq_df.iloc[idx]
                p_s = float(eq_row.get("p_suggest", row["close"]))
                if not math.isfinite(p_s):
                    p_s = float(row["close"])
                b_th = float(eq_row.get("buy_threshold", row["close"]))
                if not math.isfinite(b_th):
                    b_th = p_s
                s_th = float(eq_row.get("sell_threshold", row["close"]))
                if not math.isfinite(s_th):
                    s_th = p_s
                e_ret = float(eq_row.get("expected_return", 0.0)) * 100.0
                if not math.isfinite(e_ret):
                    e_ret = 0.0
                th_count = float(eq_row.get("theses_count", 0))
                if not math.isfinite(th_count):
                    th_count = 0.0
                nav_val = float(eq_row.get("nav", req.initial_cash))
                if not math.isfinite(nav_val):
                    nav_val = req.initial_cash
                bench_val = float(eq_row.get("benchmark_nav", req.initial_cash))
                if not math.isfinite(bench_val):
                    bench_val = req.initial_cash

                sup_val = float(eq_row.get("support", b_th))
                if not math.isfinite(sup_val):
                    sup_val = b_th
                res_val = float(eq_row.get("resistance", s_th))
                if not math.isfinite(res_val):
                    res_val = s_th

                support_line.append(LinePoint(time=t_sec, value=round(sup_val, 1)))
                resistance_line.append(LinePoint(time=t_sec, value=round(res_val, 1)))
                p_suggest_line.append(LinePoint(time=t_sec, value=round(p_s, 1)))
                buy_thresh_line.append(LinePoint(time=t_sec, value=round(b_th, 1)))
                sell_thresh_line.append(LinePoint(time=t_sec, value=round(s_th, 1)))
                exp_return_line.append(LinePoint(time=t_sec, value=round(e_ret, 2)))

                p_di = float(eq_row.get("plus_di", 0.0))
                m_di = float(eq_row.get("minus_di", 0.0))
                adx_v = float(eq_row.get("adx", 0.0))
                plus_di_line.append(LinePoint(time=t_sec, value=round(p_di if math.isfinite(p_di) else 0.0, 2)))
                minus_di_line.append(LinePoint(time=t_sec, value=round(m_di if math.isfinite(m_di) else 0.0, 2)))
                adx_line.append(LinePoint(time=t_sec, value=round(adx_v if math.isfinite(adx_v) else 0.0, 2)))

                pos_s = float(eq_row.get("position_shares", eq_row.get("shares_held", 0.0)))
                pos_l = float(eq_row.get("position_level", 0.0))
                position_shares_line.append(LinePoint(time=t_sec, value=round(pos_s if math.isfinite(pos_s) else 0.0, 0)))
                position_level_line.append(LinePoint(time=t_sec, value=round(pos_l if math.isfinite(pos_l) else 0.0, 0)))

                pqr_val = float(eq_row.get("pqr", 0.0)) * 100.0
                pqr_line.append(LinePoint(time=t_sec, value=round(pqr_val if math.isfinite(pqr_val) else 0.0, 2)))

                pqt_val = float(eq_row.get("pqt", 0.0)) * 100.0
                pqt_line.append(LinePoint(time=t_sec, value=round(pqt_val if math.isfinite(pqt_val) else 0.0, 2)))

                pr_val = float(eq_row.get("pr", 0.0)) * 100.0
                pr_line.append(LinePoint(time=t_sec, value=round(pr_val if math.isfinite(pr_val) else 0.0, 2)))

                pt_val = float(eq_row.get("pt", 0.0)) * 100.0
                pt_line.append(LinePoint(time=t_sec, value=round(pt_val if math.isfinite(pt_val) else 0.0, 2)))

                div_val = float(eq_row.get("dividend_yield", 0.0)) * 100.0
                div_yield_line.append(LinePoint(time=t_sec, value=round(div_val if math.isfinite(div_val) else 0.0, 2)))

                theses_line.append(LinePoint(time=t_sec, value=round(th_count, 1)))
                loser_val = float(eq_row.get("loser_ratio", 0.5)) * 100.0
                loser_ratio_line.append(LinePoint(time=t_sec, value=round(loser_val if math.isfinite(loser_val) else 50.0, 1)))
                equity_line.append(LinePoint(time=t_sec, value=round(nav_val, 0)))
                bench_line.append(LinePoint(time=t_sec, value=round(bench_val, 0)))
                if nav_val > rolling_max_nav:
                    rolling_max_nav = nav_val
                dd_pct = (nav_val - rolling_max_nav) / rolling_max_nav * 100.0 if rolling_max_nav > 0 else 0.0
                drawdown_line.append(LinePoint(time=t_sec, value=round(dd_pct, 2)))
        # 2. Markers cho TradingView Chart
        markers: list[ChartMarker] = []
        trades: list[TradeItem] = []

        for idx, t in enumerate(result.trades_log):
            t_d_str = pd.to_datetime(t.date).strftime("%Y-%m-%d")
            t_sec = date_to_timestamp.get(t_d_str, int(pd.to_datetime(t.date).timestamp()))
            if t.action == "BUY":
                markers.append(
                    ChartMarker(
                        time=t_sec,
                        position="belowBar",
                        color="#089981",  # Xanh ngọc TradingView
                        shape="arrowUp",
                        text=f"B(F{t.factor})",
                    )
                )
            else:
                markers.append(
                    ChartMarker(
                        time=t_sec,
                        position="aboveBar",
                        color="#f23645",  # Đỏ TradingView
                        shape="arrowDown",
                        text=f"S(F{t.factor})",
                    )
                )

            trades.append(
                TradeItem(
                    trade_id=idx + 1,
                    date=t.date,
                    action=t.action,
                    price=t.price,
                    shares=t.shares,
                    amount=t.amount,
                    fee_tax=t.fee_tax,
                    factor=t.factor,
                    theses_count=t.theses_count,
                    reason=t.reason,
                    nav=t.nav_after,
                    level=getattr(t, "level", 1),
                    pnl=getattr(t, "pnl", 0.0),
                    surplus_after=getattr(t, "surplus_after", 0.0),
                )
            )

        # 3. Summary Metrics
        summary = BacktestSummaryMetrics(
            initial_nav=result.initial_nav,
            final_nav=result.final_nav,
            total_return_pct=round(result.total_return_pct, 2),
            cagr_pct=round(result.cagr_pct, 2),
            benchmark_return_pct=round(result.benchmark_return_pct, 2),
            alpha_pct=round(result.total_return_pct - result.benchmark_return_pct, 2),
            max_drawdown_pct=round(result.max_drawdown_pct, 2),
            sharpe_ratio=round(result.sharpe_ratio, 4),
            sortino_ratio=round(result.sortino_ratio, 4),
            calmar_ratio=round(result.calmar_ratio, 4),
            win_rate_pct=round(result.win_rate_pct, 2),
            profit_factor=round(result.profit_factor, 2),
            total_trades=result.total_trades,
            buy_trades=result.buy_trades,
            sell_trades=result.sell_trades,
        )

        return BacktestRunResponse(
            symbol=req.symbol,
            engine=req.engine_type.upper(),
            summary=summary,
            candles=candles,
            p_suggest=p_suggest_line,
            support=support_line,
            resistance=resistance_line,
            buy_threshold=buy_thresh_line,
            sell_threshold=sell_thresh_line,
            sma20=sma20_line,
            expected_return=exp_return_line,
            pqr_series=pqr_line,
            pqt_series=pqt_line,
            pr_series=pr_line,
            pt_series=pt_line,
            div_yield_series=div_yield_line,
            theses_count=theses_line,
            loser_ratio=loser_ratio_line,
            equity_curve=equity_line,
            benchmark_curve=bench_line,
            drawdown_curve=drawdown_line,
            plus_di=plus_di_line,
            minus_di=minus_di_line,
            adx=adx_line,
            position_shares=position_shares_line,
            position_level=position_level_line,
            markers=markers,
            trades=trades,
        )
