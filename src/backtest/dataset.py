from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_DATASET_CACHE: dict[tuple[str, str, str, bool, bool], tuple[pd.DataFrame, float, list[float], bool]] = {}
def generate_synthetic_strategy_dataset(
    n_bars: int = 750,
    start_date: str = "2021-01-04",
    symbol: str = "FPT",
    initial_stock_price: float = 45000.0,
    initial_shares_outstanding: float = 1_000_000_000.0,
    all_history: bool = False,
) -> tuple[pd.DataFrame, float, list[float]]:
    """Tạo bộ dữ liệu đa tài sản giả lập (3 năm ~ 750 phiên hoặc toàn bộ lịch sử từ năm 2000) phục vụ backtest chiến lược định lượng.

    Tạo lập đầy đủ 9 yếu tố đầu vào:
    1. Giá thị trường OHLCV (Cổ phiếu mục tiêu)
    2. Khối lượng giao dịch (Volume)
    3. Số lượng cổ phiếu lưu hành (Shares outstanding)
    4. Cổ tức 5 năm (Dividends)
    5. EURUSD
    6. DXY
    7. USDVND
    8. Lạm phát (CPI)
    9. Lợi suất trái phiếu chính phủ 10Y
    """
    clean_sym = symbol.strip().upper()
    profiles: dict[str, dict[str, Any]] = {
        "FPT": {"price": 45000.0, "shares": 1_300_000_000.0, "divs": [1500.0, 2000.0, 2000.0, 2500.0, 2500.0], "beta": 1.30},
        "SSI": {"price": 22000.0, "shares": 1_500_000_000.0, "divs": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0], "beta": 1.55},
        "HPG": {"price": 28000.0, "shares": 5_800_000_000.0, "divs": [500.0, 500.0, 1000.0, 1000.0, 1000.0], "beta": 1.25},
        "VNM": {"price": 82000.0, "shares": 2_090_000_000.0, "divs": [3850.0, 3850.0, 4000.0, 4000.0, 4000.0], "beta": 0.65},
        "VIC": {"price": 65000.0, "shares": 3_800_000_000.0, "divs": [0.0, 0.0, 0.0, 0.0, 0.0], "beta": 1.10},
        "MWG": {"price": 48000.0, "shares": 1_460_000_000.0, "divs": [1000.0, 1500.0, 1500.0, 500.0, 500.0], "beta": 1.20},
        "VCB": {"price": 72000.0, "shares": 5_500_000_000.0, "divs": [800.0, 800.0, 800.0, 800.0, 800.0], "beta": 0.75},
        "TCB": {"price": 32000.0, "shares": 3_500_000_000.0, "divs": [0.0, 0.0, 0.0, 0.0, 1500.0], "beta": 1.35},
        "MBB": {"price": 18000.0, "shares": 5_200_000_000.0, "divs": [500.0, 500.0, 500.0, 500.0, 500.0], "beta": 1.15},
        "VHM": {"price": 55000.0, "shares": 4_350_000_000.0, "divs": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0], "beta": 1.20},
        "STB": {"price": 24000.0, "shares": 1_880_000_000.0, "divs": [0.0, 0.0, 0.0, 0.0, 0.0], "beta": 1.45},
        "ACB": {"price": 23000.0, "shares": 3_880_000_000.0, "divs": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0], "beta": 0.95},
    }

    prof = profiles.get(clean_sym, {"price": initial_stock_price, "shares": initial_shares_outstanding, "divs": [1500.0, 1500.0, 2000.0, 2000.0, 2500.0], "beta": 1.20})
    stock_base_price = prof["price"]
    stock_shares = prof["shares"]
    stock_divs = prof["divs"]
    stock_beta = prof["beta"]

    # Deterministic distinct seed for each symbol and dataset length
    sym_hash = sum((i + 1) * ord(c) for i, c in enumerate(clean_sym))
    if all_history:
        start_date = "2000-07-28"
        today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
        dates = pd.date_range(start_date, today_str, freq="B")
        n_bars = len(dates)
    else:
        dates = pd.date_range(start_date, periods=n_bars, freq="B")

    np.random.seed((sym_hash * 997 + n_bars) % 1_000_000)
    # Mô phỏng các biến số vĩ mô
    r_dxy = np.random.normal(0.0001, 0.004, n_bars)
    r_eur = -0.85 * r_dxy + np.random.normal(0.0, 0.003, n_bars)
    r_fx = 0.35 * r_dxy + np.random.normal(0.0001, 0.0015, n_bars)
    r_vni = -0.40 * r_dxy + np.random.normal(0.0005, 0.012, n_bars)

    p_dxy = 98.0 * np.exp(np.cumsum(r_dxy))
    p_eur = 1.12 * np.exp(np.cumsum(r_eur))
    p_fx = 23100.0 * np.exp(np.cumsum(r_fx))
    p_vni = 1100.0 * np.exp(np.cumsum(r_vni))

    # Lãi suất TPCP 10Y và Lạm phát CPI biến thiên chu kỳ
    t_arr = np.linspace(0, 3.0 * np.pi, n_bars)
    inflation_series = 3.2 + 0.8 * np.sin(t_arr) + np.random.normal(0, 0.05, n_bars)
    bond_yield_series = 2.6 + 0.6 * np.cos(t_arr) + np.random.normal(0, 0.05, n_bars)

    # Cổ phiếu mục tiêu có độ nhạy Beta và drift theo hồ sơ riêng của mã
    r_stock = 0.0003 + stock_beta * r_vni - 0.20 * r_fx + np.random.normal(0.0, 0.008, n_bars)
    p_close = stock_base_price * np.exp(np.cumsum(r_stock))

    # Sinh OHLCV từ giá đóng cửa
    high_p = p_close * (1.0 + np.abs(np.random.normal(0.008, 0.004, n_bars)))
    low_p = p_close * (1.0 - np.abs(np.random.normal(0.008, 0.004, n_bars)))
    open_p = low_p + (high_p - low_p) * np.random.uniform(0.2, 0.8, n_bars)
    volume_p = np.random.randint(1_200_000, 6_000_000, n_bars)

    df = pd.DataFrame({
        "date": dates,
        "open": np.round(open_p, -1),
        "high": np.round(high_p, -1),
        "low": np.round(low_p, -1),
        "close": np.round(p_close, -1),
        "volume": volume_p,
        "vnindex": np.round(p_vni, 2),
        "eurusd": np.round(p_eur, 4),
        "dxy": np.round(p_dxy, 2),
        "usdvnd": np.round(p_fx, 1),
        "inflation": np.round(inflation_series, 2),
        "bond_yield_10y": np.round(bond_yield_series, 2),
    })

    return df, stock_shares, stock_divs


