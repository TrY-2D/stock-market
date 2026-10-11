from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AccountType, BarAggregation, OmsType, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity

from src.backtest.engine import BacktestResult, TradeRecord
from src.strategies.nautilus_strategy import NautilusQuantitativeConfig, NautilusQuantitativeStrategy


class NautilusBacktestRunner:
    """Runner thiết lập và điều phối BacktestEngine của Nautilus Trader."""

    @staticmethod
    def dataframe_to_nautilus_data(
        df: pd.DataFrame,
        symbol: str = "FPT",
        venue_str: str = "HOSE",
        currency_str: str = "VND",
        lot_size: int = 100,
    ) -> tuple[Equity, BarType, list[Bar], dict[str, dict[str, float]]]:
        """Chuyển đổi DataFrame thành Equity Instrument, BarType, danh sách Bar và Macro Lookup."""
        curr = Currency.from_str(currency_str)
        sym_obj = Symbol(symbol)
        venue_obj = Venue(venue_str)
        inst_id = InstrumentId(sym_obj, venue_obj)

        price_first = float(df.iloc[0]["close"])
        p_prec = 0 if price_first > 1000 else 2

        equity = Equity(
            instrument_id=inst_id,
            raw_symbol=sym_obj,
            currency=curr,
            price_precision=p_prec,
            price_increment=Price(10 if p_prec == 0 else 0.01, p_prec),
            lot_size=Quantity(lot_size, 0),
            max_quantity=Quantity(10_000_000, 0),
            min_quantity=Quantity(lot_size, 0),
            ts_event=0,
            ts_init=0,
        )

        bar_spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
        bar_type = BarType(inst_id, bar_spec)

        bars: list[Bar] = []
        macro_lookup: dict[str, dict[str, float]] = {}

        for idx, row in df.iterrows():
            d_val = row["date"]
            dt = pd.to_datetime(d_val)
            d_str = dt.strftime("%Y-%m-%d")
            ts_ns = int(dt.timestamp() * 1_000_000_000)

            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            v = int(row.get("volume", 1_000_000))

            bar = Bar(
                bar_type=bar_type,
                open=Price(o, p_prec),
                high=Price(h, p_prec),
                low=Price(l, p_prec),
                close=Price(c, p_prec),
                volume=Quantity(v, 0),
                ts_event=ts_ns,
                ts_init=ts_ns,
            )
            bars.append(bar)

            macro_lookup[d_str] = {
                "vnindex": float(row.get("vnindex", 1200.0)),
                "eurusd": float(row.get("eurusd", 1.08)),
                "dxy": float(row.get("dxy", 104.0)),
                "usdvnd": float(row.get("usdvnd", 25000.0)),
                "inflation": float(row.get("inflation", 3.5)),
                "bond_yield_10y": float(row.get("bond_yield_10y", 2.5)),
            }

        return equity, bar_type, bars, macro_lookup

    @classmethod
    def run(
        cls,
        market_data: pd.DataFrame,
        symbol: str = "FPT",
        venue_str: str = "HOSE",
        currency_str: str = "VND",
        initial_cash: float = 1_000_000_000.0,
        base_nav_pct: float = 0.04,
        v0: int | None = None,
        lot_size: int = 100,
        window: int = 30,
        linear_window: int | None = None,
        sma_window: int | None = None,
        beta_window: int | None = None,
        z_score_window: int = 120,
        sma20_period: int = 20,
        atr_period: int = 14,
        atr_multiplier: float = 1.0,
        linear_k: float = 5.0,
        min_theses: int = 3,
        expanding: bool = False,
        shares_outstanding: float = 1_000_000_000.0,
        dividend_history: Sequence[float] | None = None,
        log_level: str = "ERROR",
    ) -> BacktestResult:
        """Khởi tạo và thực thi Backtest qua Nautilus Trader Engine."""
        div_hist = list(dividend_history) if dividend_history else [1500.0, 1500.0, 2000.0, 2000.0, 2500.0]

        equity, bar_type, bars, macro_lookup = cls.dataframe_to_nautilus_data(
            df=market_data,
            symbol=symbol,
            venue_str=venue_str,
            currency_str=currency_str,
            lot_size=lot_size,
        )

        curr = Currency.from_str(currency_str)
        venue = Venue(venue_str)

        # 1. Khởi tạo Engine
        config = BacktestEngineConfig(
            trader_id=TraderId("BACKTESTER-001"),
            logging=LoggingConfig(log_level=log_level),
        )
        engine = BacktestEngine(config=config)

        # 2. Đăng ký Venue & Tài khoản Cash
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=curr,
            starting_balances=[Money(initial_cash, curr)],
        )

        # 3. Nạp dữ liệu
        engine.add_instrument(equity)
        engine.add_data(bars)

        # 4. Cấu hình và thêm Strategy
        strat_cfg = NautilusQuantitativeConfig(
            instrument_id=equity.id,
            bar_type=bar_type,
            shares_outstanding=shares_outstanding,
            dividend_history=div_hist,
            base_nav_pct=base_nav_pct,
            lot_size=lot_size,
            v0=v0,
            initial_cash=initial_cash,
            buy_fee_rate=0.0015,
            sell_fee_tax_rate=0.0025,
            window=window,
            linear_window=linear_window,
            sma_window=min(int(sma_window), 1500) if sma_window is not None else 1500,
            beta_window=beta_window or window,
            z_score_window=z_score_window,
            sma20_period=sma20_period,
            atr_period=atr_period,
            atr_multiplier=atr_multiplier,
            linear_k=linear_k,
            min_theses=min_theses,
            expanding=expanding,
            macro_lookup=macro_lookup,
        )
        strategy = NautilusQuantitativeStrategy(config=strat_cfg)
        engine.add_strategy(strategy)

        # 5. Thực thi mô phỏng
        engine.run()

        # 6. Trích xuất báo cáo từ Nautilus Trader
        df_acc = engine.trader.generate_account_report(venue)
        df_orders = engine.trader.generate_orders_report()
        df_fills = engine.trader.generate_order_fills_report()
        df_positions = engine.trader.generate_positions_report()

        # 7. Tính toán đường cong NAV và các lệnh
        trades_log: list[TradeRecord] = []
        if strategy.strategy_trades:
            trades_log = list(strategy.strategy_trades)
        elif not df_fills.empty:
            running_cash = initial_cash
            running_shares = 0
            for _, row in df_fills.iterrows():
                fill_dt = pd.to_datetime(row.get("ts_last", 0)).strftime("%Y-%m-%d")
                side_str = str(row.get("side", "BUY")).upper()
                px = float(str(row.get("avg_px", 0.0)).split()[0])
                qty = int(float(str(row.get("filled_qty", 0.0)).split()[0]))
                fee_rate = 0.0015 if "BUY" in side_str else 0.0025
                comm = px * qty * fee_rate

                if "BUY" in side_str:
                    running_cash -= (px * qty + comm)
                    running_shares += qty
                else:
                    running_cash += (px * qty - comm)
                    running_shares -= qty

                nav_snapshot = running_cash + running_shares * px

                trades_log.append(
                    TradeRecord(
                        date=fill_dt,
                        action="BUY" if "BUY" in side_str else "SELL",
                        price=px,
                        shares=qty,
                        amount=px * qty,
                        fee_tax=comm,
                        factor=1,
                        theses_count=3,
                        reason="Nautilus Trader Execution",
                        cash_after=running_cash,
                        shares_after=running_shares,
                        nav_after=nav_snapshot,
                    )
                )

        # Chuẩn hóa Equity Curve theo từng ngày
        p_first = float(market_data.iloc[0]["close"])
        p_last = float(market_data.iloc[-1]["close"])
        benchmark_shares = math.floor(initial_cash / (p_first * 1.0015 * lot_size)) * lot_size
        benchmark_final = benchmark_shares * p_last
        benchmark_return_pct = (benchmark_final - initial_cash) / initial_cash * 100.0

        equity_records: list[dict[str, Any]] = []
        cum_shares = 0
        cum_cash = initial_cash

        fill_map: dict[str, list[tuple[str, int, float]]] = {}
        for t in trades_log:
            fill_map.setdefault(t.date, []).append((t.action, t.shares, t.price))

        for idx, row in market_data.iterrows():
            d_str = pd.to_datetime(row["date"]).strftime("%Y-%m-%d")
            c = float(row["close"])

            # Cập nhật theo fills
            if d_str in fill_map:
                for act, q, p in fill_map[d_str]:
                    if act == "BUY":
                        cum_cash -= q * p * 1.0015
                        cum_shares += q
                    else:
                        cum_cash += q * p * 0.9975
                        cum_shares -= q

            nav_t = cum_cash + cum_shares * c
            bench_t = benchmark_shares * c
            snap = strategy.snapshots[idx] if idx < len(strategy.snapshots) else None

            equity_records.append({
                "date": d_str,
                "price": c,
                "cash": cum_cash,
                "shares_held": cum_shares,
                "stock_value": cum_shares * c,
                "nav": nav_t,
                "benchmark_nav": bench_t,
                "p_suggest": snap.p_suggest if snap else c,
                "support": snap.support if snap else c,
                "resistance": snap.resistance if snap else c,
                "buy_threshold": snap.buy_threshold if snap else c,
                "sell_threshold": snap.sell_threshold if snap else c,
                "theses_count": snap.theses_count if snap else 0,
                "expected_return": snap.expected_return if snap else 0.0,
                "loser_ratio": snap.loser_ratio if snap else 0.5,
                "discount": snap.discount if snap else 0.0,
                "pqr": snap.pqr if snap else 0.0,
                "pqt": snap.pqt if snap else 0.0,
                "pr": snap.pr if snap else 0.0,
                "pt": snap.pt if snap else 0.0,
                "dividend_yield": snap.dividend_yield if snap else 0.0,
                "score_e": snap.score_e if snap else 0.5,
                "score_u": snap.score_u if snap else 0.5,
                "score_l": snap.score_l if snap else 0.5,
                "surplus": strategy.execute_engine.surplus,
                "signal": snap.signal if snap else 0,
                "trend": snap.trend if snap else 0,
                "plus_di": snap.plus_di if snap else 0.0,
                "minus_di": snap.minus_di if snap else 0.0,
                "adx": snap.adx if snap else 0.0,
                "position_shares": cum_shares,
                "position_level": max(strategy.execute_engine.open_levels, default=0),
            })

        eq_df = pd.DataFrame(equity_records)
        final_nav = float(eq_df["nav"].iloc[-1])
        total_return_pct = (final_nav - initial_cash) / initial_cash * 100.0

        n_days = max(len(eq_df), 1)
        years = max(n_days / 252.0, 1.0 / 252.0)
        cagr_pct = ((final_nav / initial_cash) ** (1.0 / years) - 1.0) * 100.0 if final_nav > 0 else -100.0

        rolling_max = eq_df["nav"].cummax()
        drawdown_series = (eq_df["nav"] - rolling_max) / rolling_max
        max_drawdown_pct = float(abs(drawdown_series.min())) * 100.0

        daily_returns = eq_df["nav"].pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 1e-12:
            excess_returns = daily_returns - (0.05 / 252.0)
            sharpe_ratio = float(math.sqrt(252.0) * excess_returns.mean() / daily_returns.std())
            neg_returns = daily_returns[daily_returns < 0]
            downside_std = neg_returns.std() if len(neg_returns) > 1 else daily_returns.std()
            sortino_ratio = float(math.sqrt(252.0) * excess_returns.mean() / max(downside_std, 1e-8))
        else:
            sharpe_ratio = 0.0
            sortino_ratio = 0.0

        calmar_ratio = cagr_pct / max(max_drawdown_pct, 1e-4)
        # Thống kê lệnh & Win rate từ ExecuteEngine / trades_log
        total_trades = len(trades_log)
        buy_trades = sum(1 for t in trades_log if t.action == "BUY")
        sell_trades = sum(1 for t in trades_log if t.action == "SELL")

        sell_records = [t for t in trades_log if t.action == "SELL"]
        win_trades = sum(1 for t in sell_records if t.pnl > 0)
        win_rate_pct = (win_trades / max(len(sell_records), 1)) * 100.0 if sell_records else 0.0

        gains = sum(t.pnl for t in sell_records if t.pnl > 0)
        losses = sum(abs(t.pnl) for t in sell_records if t.pnl < 0)
        profit_factor = (gains / losses) if losses > 1e-6 else (100.0 if gains > 0 else 1.0)
        return BacktestResult(
            initial_nav=initial_cash,
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
            trades_log=trades_log,
            equity_curve=eq_df,
        )
