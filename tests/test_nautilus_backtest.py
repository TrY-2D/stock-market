from __future__ import annotations

import pytest
from src.backtest import (
    NautilusBacktestRunner,
    generate_synthetic_strategy_dataset,
)
from src.strategies.nautilus_strategy import NautilusQuantitativeConfig, NautilusQuantitativeStrategy

def test_nautilus_data_conversion():
    df, shares, divs = generate_synthetic_strategy_dataset(n_bars=30)
    equity, bar_type, bars, macro = NautilusBacktestRunner.dataframe_to_nautilus_data(
        df=df,
        symbol="FPT",
        venue_str="HOSE",
        currency_str="VND",
        lot_size=100,
    )
    assert equity.id.symbol.value == "FPT"
    assert equity.id.venue.value == "HOSE"
    assert bar_type.instrument_id == equity.id
    assert len(bars) == 30
    assert len(macro) == 30
    assert "dxy" in list(macro.values())[0]


def test_nautilus_backtest_runner_execution():
    df, shares, divs = generate_synthetic_strategy_dataset(n_bars=80, initial_stock_price=45000.0)

    result = NautilusBacktestRunner.run(
        market_data=df,
        symbol="FPT",
        venue_str="HOSE",
        currency_str="VND",
        initial_cash=1_000_000_000.0,
        base_nav_pct=0.04,
        lot_size=100,
        window=20,
        shares_outstanding=shares,
        dividend_history=divs,
    )

    assert result.initial_nav == 1_000_000_000.0
    assert result.final_nav > 0.0
    assert len(result.equity_curve) == 80
    assert result.max_drawdown_pct >= 0.0
    assert result.total_trades > 0

    # Kiểm tra tính toàn vẹn của trades log
    for trade in result.trades_log:
        assert trade.action in ("BUY", "SELL")
        assert trade.shares % 100 == 0
        assert trade.amount > 0.0
        assert trade.fee_tax > 0.0


def test_nautilus_backtest_runner_expanding():
    df, shares, divs = generate_synthetic_strategy_dataset(n_bars=60)
    result = NautilusBacktestRunner.run(
        market_data=df,
        symbol="FPT",
        initial_cash=500_000_000.0,
        expanding=True,
        shares_outstanding=shares,
        dividend_history=divs,
    )
    assert result.initial_nav == 500_000_000.0
    assert result.final_nav > 0.0
    assert len(result.equity_curve) == 60
