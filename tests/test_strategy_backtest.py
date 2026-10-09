from __future__ import annotations

import numpy as np
import pytest
from src.backtest import QuantitativeBacktestEngine, generate_synthetic_strategy_dataset
from src.strategies.indicators.candlestick import CandlestickPatternDetector
from src.strategies.valuation import ExpectedReturnEngine

def test_candlestick_reversal_patterns():
    # 1. Hammer: thân nhỏ ở trên, bóng dưới dài gấp đôi thân
    sig_hammer = CandlestickPatternDetector.analyze(
        open_p=102.0, high_p=103.0, low_p=95.0, close_p=102.5,
    )
    assert sig_hammer.is_bullish
    assert not sig_hammer.is_bearish
    assert sig_hammer.pattern == "Hammer"

    # 2. Inverted Hammer: thân nhỏ ở dưới, bóng trên dài gấp đôi thân
    sig_inv_hammer = CandlestickPatternDetector.analyze(
        open_p=96.0, high_p=105.0, low_p=95.5, close_p=96.5,
    )
    assert sig_inv_hammer.is_bullish
    assert not sig_inv_hammer.is_bearish
    assert sig_inv_hammer.pattern == "Inverted Hammer"

    # 3. Bullish Engulfing
    sig_bull_engulf = CandlestickPatternDetector.analyze(
        open_p=95.0, high_p=105.0, low_p=94.0, close_p=104.0,
        prev_open=100.0, prev_close=96.0,
    )
    assert sig_bull_engulf.is_bullish
    assert sig_bull_engulf.pattern == "Bullish Engulfing"

    # 4. Shooting Star: thân nhỏ ở dưới, bóng trên dài, nến giảm
    sig_star = CandlestickPatternDetector.analyze(
        open_p=100.0, high_p=108.0, low_p=99.5, close_p=99.6,
    )
    assert sig_star.is_bearish
    assert sig_star.pattern == "Shooting Star"

    # 5. Bearish Engulfing
    sig_bear_engulf = CandlestickPatternDetector.analyze(
        open_p=105.0, high_p=106.0, low_p=95.0, close_p=96.0,
        prev_open=98.0, prev_close=103.0,
    )
    assert sig_bear_engulf.is_bearish
    assert sig_bear_engulf.pattern == "Bearish Engulfing"


def test_expected_return_engine_and_scoring():
    engine = ExpectedReturnEngine(window=20, three_year_window=50, z_score_window=30)

    # Cung cấp 30 phiên dữ liệu để khởi tạo
    for i in range(30):
        c = 100.0 + i * 0.5
        h = c + 1.5
        l = c - 1.5
        o = c - 0.2
        snapshot = engine.update(
            stock_open=o,
            stock_high=h,
            stock_low=l,
            stock_close=c,
            stock_volume=1_000_000,
            shares_outstanding=10_000_000,
            dividend_5y_history=[2000.0, 2000.0, 2500.0],
            eurusd_close=1.08 + i * 0.001,
            dxy_close=103.0 - i * 0.05,
            usdvnd_close=25000.0 + i * 10.0,
            inflation_rate=3.5,
            bond_yield_10y=2.5,
        )

    # Kiểm tra các thành phần tính toán
    assert snapshot.saving_rate == pytest.approx(0.06, abs=1e-4)  # 3.5% + 2.5% = 6.0%
    assert snapshot.atr > 0.0
    assert snapshot.buy_threshold > snapshot.p_suggest
    assert snapshot.sell_threshold < snapshot.p_suggest
    assert 0.0 <= snapshot.u_discount <= 1.0
    assert 0.0 <= snapshot.l_loser_ratio <= 1.0
    assert 0.0 <= snapshot.score_bp_sma <= 1.0
    assert 0.0 <= snapshot.score_bp_linear <= 1.0
    assert 0 <= snapshot.theses_count <= 5
    # Kiểm tra công thức tổng hợp lợi nhuận kỳ vọng 1 năm (E)
    expected_e = (
        0.42 * snapshot.pqr
        + 0.18 * snapshot.pqt
        + 0.28 * snapshot.pr
        + 0.12 * snapshot.pt
        + snapshot.dividend_yield
    )
    assert pytest.approx(snapshot.expected_return, abs=1e-6) == expected_e


def test_quantitative_backtest_execution():
    df, shares_out, div_hist = generate_synthetic_strategy_dataset(n_bars=150, initial_stock_price=50000.0)

    engine = QuantitativeBacktestEngine(
        initial_cash=500_000_000.0,
        base_nav_pct=0.03,
        lot_size=100,
        buy_fee_rate=0.0015,
        sell_fee_tax_rate=0.0025,
    )

    result = engine.run(
        market_data=df,
        shares_outstanding=shares_out,
        dividend_history=div_hist,
    )

    assert result.initial_nav == 500_000_000.0
    assert result.final_nav > 0.0
    assert len(result.equity_curve) == 150
    assert result.max_drawdown_pct >= 0.0

    # Kiểm tra log giao dịch
    if result.trades_log:
        first_trade = result.trades_log[0]
        assert first_trade.action in ("BUY", "SELL")
        assert first_trade.shares % 100 == 0  # Tuân thủ lô 100
        assert first_trade.fee_tax > 0.0


def test_expanding_window_engine_and_all_history():
    # Test all_history dataset generation
    df_all, shares, divs = generate_synthetic_strategy_dataset(symbol="FPT", all_history=True)
    assert len(df_all) > 5000  # Business days since 2000
    assert "2000" in str(df_all.iloc[0]["date"])

    # Test ExpectedReturnEngine with expanding=True
    engine = ExpectedReturnEngine(expanding=True)
    assert engine.expanding
    assert engine.stock_sma.expanding
    assert engine.stock_lrc.expanding
    assert engine.beta_model.expanding

    # Feed 40 bars into expanding engine
    for i in range(40):
        r = df_all.iloc[i]
        snap = engine.update(
            stock_open=r["open"], stock_high=r["high"], stock_low=r["low"], stock_close=r["close"],
            stock_volume=r["volume"], shares_outstanding=shares, dividend_5y_history=divs,
            eurusd_close=r["eurusd"], dxy_close=r["dxy"], usdvnd_close=r["usdvnd"],
            inflation_rate=r["inflation"], bond_yield_10y=r["bond_yield_10y"],
        )

    assert snap.theses_count in range(6)
    assert engine.stock_sma.initialized
    assert engine.stock_lrc.initialized
    assert engine.beta_model.initialized

    # Test QuantitativeBacktestEngine with expanding=True
    backtest_engine = QuantitativeBacktestEngine(
        initial_cash=1_000_000_000.0,
        expanding=True,
    )
    assert backtest_engine.expanding
    res = backtest_engine.run(market_data=df_all.iloc[:100], shares_outstanding=shares, dividend_history=divs)
    assert res.final_nav > 0
    assert len(res.equity_curve) == 100
