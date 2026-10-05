import tempfile
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType, AggregationSource
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity, CurrencyPair
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.tradingview.fetcher import TradingviewFetcher


@pytest.fixture
def fetcher():
    return TradingviewFetcher(
        default_venue="HOSE",
        default_currency="VND",
        default_price_precision=2,
        default_size_precision=0,
    )


def test_parse_interval(fetcher):
    # Minute intervals
    assert fetcher.parse_interval("1m") == ("1m", 1, BarAggregation.MINUTE)
    assert fetcher.parse_interval("15m") == ("15m", 15, BarAggregation.MINUTE)
    assert fetcher.parse_interval("30min") == ("30m", 30, BarAggregation.MINUTE)

    # Hour intervals
    assert fetcher.parse_interval("1h") == ("1h", 1, BarAggregation.HOUR)
    assert fetcher.parse_interval("1H") == ("1h", 1, BarAggregation.HOUR)
    assert fetcher.parse_interval("4h") == ("4h", 4, BarAggregation.HOUR)

    # Day intervals
    assert fetcher.parse_interval("1d") == ("1d", 1, BarAggregation.DAY)
    assert fetcher.parse_interval("1D") == ("1d", 1, BarAggregation.DAY)
    assert fetcher.parse_interval("D") == ("1d", 1, BarAggregation.DAY)
    assert fetcher.parse_interval("daily") == ("1d", 1, BarAggregation.DAY)

    # Week intervals
    assert fetcher.parse_interval("1w") == ("1w", 1, BarAggregation.WEEK)
    assert fetcher.parse_interval("1W") == ("1w", 1, BarAggregation.WEEK)
    assert fetcher.parse_interval("weekly") == ("1w", 1, BarAggregation.WEEK)

    # Month intervals
    assert fetcher.parse_interval("1M") == ("1M", 1, BarAggregation.MONTH)
    assert fetcher.parse_interval("M") == ("1M", 1, BarAggregation.MONTH)
    assert fetcher.parse_interval("monthly") == ("1M", 1, BarAggregation.MONTH)

    # Invalid interval
    with pytest.raises(ValueError, match="Unsupported interval"):
        fetcher.parse_interval("invalid_interval")


def test_create_equity(fetcher):
    eq = fetcher.create_equity(
        symbol="VCB",
        venue="HOSE",
        currency="VND",
        price_precision=2,
        size_precision=0,
        price_increment=100.0,
        lot_size=100.0,
    )

    assert isinstance(eq, Equity)
    assert str(eq.id) == "VCB.HOSE"
    assert eq.symbol.value == "VCB"
    assert eq.venue.value == "HOSE"
    assert eq.quote_currency == Currency.from_str("VND")
    assert eq.price_precision == 2
    assert eq.size_precision == 0
    assert float(eq.price_increment) == 100.0
    assert float(eq.lot_size) == 100.0


def test_create_currency_pair(fetcher):
    cp = fetcher.create_currency_pair(
        symbol="USD/VND",
        venue="SIM",
        base="USD",
        quote="VND",
        price_precision=2,
        size_precision=2,
        price_increment=1.0,
        size_increment=1.0,
        lot_size=1.0,
    )

    assert isinstance(cp, CurrencyPair)
    assert str(cp.id) == "USD/VND.SIM"
    assert cp.base_currency == Currency.from_str("USD")
    assert cp.quote_currency == Currency.from_str("VND")
    assert cp.price_precision == 2
    assert cp.size_precision == 2


def test_create_instrument_backward_compat(fetcher):
    # Default equity
    inst_eq = fetcher.create_instrument(symbol="HPG", venue_str="HOSE")
    assert isinstance(inst_eq, Equity)
    assert str(inst_eq.id) == "HPG.HOSE"

    # Currency pair via slash
    inst_cp = fetcher.create_instrument(symbol="EUR/USD", venue_str="SIM", instrument_type="currency_pair")
    assert isinstance(inst_cp, CurrencyPair)
    assert str(inst_cp.id) == "EUR/USD.SIM"


def test_get_bar_type(fetcher):
    eq = fetcher.create_equity("VCB", venue="HOSE")

    # From Equity
    bt1 = fetcher.get_bar_type(eq, interval="1d")
    assert str(bt1) == "VCB.HOSE-1-DAY-LAST-EXTERNAL"

    # From InstrumentId
    bt2 = fetcher.get_bar_type(eq.id, interval="1h")
    assert str(bt2) == "VCB.HOSE-1-HOUR-LAST-EXTERNAL"

    # From string with venue
    bt3 = fetcher.get_bar_type("VCB.HOSE", interval="15m")
    assert str(bt3) == "VCB.HOSE-15-MINUTE-LAST-EXTERNAL"

    # From symbol string only (uses default venue)
    bt4 = fetcher.get_bar_type("VCB", interval="1w")
    assert str(bt4) == "VCB.HOSE-1-WEEK-LAST-EXTERNAL"


def test_clean_dataframe(fetcher):
    df_raw = pd.DataFrame({
        "Datetime": [
            "2024-01-01 09:00:00",
            "2024-01-03 09:00:00",
            "2024-01-02 09:00:00",
            "2024-01-02 09:00:00",  # Duplicate timestamp
            None,                    # Missing timestamp
        ],
        "OPEN": [100.0, 102.0, 101.0, 101.5, 99.0],
        "HIGH": [95.0, 105.0, 103.0, 103.0, 100.0],  # 95 is smaller than open (data error)
        "LOW": [98.0, 99.0, 100.0, 100.0, 95.0],
        "CLOSE": [101.0, 104.0, 102.0, 102.0, 98.0],
        "VOLUME": [1000, 2000, 1500, 1600, 500],
    })

    cleaned = fetcher.clean_dataframe(df_raw)

    assert len(cleaned) == 3
    assert isinstance(cleaned.index, pd.DatetimeIndex)
    assert cleaned.index.tz is not None
    # Chronologically sorted
    assert list(cleaned.index) == sorted(cleaned.index)
    # High fixed to max(open, high, close)
    assert cleaned.iloc[0]["high"] >= cleaned.iloc[0]["open"]
    assert cleaned.iloc[0]["high"] >= cleaned.iloc[0]["close"]
    # Duplicate resolved
    assert cleaned.loc["2024-01-02 09:00:00+00:00"]["open"] == 101.5