def load_strategy_dataset(
    symbol: str = "FPT",
    start_date: str = "2021-01-01",
    end_date: str = "2024-07-31",
    force_synthetic: bool = False,
    all_history: bool = False,
) -> tuple[pd.DataFrame, float, list[float], bool]:
    """Tải và chuẩn hóa bộ dữ liệu đa tài sản từ SSI, Yahoo Finance, TradingEconomics
    hoặc tự động chuyển sang dữ liệu giả lập chất lượng cao.
    """
    if all_history:
        start_date = "2000-01-01"
        end_date = pd.Timestamp.now().strftime("%Y-%m-%d")

    cache_key = (symbol.strip().upper(), start_date, end_date, force_synthetic, all_history)
    if cache_key in _DATASET_CACHE:
        cached_df, cached_shares, cached_divs, cached_syn = _DATASET_CACHE[cache_key]
        logger.info("Serving dataset from cache for %s", symbol)
        return cached_df.copy(), cached_shares, list(cached_divs), cached_syn
    if force_synthetic:
        logger.info("Using synthetic dataset by flag.")
        df_syn, shares, divs = generate_synthetic_strategy_dataset(n_bars=750, symbol=symbol, all_history=all_history)
        return df_syn, shares, divs, True
    try:
        from src.data_pipeline.economics import EconomicFetcher
        from src.data_pipeline.ssi import SSIFetcher
        from src.data_pipeline.yahoo import YahooFinanceFetcher

        print("  [Data Pipeline] Đang lấy dữ liệu từ SSIFetcher (Cổ phiếu, Cổ tức, Niêm yết)...")
        with SSIFetcher() as ssi:
            df_stock = ssi.fetch_df(symbol, interval="1d", start_date=start_date, end_date=end_date)
            df_vni = ssi.fetch_df("VNINDEX", interval="1d", start_date=start_date, end_date=end_date)
            try:
                listing_info = ssi.get_listing_info(symbol)
                shares_outstanding = float(listing_info.circulating_shares or listing_info.issue_shares or 1_000_000_000.0)
            except Exception:
                shares_outstanding = 1_000_000_000.0

            try:
                div_df = ssi.get_cash_dividends_df(symbol)
                if not div_df.empty and "cash_rate" in div_df.columns:
                    div_history = [float(x) for x in div_df["cash_rate"].dropna().tolist()[:5]]
                else:
                    div_history = [2000.0, 2000.0, 2000.0, 2500.0, 2500.0]
            except Exception:
                div_history = [2000.0, 2000.0, 2000.0, 2500.0, 2500.0]

        print("  [Data Pipeline] Đang lấy dữ liệu từ YahooFinanceFetcher (EURUSD, DXY, USDVND)...")
        with YahooFinanceFetcher() as yf:
            df_eur = yf.get_ohlcv("EUR/USD", interval="1d", start_date=start_date, end_date=end_date)
            df_fx = yf.get_ohlcv("USD/VND", interval="1d", start_date=start_date, end_date=end_date)
            try:
                df_dxy = yf.get_ohlcv("DXY", interval="1d", start_date=start_date, end_date=end_date)
            except Exception:
                df_dxy = pd.DataFrame()

        print("  [Data Pipeline] Đang lấy dữ liệu từ EconomicFetcher (CPI, 10Y Yield)...")
        with EconomicFetcher() as econ:
            try:
                df_inf = econ.fetch_inflation_df(country="vietnam")
            except Exception:
                df_inf = pd.DataFrame()
            try:
                df_bond = econ.fetch_bond_yield_df(country="vietnam", span="5Y")
            except Exception:
                df_bond = pd.DataFrame()

        if df_stock.empty or df_fx.empty:
            raise ValueError("Dữ liệu cổ phiếu hoặc tỷ giá trả về rỗng.")

        # Đồng bộ ngày giao dịch
        df_stock["d"] = pd.to_datetime(df_stock.index).date
        merged = df_stock[["d", "open", "high", "low", "close", "volume"]].copy()

        if not df_vni.empty:
            df_vni["d"] = pd.to_datetime(df_vni.index).date
            merged = merged.merge(df_vni[["d", "close"]].rename(columns={"close": "vnindex"}), on="d", how="left")
        else:
            merged["vnindex"] = 1200.0

        df_fx["d"] = pd.to_datetime(df_fx.index).date
        merged = merged.merge(df_fx[["d", "close"]].rename(columns={"close": "usdvnd"}), on="d", how="left")

        if not df_eur.empty:
            df_eur["d"] = pd.to_datetime(df_eur.index).date
            merged = merged.merge(df_eur[["d", "close"]].rename(columns={"close": "eurusd"}), on="d", how="left")
        else:
            merged["eurusd"] = 1.08

        if not df_dxy.empty:
            df_dxy["d"] = pd.to_datetime(df_dxy.index).date
            merged = merged.merge(df_dxy[["d", "close"]].rename(columns={"close": "dxy"}), on="d", how="left")
        else:
            # Ước lượng xấp xỉ DXY từ EURUSD nếu không có
            merged["dxy"] = 104.0

        # Lạm phát và Lợi suất trái phiếu
        if not df_inf.empty and "value" in df_inf.columns:
            df_inf["d"] = pd.to_datetime(df_inf.index).date
            merged = merged.merge(df_inf[["d", "value"]].rename(columns={"value": "inflation"}), on="d", how="left")
        else:
            merged["inflation"] = 3.5

        if not df_bond.empty and "value" in df_bond.columns:
            df_bond["d"] = pd.to_datetime(df_bond.index).date
            merged = merged.merge(df_bond[["d", "value"]].rename(columns={"value": "bond_yield_10y"}), on="d", how="left")
        else:
            merged["bond_yield_10y"] = 2.5

        # Forward-fill các giá trị vĩ mô còn thiếu
        merged = merged.rename(columns={"d": "date"}).sort_values("date").reset_index(drop=True)
        merged = merged.ffill().bfill()

        print(f"  => Tải và hợp nhất thành công {len(merged)} phiên đa tài sản!")
        _DATASET_CACHE[cache_key] = (merged.copy(), shares_outstanding, list(div_history), False)
        return merged, shares_outstanding, div_history, False

    except Exception as exc:
        print(f"  [Thông báo] Chuyển sang dữ liệu giả lập chuẩn hóa ({exc}).")
        df_syn, shares, divs = generate_synthetic_strategy_dataset(n_bars=750, symbol=symbol, all_history=all_history)
        _DATASET_CACHE[cache_key] = (df_syn.copy(), shares, list(divs), True)
        return df_syn, shares, divs, True
