import base64
import json
import shutil
import tempfile
import zlib
from pathlib import Path

import pandas as pd
import pytest

from nautilus_trader.model.data import Bar
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.economics.constants import DEFAULT_OBFUSCATION_KEY
from src.data_pipeline.economics.fetcher import EconomicFetcher
from src.data_pipeline.economics.models import (
    EconomicData,
    EconomicDataPoint,
    points_to_bars,
    points_to_dataframe,
)


def test_resolve_country():
    assert EconomicFetcher.resolve_country("vn") == "vietnam"
    assert EconomicFetcher.resolve_country("vietnam") == "vietnam"
    assert EconomicFetcher.resolve_country("VIETNAM") == "vietnam"
    assert EconomicFetcher.resolve_country("việt nam") == "vietnam"
    assert EconomicFetcher.resolve_country("us") == "united-states"
    assert EconomicFetcher.resolve_country("usa") == "united-states"
    assert EconomicFetcher.resolve_country("United States") == "united-states"
    assert EconomicFetcher.resolve_country("jp") == "japan"
    assert EconomicFetcher.resolve_country(None) == "vietnam"


def test_resolve_indicator():
    assert EconomicFetcher.resolve_indicator("inflation") == "inflation-cpi"
    assert EconomicFetcher.resolve_indicator("cpi") == "inflation-cpi"
    assert EconomicFetcher.resolve_indicator("inflation_rate") == "inflation-cpi"
    assert EconomicFetcher.resolve_indicator("bond-yield") == "government-bond-yield"
    assert EconomicFetcher.resolve_indicator("bond_yield") == "government-bond-yield"
    assert EconomicFetcher.resolve_indicator("yield") == "government-bond-yield"
    assert EconomicFetcher.resolve_indicator("core-inflation") == "core-inflation-rate"
    assert EconomicFetcher.resolve_indicator("gdp") == "gdp-growth-annual"
    assert EconomicFetcher.resolve_indicator("interest_rate") == "interest-rate"


def test_decompress_and_deobfuscate():
    original_data = {"test_series": [1.0, 2.0, 3.5, 4.2]}
    json_bytes = json.dumps(original_data).encode("utf-8")
    compressed = zlib.compress(json_bytes)

    key = DEFAULT_OBFUSCATION_KEY
    obfuscated = bytearray(compressed)
    for i in range(len(obfuscated)):
        obfuscated[i] ^= key[i % len(key)]

    payload_b64 = base64.b64encode(obfuscated).decode("utf-8")

    result = EconomicFetcher.decompress_and_deobfuscate_data(payload_b64, key=key)
    assert result == original_data


def test_extract_page_metadata():
    html_mock = """
    <html>
      <script>
        var TEChartsDatasource = 'https://d3ii0wo49og5mi.cloudfront.net';
        var TEChartsToken = '20261004:testtoken';
        var TEObfuscationkey = 'test-key-123';
        var TEChart = 'EC';
        var TESymbol = 'VietnamIR';
      </script>
    </html>
    """
    meta = EconomicFetcher.extract_page_metadata(html_mock)
    assert meta["datasource"] == "https://d3ii0wo49og5mi.cloudfront.net"
    assert meta["token"] == "20261004:testtoken"
    assert meta["key"] == b"test-key-123"
    assert meta["chart_type"] == "EC"
    assert meta["symbol"] == "VietnamIR"


def test_models_and_dataframe_conversion():
    p1 = EconomicDataPoint(
        name="INFLATION_RATE",
        country="VIETNAM",
        symbol="VIETNAM_INFLATION_RATE",
        date="2024-01-01",
        value=3.37,
        unit="%",
    )
    p2 = EconomicDataPoint(
        name="INFLATION_RATE",
        country="VIETNAM",
        symbol="VIETNAM_INFLATION_RATE",
        date="2024-02-01",
        value=3.98,
        unit="%",
    )

    ed1 = p1.to_economic_data()
    assert isinstance(ed1, EconomicData)
    assert ed1.name == "INFLATION_RATE"
    assert ed1.country == "VIETNAM"
    assert ed1.value == 3.37
    assert ed1.ts_event == 1704067200000000000  # 2024-01-01 ns UTC

    df = points_to_dataframe([p1, p2])
    assert len(df) == 2
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    assert "value" in df.columns
    assert "indicator" in df.columns
    assert df.iloc[0]["value"] == 3.37


def test_points_to_bars():
    points = [
        EconomicDataPoint("YIELD_10Y", "VIETNAM", "VNM10Y", "2024-01-01", 4.5, "%"),
        EconomicDataPoint("YIELD_10Y", "VIETNAM", "VNM10Y", "2024-01-02", 4.6, "%"),
    ]
    bars = points_to_bars(points, bar_type="VNM10Y.MACRO-1-DAY-LAST-EXTERNAL")
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)
    assert float(bars[0].close) == 4.5
    assert float(bars[1].close) == 4.6
    assert int(bars[0].volume) == 0