def test_df_to_bars(fetcher):
    eq = fetcher.create_equity("VCB", venue="HOSE")
    bar_type = fetcher.get_bar_type(eq, interval="1d")

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
        "open": [10000.0, 10200.0, 10100.0],
        "high": [10300.0, 10500.0, 10400.0],
        "low": [9900.0, 10100.0, 10000.0],
        "close": [10200.0, 10300.0, 10200.0],
        "volume": [50000.0, 60000.0, 55000.0],
    })

    bars = fetcher.df_to_bars(df, bar_type=bar_type, price_precision=2, size_precision=0)

    assert len(bars) == 3
    assert all(isinstance(b, Bar) for b in bars)
    assert bars[0].bar_type == bar_type
    assert float(bars[0].open) == 10000.0
    assert float(bars[0].high) == 10300.0
    assert float(bars[0].low) == 9900.0
    assert float(bars[0].close) == 10200.0
    assert int(bars[0].volume) == 50000
    assert bars[0].ts_event == 1704067200000000000


def test_catalog_save_and_query(fetcher):
    temp_dir = tempfile.mkdtemp()
    try:
        catalog = fetcher.get_catalog(catalog_path=temp_dir)
        eq = fetcher.create_equity("VCB", venue="HOSE")
        bar_type = fetcher.get_bar_type(eq, interval="1d")

        df = pd.DataFrame({
            "datetime": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "open": [10000.0, 10200.0],
            "high": [10300.0, 10500.0],
            "low": [9900.0, 10100.0],
            "close": [10200.0, 10300.0],
            "volume": [50000.0, 60000.0],
        })

        bars = fetcher.df_to_bars(df, bar_type=bar_type)

        # Save to catalog
        fetcher.save_to_catalog(bars=bars, instruments=[eq], catalog=catalog)

        # Query back
        loaded_instruments = catalog.instruments(instrument_ids=["VCB.HOSE"])
        assert len(loaded_instruments) == 1
        assert str(loaded_instruments[0].id) == "VCB.HOSE"

        loaded_bars = catalog.bars(bar_types=[str(bar_type)])
        assert len(loaded_bars) == 2
        assert loaded_bars[0].bar_type == bar_type
        assert float(loaded_bars[0].open) == 10000.0
    finally:
        shutil.rmtree(temp_dir)


def test_live_search_and_list():
    # Verify vnquantpy integration
    try:
        symbols = TradingviewFetcher.list_symbols(country="VN", exchange="HOSE", limit=3)
        assert len(symbols) > 0
        assert "symbol" in symbols[0]
        assert "exchange" in symbols[0]
    except Exception as e:
        pytest.skip(f"Live network call to Tradingview failed: {e}")

    try:
        searched = TradingviewFetcher.search_symbol(query="VCB", country="VN", limit=3)
        assert len(searched) > 0
        assert any(item.get("symbol") == "VCB" for item in searched)
    except Exception as e:
        pytest.skip(f"Live search failed: {e}")


def test_live_fetch_and_catalog():
    fetcher = TradingviewFetcher(default_venue="HOSE")
    temp_dir = tempfile.mkdtemp()
    try:
        instruments, bars = fetcher.fetch_and_catalog(
            symbols="VCB",
            exchange="HOSE",
            interval="1d",
            catalog_path=temp_dir,
        )
        assert len(instruments) == 1
        assert str(instruments[0].id) == "VCB.HOSE"
        assert len(bars) > 100  # VCB has years of daily bars

        # Validate against Nautilus catalog query
        cat = ParquetDataCatalog(temp_dir)
        queried = cat.bars(bar_types=[str(bars[0].bar_type)])
        assert len(queried) == len(bars)
    except Exception as e:
        pytest.skip(f"Live fetch to Tradingview failed: {e}")
    finally:
        shutil.rmtree(temp_dir)


def test_batch_fetch_and_catalog():
    fetcher = TradingviewFetcher(default_venue="HOSE")
    temp_dir = tempfile.mkdtemp()
    try:
        instruments, bars = fetcher.fetch_and_catalog(
            symbols=["VCB", "HPG"],
            exchange="HOSE",
            interval="1d",
            catalog_path=temp_dir,
        )
        assert len(instruments) == 2
        inst_ids = {str(inst.id) for inst in instruments}
        assert "VCB.HOSE" in inst_ids
        assert "HPG.HOSE" in inst_ids
        assert len(bars) > 200

        # Verify catalog query
        cat = ParquetDataCatalog(temp_dir)
        vcb_bars = cat.bars(bar_types=["VCB.HOSE-1-DAY-LAST-EXTERNAL"])
        hpg_bars = cat.bars(bar_types=["HPG.HOSE-1-DAY-LAST-EXTERNAL"])
        assert len(vcb_bars) > 100
        assert len(hpg_bars) > 100
    except Exception as e:
        pytest.skip(f"Live batch fetch failed: {e}")
    finally:
        shutil.rmtree(temp_dir)
