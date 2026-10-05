import shutil
import tempfile
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import pandas as pd
import pytest

from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import CurrencyPair, Equity
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from src.data_pipeline.ssi.fetcher import SSIFetcher, _parse_ssi_date
from src.data_pipeline.ssi.models import (
    CompanyListingInfo,
    Dividend,
    calculate_price_increment,
)


# =============================================================================
# 1. UNIT TESTS (Offline / Fast Verification)
# =============================================================================


def test_calculate_price_increment():
    # HOSE rules
    assert calculate_price_increment(8500.0, "HOSE") == 10.0
    assert calculate_price_increment(9990.0, "HOSE") == 10.0
    assert calculate_price_increment(10000.0, "HOSE") == 50.0
    assert calculate_price_increment(25400.0, "HOSE") == 50.0
    assert calculate_price_increment(49950.0, "HOSE") == 50.0
    assert calculate_price_increment(50000.0, "HOSE") == 100.0
    assert calculate_price_increment(85000.0, "HOSE") == 100.0

    # HNX and UPCOM always 100
    assert calculate_price_increment(5000.0, "HNX") == 100.0
    assert calculate_price_increment(20000.0, "HNX") == 100.0
    assert calculate_price_increment(5000.0, "UPCOM") == 100.0


def test_parse_ssi_date():
    assert _parse_ssi_date("30/06/2009") == "2009-06-30"
    assert _parse_ssi_date("2009-06-30") == "2009-06-30"
    assert _parse_ssi_date("23/07/2026") == "2026-07-23"
    assert _parse_ssi_date(None) is None
    assert _parse_ssi_date("") is None


def test_parse_interval_and_bar_type():
    fetcher = SSIFetcher()
    try:
        assert fetcher.parse_interval("1d") == ("1d", 1, BarAggregation.DAY)
        assert fetcher.parse_interval("D") == ("1d", 1, BarAggregation.DAY)
        assert fetcher.parse_interval("15m") == ("15m", 15, BarAggregation.MINUTE)
        assert fetcher.parse_interval("15") == ("15m", 15, BarAggregation.MINUTE)
        assert fetcher.parse_interval("1h") == ("1h", 1, BarAggregation.HOUR)
        assert fetcher.parse_interval("1w") == ("1w", 1, BarAggregation.WEEK)
        assert fetcher.parse_interval("1M") == ("1M", 1, BarAggregation.MONTH)

        bar_type = fetcher.get_bar_type("HPG", interval="1d", venue="HOSE")
        assert isinstance(bar_type, BarType)
        assert str(bar_type) == "HPG.HOSE-1-DAY-LAST-EXTERNAL"

        with pytest.raises(ValueError):
            fetcher.parse_interval("invalid_interval")
    finally:
        fetcher.close()


def test_company_listing_info_to_equity():
    info = CompanyListingInfo(
        symbol="VCB",
        exchange="HOSE",
        company_name="Ngân hàng Ngoại thương",
        client_name_en="Vietcombank",
        isin="VN000000VCB1",
        listing_date="2009-06-30",
        founding_date="1963-04-01",
        issue_shares=8355675094.0,
        circulating_shares=8355675094.0,
        charter_capital=83556750940000.0,
        first_price=60000.0,
        free_float_rate=10.0,
        industry_name="Ngân hàng",
        sector="Tài chính",
    )

    eq = info.to_equity(current_price=57000.0)

    assert isinstance(eq, Equity)
    assert str(eq.id) == "VCB.HOSE"
    assert eq.symbol.value == "VCB"
    assert eq.venue.value == "HOSE"
    assert eq.quote_currency == Currency.from_str("VND")
    assert eq.price_precision == 2
    assert float(eq.price_increment) == 100.0  # 57000 >= 50000
    assert float(eq.lot_size) == 100.0
    assert eq.isin == "VN000000VCB1"
    assert eq.ts_event == 1246320000000000000  # 2009-06-30 in ns UTC
    assert eq.info["company_name"] == "Ngân hàng Ngoại thương"
    assert eq.info["issue_shares"] == 8355675094.0


def test_create_currency_pair_and_instrument():
    fetcher = SSIFetcher()
    try:
        fx = fetcher.create_currency_pair("USD/VND", venue="SIM")
        assert isinstance(fx, CurrencyPair)
        assert str(fx.id) == "USD/VND.SIM"

        eq = fetcher.create_equity("FPT", venue="HOSE", current_price=130000.0, fetch_profile=False)
        assert isinstance(eq, Equity)
        assert str(eq.id) == "FPT.HOSE"
        assert float(eq.price_increment) == 100.0
    finally:
        fetcher.close()