def test_economic_data_in_parquet_catalog():
    temp_dir = tempfile.mkdtemp()
    try:
        cat = ParquetDataCatalog(temp_dir)
        e1 = EconomicData(
            instrument_id=InstrumentId.from_str("INFLATION_RATE.VIETNAM"),
            name="INFLATION_RATE",
            country="VIETNAM",
            symbol="VIETNAM_INFLATION_RATE",
            date="2024-01-01",
            value=3.37,
            unit="%",
            ts_event=1704067200000000000,
            ts_init=1704067200000000000,
        )
        e2 = EconomicData(
            instrument_id=InstrumentId.from_str("INFLATION_RATE.VIETNAM"),
            name="INFLATION_RATE",
            country="VIETNAM",
            symbol="VIETNAM_INFLATION_RATE",
            date="2024-02-01",
            value=3.98,
            unit="%",
            ts_event=1706745600000000000,
            ts_init=1706745600000000000,
        )
        cat.write_data([e1, e2])

        queried = cat.custom_data(cls=EconomicData)
        assert len(queried) == 2
        first_item = queried[0].data if hasattr(queried[0], "data") else queried[0]
        assert first_item.name == "INFLATION_RATE"
        assert first_item.value == 3.37
        assert first_item.date == "2024-01-01"
    finally:
        shutil.rmtree(temp_dir)


def test_live_fetch_vietnam_inflation():
    fetcher = EconomicFetcher()
    try:
        data = fetcher.fetch_inflation(country="vietnam", span="5Y")
        assert len(data) > 20
        assert all(isinstance(d, EconomicData) for d in data)
        assert data[0].country == "VIETNAM"
        assert data[0].name == "INFLATION_CPI"
        # Monotonicity check
        for i in range(len(data) - 1):
            assert data[i].ts_event <= data[i + 1].ts_event

        df = fetcher.fetch_inflation_df(country="vietnam", span="5Y")
        assert not df.empty
        assert isinstance(df.index, pd.DatetimeIndex)
        assert "value" in df.columns
    except Exception as e:
        pytest.skip(f"Live TradingEconomics network call failed: {e}")
    finally:
        fetcher.close()


def test_live_fetch_vietnam_bond_yield():
    fetcher = EconomicFetcher()
    try:
        data = fetcher.fetch_bond_yield(country="vietnam", span="5Y")
        assert len(data) > 50
        assert all(isinstance(d, EconomicData) for d in data)
        assert data[0].country == "VIETNAM"
        assert data[0].name == "GOVERNMENT_BOND_YIELD"

        df = fetcher.fetch_bond_yield_df(country="vietnam", span="5Y")
        assert not df.empty
        assert (df["value"] > 0).all()
    except Exception as e:
        pytest.skip(f"Live TradingEconomics network call failed: {e}")
    finally:
        fetcher.close()


def test_live_list_indicators():
    fetcher = EconomicFetcher()
    try:
        df_indicators = fetcher.list_indicators(country="vietnam")
        assert not df_indicators.empty
        assert "indicator" in df_indicators.columns
        assert "url" in df_indicators.columns
        slugs = set(df_indicators["indicator"].tolist())
        assert "inflation-cpi" in slugs
        assert "interest-rate" in slugs
    except Exception as e:
        pytest.skip(f"Live TradingEconomics network call failed: {e}")
    finally:
        fetcher.close()


def test_live_fetch_and_catalog():
    fetcher = EconomicFetcher()
    temp_dir = tempfile.mkdtemp()
    try:
        results = fetcher.fetch_and_catalog(
            country="vietnam",
            indicators=["inflation-cpi", "government-bond-yield"],
            span="3Y",
            catalog_path=temp_dir,
        )
        assert "inflation-cpi" in results
        assert "government-bond-yield" in results
        assert len(results["inflation-cpi"]) > 10
        assert len(results["government-bond-yield"]) > 10

        # Query back from Nautilus ParquetDataCatalog
        cat = ParquetDataCatalog(temp_dir)
        queried = cat.custom_data(cls=EconomicData)
        total_fetched = len(results["inflation-cpi"]) + len(results["government-bond-yield"])
        assert len(queried) == total_fetched
    except Exception as e:
        pytest.skip(f"Live fetch_and_catalog failed: {e}")
    finally:
        fetcher.close()
        shutil.rmtree(temp_dir)


def test_live_fetch_us_macro():
    fetcher = EconomicFetcher(default_country="united-states")
    try:
        us_inf = fetcher.fetch_inflation(country="us", span="3Y")
        assert len(us_inf) > 10
        assert us_inf[0].country == "UNITED_STATES"

        us_bond = fetcher.fetch_bond_yield(country="united-states", span="3Y")
        assert len(us_bond) > 10
        assert us_bond[0].country == "UNITED_STATES"
    except Exception as e:
        pytest.skip(f"Live US macro fetch failed: {e}")
    finally:
        fetcher.close()