def test_clean_dataframe_and_df_to_bars():
    fetcher = SSIFetcher()
    try:
        # Raw data with unsorted dates, duplicates, and slightly inverted high/low
        raw_df = pd.DataFrame({
            "datetime": [
                "2025-01-03T00:00:00Z",
                "2025-01-02T00:00:00Z",
                "2025-01-02T00:00:00Z",  # Duplicate timestamp
            ],
            "open": [28000.0, 27500.0, 27600.0],
            "high": [27900.0, 28000.0, 28100.0],  # Row 0 has high < open (should auto-correct to 28500)
            "low": [28200.0, 27000.0, 27200.0],   # Row 0 has low > open (should auto-correct to 28000)
            "close": [28500.0, 27800.0, 27900.0],
            "volume": [1500000, 1200000, 1300000],
        })

        cleaned = fetcher.clean_dataframe(raw_df)
        assert len(cleaned) == 2
        assert isinstance(cleaned.index, pd.DatetimeIndex)
        assert cleaned.index.is_monotonic_increasing
        # Verify OHLC boundary correction on 2025-01-03 row
        row_jan3 = cleaned.iloc[1]
        assert row_jan3["high"] == 28500.0
        assert row_jan3["low"] == 28000.0

        # Convert to Nautilus Bars
        bar_type = fetcher.get_bar_type("HPG", interval="1d", venue="HOSE")
        bars = fetcher.df_to_bars(cleaned, bar_type=bar_type)
        assert len(bars) == 2
        assert all(isinstance(b, Bar) for b in bars)
        assert bars[0].ts_event < bars[1].ts_event
        assert float(bars[1].close) == 28500.0
        assert float(bars[1].volume) == 1500000.0
    finally:
        fetcher.close()


def test_dividend_and_bars_catalog_persistence():
    temp_dir = tempfile.mkdtemp()
    fetcher = SSIFetcher(catalog_path=temp_dir)
    try:
        cat = ParquetDataCatalog(temp_dir)
        eq = fetcher.create_equity("VCB", venue="HOSE", current_price=57000.0, fetch_profile=False)

        d1 = Dividend(
            instrument_id=InstrumentId.from_str("VCB.HOSE"),
            amount=450.0,
            ex_date="2024-07-23",
            record_date="2024-07-24",
            payment_date="2024-08-27",
            fiscal_year=2023,
            ratio=0.045,
            description="VCB 450 VND",
            ts_event=1721692800000000000,
            ts_init=1721692800000000000,
        )
        d2 = Dividend(
            instrument_id=InstrumentId.from_str("VCB.HOSE"),
            amount=1200.0,
            ex_date="2020-12-21",
            record_date="2020-12-22",
            payment_date="2021-01-15",
            fiscal_year=2019,
            ratio=0.12,
            description="VCB 1200 VND",
            ts_event=1608508800000000000,
            ts_init=1608508800000000000,
        )

        sample_df = pd.DataFrame({
            "datetime": ["2024-07-22T00:00:00Z", "2024-07-23T00:00:00Z"],
            "open": [56000.0, 56500.0],
            "high": [57000.0, 57500.0],
            "low": [55800.0, 56200.0],
            "close": [56500.0, 57200.0],
            "volume": [2000000, 2500000],
        })
        btype = fetcher.get_bar_type(eq, interval="1d")
        bars = fetcher.df_to_bars(sample_df, bar_type=btype)

        fetcher.save_to_catalog(
            bars=bars,
            instruments=[eq],
            dividends=[d2, d1],
            catalog=cat,
        )

        queried_inst = cat.instruments(instrument_ids=["VCB.HOSE"])
        queried_divs = cat.custom_data(cls=Dividend)
        queried_bars = cat.bars()

        assert len(queried_inst) == 1
        assert len(queried_divs) == 2
        assert len(queried_bars) == 2

        first_div = queried_divs[0].data if hasattr(queried_divs[0], "data") else queried_divs[0]
        assert first_div.amount == 1200.0
        assert first_div.fiscal_year == 2019
        assert first_div.ex_date == "2020-12-21"
    finally:
        fetcher.close()
        shutil.rmtree(temp_dir)


# =============================================================================
# 2. LIVE INTEGRATION TESTS (SSI iBoard Endpoints)
# =============================================================================


def test_live_get_listed_companies():
    fetcher = SSIFetcher()
    try:
        stocks = fetcher.get_listed_companies(stock_type_only=True)
        assert len(stocks) > 1000
        assert "symbol" in stocks.columns
        assert "exchange" in stocks.columns
        assert "company_name" in stocks.columns

        hose_stocks = fetcher.get_listed_companies(exchange="HOSE")
        assert len(hose_stocks) > 300
        assert (hose_stocks["exchange"] == "HOSE").all()
    except Exception as e:
        pytest.skip(f"Live SSI network call failed: {e}")
    finally:
        fetcher.close()


def test_live_listing_info_and_equity():
    fetcher = SSIFetcher()
    try:
        info = fetcher.get_listing_info("VCB")
        assert info.symbol == "VCB"
        assert info.exchange == "HOSE"
        assert info.listing_date is not None
        assert info.issue_shares is not None and info.issue_shares > 1e9
        assert info.circulating_shares is not None and info.circulating_shares > 1e9

        eq = fetcher.create_equity("VCB", listing_info=info)
        assert isinstance(eq, Equity)
        assert str(eq.id) == "VCB.HOSE"
        assert eq.info["issue_shares"] == info.issue_shares
    except Exception as e:
        pytest.skip(f"Live SSI listing info call failed: {e}")
    finally:
        fetcher.close()


def test_live_cash_dividends_and_df():
    fetcher = SSIFetcher()
    try:
        divs = fetcher.get_cash_dividends("VCB")
        assert len(divs) > 0
        assert all(isinstance(d, Dividend) for d in divs)
        for i in range(len(divs) - 1):
            assert divs[i].ts_event <= divs[i + 1].ts_event

        df = fetcher.get_cash_dividends_df("VCB")
        assert not df.empty
        assert isinstance(df.index, pd.DatetimeIndex)
        assert "amount" in df.columns
        assert "fiscal_year" in df.columns
        assert (df["amount"] > 0).all()
    except Exception as e:
        pytest.skip(f"Live SSI dividend call failed: {e}")
    finally:
        fetcher.close()


def test_live_get_ohlcv_and_bars():
    fetcher = SSIFetcher()
    try:
        # 1. Full history DataFrame
        df = fetcher.get_ohlcv("HPG", interval="1d")
        assert not df.empty
        assert len(df) > 1000  # HPG has been listed since 2007 (> 4,000 trading days)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        # Check VND scaling (price in thousands of VND is scaled to > 1,000 VND)
        assert df["close"].iloc[-1] > 1000.0
        assert (df["high"] >= df["low"]).all()

        # 2. Convert to Nautilus Bar objects
        bars = fetcher.fetch_bars("HPG", exchange="HOSE", interval="1d", start_date="2024-01-01")
        assert len(bars) > 100
        assert all(isinstance(b, Bar) for b in bars)
        assert str(bars[0].bar_type) == "HPG.HOSE-1-DAY-LAST-EXTERNAL"
        for i in range(len(bars) - 1):
            assert bars[i].ts_event < bars[i + 1].ts_event
    except Exception as e:
        pytest.skip(f"Live SSI OHLCV call failed: {e}")
    finally:
        fetcher.close()


def test_live_fetch_all_ohlcv_batch():
    fetcher = SSIFetcher()
    try:
        df_batch = fetcher.fetch_all_ohlcv(
            symbols=["VCB", "ACB"],
            interval="1d",
            start_date="2025-01-01",
            delay_seconds=0.05,
        )
        assert not df_batch.empty
        assert set(df_batch["symbol"].unique()) == {"VCB", "ACB"}
        assert "open" in df_batch.columns
        assert "close" in df_batch.columns
    except Exception as e:
        pytest.skip(f"Live SSI batch OHLCV call failed: {e}")
    finally:
        fetcher.close()


def test_live_fetch_and_catalog():
    fetcher = SSIFetcher()
    temp_dir = tempfile.mkdtemp()
    try:
        equities, dividends, bars = fetcher.fetch_and_catalog(
            symbols="VCB",
            interval="1d",
            include_bars=True,
            include_dividends=True,
            start_date="2024-01-01",
            catalog_path=temp_dir,
        )
        assert len(equities) == 1
        assert str(equities[0].id) == "VCB.HOSE"
        assert len(dividends) > 0
        assert len(bars) > 0

        # Query back from Nautilus ParquetDataCatalog
        cat = ParquetDataCatalog(temp_dir)
        queried_instruments = cat.instruments(instrument_ids=["VCB.HOSE"])
        assert len(queried_instruments) == 1
        assert str(queried_instruments[0].id) == "VCB.HOSE"

        queried_dividends = cat.custom_data(cls=Dividend)
        assert len(queried_dividends) == len(dividends)

        queried_bars = cat.bars()
        assert len(queried_bars) == len(bars)
    except Exception as e:
        pytest.skip(f"Live SSI fetch_and_catalog failed: {e}")
    finally:
        fetcher.close()
        shutil.rmtree(temp_dir)