from __future__ import annotations

import base64
import json
import logging
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.economics.constants import (
    BOND_YIELD_INDICATOR,
    CORE_INFLATION_INDICATOR,
    COUNTRY_ALIASES,
    DATASOURCE_BASE_URL,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_CHARTS_TOKEN,
    DEFAULT_COUNTRY,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_OBFUSCATION_KEY,
    DEFAULT_SPAN,
    DEFAULT_TIMEOUT,
    FEATS_IGNORED,
    HOME_URL,
    INDICATOR_ALIASES,
    INFLATION_INDICATOR,
    RETRY_STATUS_CODES,
)
from src.data_pipeline.economics.models import (
    EconomicData,
    EconomicDataPoint,
    points_to_bars,
    points_to_dataframe,
)

logger = logging.getLogger(__name__)


class EconomicFetcher:
    """Fetcher for country macroeconomic indicators (inflation, bond yields, etc.) with Nautilus Trader integration."""

    def __init__(
        self,
        default_country: str = DEFAULT_COUNTRY,
        *,
        base_url: str = HOME_URL,
        datasource_url: str = DATASOURCE_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        catalog_path: str | Path | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initializes EconomicFetcher.

        Parameters
        ----------
        default_country : str, default 'vietnam'
            Default country slug or alias (e.g. 'vietnam', 'united-states', 'vn', 'us').
        base_url : str, default 'https://tradingeconomics.com'
            Root website URL.
        datasource_url : str, default 'https://d3ii0wo49og5mi.cloudfront.net'
            Cloudfront data source API endpoint.
        timeout : float, default 15.0
            Request timeout in seconds.
        max_retries : int, default 3
            Maximum retries on connection issues or 429/5xx status codes.
        backoff_factor : float, default 0.5
            Exponential backoff factor for retries.
        catalog_path : str | Path, optional
            Default path for Nautilus Trader ParquetDataCatalog root directory.
        headers : dict[str, str], optional
            Custom request headers.
        """
        self.default_country = self.resolve_country(default_country)
        self.base_url = base_url.rstrip("/")
        self.datasource_url = datasource_url.rstrip("/")
        self.timeout = timeout
        self.catalog_path = Path(catalog_path).expanduser().resolve() if catalog_path else None

        self._session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=RETRY_STATUS_CODES,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update(DEFAULT_HEADERS)
        if headers:
            self._session.headers.update(headers)

    def close(self) -> None:
        """Closes the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> EconomicFetcher:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Country & Indicator Slug Normalization
    # -------------------------------------------------------------------------

    @staticmethod
    def resolve_country(country: str | None) -> str:
        """Resolves country name or alias to canonical TradingEconomics country slug."""
        if not country:
            return DEFAULT_COUNTRY
        clean = country.strip().lower()
        return COUNTRY_ALIASES.get(clean, clean.replace(" ", "-"))

    @staticmethod
    def resolve_indicator(indicator: str) -> str:
        """Resolves indicator name or alias to canonical TradingEconomics indicator slug."""
        clean = indicator.strip().lower()
        if clean in INDICATOR_ALIASES:
            return INDICATOR_ALIASES[clean]
        # Normalize uppercase/underscore to kebab-case
        slug = clean.replace("_", "-").replace(" ", "-")
        return INDICATOR_ALIASES.get(slug, slug)

    # -------------------------------------------------------------------------
    # Deobfuscation and Metadata Extraction
    # -------------------------------------------------------------------------

    @staticmethod
    def decompress_and_deobfuscate_data(
        payload: str | bytes,
        key: bytes = DEFAULT_OBFUSCATION_KEY,
    ) -> Any:
        """Deobfuscates XOR cipher and inflates zlib compressed TradingEconomics payload."""
        if isinstance(payload, bytes):
            payload_str = payload.decode("utf-8")
        else:
            payload_str = payload.strip()

        if payload_str.startswith('"'):
            payload_str = json.loads(payload_str)

        missing_padding = len(payload_str) % 4
        if missing_padding:
            payload_str += "=" * (4 - missing_padding)

        raw_bytes = bytearray(base64.b64decode(payload_str))
        for i in range(len(raw_bytes)):
            raw_bytes[i] ^= key[i % len(key)]

        decompressed = None
        for wbits in (zlib.MAX_WBITS | 32, -zlib.MAX_WBITS, zlib.MAX_WBITS):
            try:
                decompressed = zlib.decompress(raw_bytes, wbits)
                break
            except Exception:
                continue

        if decompressed is None:
            raise ValueError("Failed to decompress TradingEconomics payload.")

        return json.loads(decompressed.decode("utf-8"))

    @staticmethod
    def extract_page_metadata(html: str) -> dict[str, Any]:
        """Extracts chart metadata, datasource URL, token, and API symbols from indicator HTML page."""
        m_ds = re.search(r"var\s+TEChartsDatasource\s*=\s*['\"]([^'\"]+)['\"]", html)
        datasource = m_ds.group(1) if m_ds else DATASOURCE_BASE_URL

        m_tk = re.search(r"var\s+TEChartsToken\s*=\s*['\"]([^'\"]+)['\"]", html)
        token = m_tk.group(1) if m_tk else DEFAULT_CHARTS_TOKEN

        m_key = re.search(r"var\s+TEObfuscationkey\s*=\s*['\"]([^'\"]+)['\"]", html)
        key = m_key.group(1).encode("utf-8") if m_key else DEFAULT_OBFUSCATION_KEY

        charts = [m for m in re.findall(r"TEChart\s*=\s*['\"]([^'\"]+)['\"]", html) if m]
        chart_type = charts[-1] if charts else "EC"

        meta_syms = re.findall(r'"symbol":"([^"]+)"', html)
        te_syms = [m for m in re.findall(r"TESymbol\s*=\s*['\"]([^'\"]+)['\"]", html) if m]
        m_img = re.search(r"charts/[^?]+\.png\?s=([^&\"'\s]+)", html)
        img_s = m_img.group(1) if m_img else None

        if chart_type == "MK" and meta_syms:
            api_symbol = meta_syms[0]
        elif te_syms:
            api_symbol = te_syms[-1]
        elif img_s:
            api_symbol = img_s
        elif meta_syms:
            api_symbol = meta_syms[0]
        else:
            api_symbol = ""

        return {
            "chart_type": chart_type,
            "symbol": api_symbol,
            "datasource": datasource,
            "token": token,
            "key": key,
        }

    # -------------------------------------------------------------------------
    # Raw Data Fetching & Parsing
    # -------------------------------------------------------------------------

    def fetch_raw_points(
        self,
        indicator: str,
        country: str | None = None,
        span: str = DEFAULT_SPAN,
        interval: str | None = None,
    ) -> list[EconomicDataPoint]:
        """Fetches raw observation points from TradingEconomics."""
        resolved_country = self.resolve_country(country or self.default_country)
        resolved_indicator = self.resolve_indicator(indicator)

        page_url = f"{self.base_url}/{resolved_country}/{resolved_indicator}"
        logger.debug("Requesting economic indicator page: %s", page_url)

        try:
            page_resp = self._session.get(page_url, timeout=self.timeout)
            page_resp.raise_for_status()
        except requests.exceptions.RequestException as err:
            logger.error("Failed to fetch indicator page %s: %s", page_url, err)
            raise ConnectionError(f"Failed to fetch indicator page {page_url}: {err}") from err

        meta = self.extract_page_metadata(page_resp.text)
        api_symbol = meta["symbol"]
        if not api_symbol:
            raise ValueError(f"Could not extract API symbol from page '{page_url}'.")

        span_str = span.lower() if span else "10y"
        datasource = meta["datasource"]

        if meta["chart_type"] == "MK":
            api_url = f"{datasource}/markets/{api_symbol}?span={span_str}&ohlc=0"
            if interval:
                api_url += f"&interval={interval.lower()}"
        else:
            api_url = f"{datasource}/economics/{api_symbol.lower()}?span={span_str}"
            if interval:
                api_url += f"&interval={interval.lower()}"

        api_headers = {
            "User-Agent": self._session.headers.get("User-Agent", DEFAULT_HEADERS["User-Agent"]),
            "x-api-key": meta["token"],
            "Referer": page_url,
        }

        logger.debug("Requesting economic data API: %s", api_url)
        try:
            api_resp = self._session.get(api_url, headers=api_headers, timeout=self.timeout)
            api_resp.raise_for_status()
        except requests.exceptions.RequestException as err:
            logger.error("Failed to fetch chart API data %s: %s", api_url, err)
            raise ConnectionError(f"Failed to fetch chart API data {api_url}: {err}") from err

        data = self.decompress_and_deobfuscate_data(api_resp.text, meta["key"])

        canonical_name = resolved_indicator.replace("-", "_").upper()
        country_upper = resolved_country.replace("-", "_").upper()
        series_symbol = f"{country_upper}_{canonical_name}"
        inst_id = InstrumentId(Symbol(canonical_name), Venue(country_upper))
        unit = "%" if ("rate" in resolved_indicator or "yield" in resolved_indicator or "cpi" in resolved_indicator) else "points"

        points: list[EconomicDataPoint] = []

        # Markets format: dict with 'series' list -> item['data'] = [[ts, val, ...], ...]
        if isinstance(data, dict) and "series" in data:
            series_list = data.get("series", [])
            if series_list:
                raw_pts = series_list[0].get("data", [])
                for pt in raw_pts:
                    if not pt or len(pt) < 2 or pt[1] is None:
                        continue
                    dt_str = datetime.fromtimestamp(pt[0], tz=timezone.utc).strftime("%Y-%m-%d")
                    points.append(
                        EconomicDataPoint(
                            name=canonical_name,
                            country=country_upper,
                            symbol=series_symbol,
                            date=dt_str,
                            value=float(pt[1]),
                            unit=unit,
                            instrument_id=inst_id,
                        )
                    )

        # Economics format: list of dicts -> item['series'][0]['serie']['data']
        elif isinstance(data, list) and data:
            item = data[0] if isinstance(data[0], dict) else {}
            series_list = item.get("series", [])
            if series_list:
                first_serie = series_list[0]
                serie = first_serie.get("serie", first_serie)
                raw_pts = serie.get("data", [])
                for pt in raw_pts:
                    if not pt or pt[0] is None:
                        continue
                    val = float(pt[0])
                    if len(pt) >= 4 and isinstance(pt[3], str) and pt[3]:
                        dt_str = pt[3].split("T")[0]
                    elif len(pt) >= 2 and isinstance(pt[1], (int, float)):
                        dt_str = datetime.fromtimestamp(pt[1], tz=timezone.utc).strftime("%Y-%m-%d")
                    else:
                        continue
                    points.append(
                        EconomicDataPoint(
                            name=canonical_name,
                            country=country_upper,
                            symbol=series_symbol,
                            date=dt_str,
                            value=val,
                            unit=unit,
                            instrument_id=inst_id,
                        )
                    )

        # Sort ascending by date to guarantee monotonicity
        points.sort(key=lambda p: p.date)
        return points

    # -------------------------------------------------------------------------
    # Nautilus EconomicData & DataFrame APIs
    # -------------------------------------------------------------------------

    def fetch_series(
        self,
        indicator: str,
        country: str | None = None,
        span: str = DEFAULT_SPAN,
        interval: str | None = None,
    ) -> list[EconomicData]:
        """Fetches historical time-series data for an economic indicator as Nautilus EconomicData objects.

        Parameters
        ----------
        indicator : str
            Indicator name or slug (e.g. 'inflation-cpi', 'government-bond-yield', 'interest-rate').
        country : str, optional
            Country name or alias (e.g. 'vietnam', 'united-states'). Defaults to instance default.
        span : str, default '10Y'
            Date span: '1Y', '3Y', '5Y', '10Y', '25Y', 'MAX'.
        interval : str, optional
            Frequency interval: '1d', '1w', '1M'.

        Returns
        -------
        list[EconomicData]
            List of Nautilus Trader EconomicData custom data objects sorted monotonically by ts_event.
        """
        raw_pts = self.fetch_raw_points(
            indicator=indicator,
            country=country,
            span=span,
            interval=interval,
        )
        return [p.to_economic_data() for p in raw_pts]

    def fetch_series_df(
        self,
        indicator: str,
        country: str | None = None,
        span: str = DEFAULT_SPAN,
        interval: str | None = None,
    ) -> pd.DataFrame:
        """Fetches historical time-series data for an indicator as a pandas DataFrame with UTC DatetimeIndex.

        Columns: ['value', 'indicator', 'country', 'symbol', 'unit']
        Index: 'datetime' (UTC pd.DatetimeIndex)
        """
        data_list = self.fetch_series(
            indicator=indicator,
            country=country,
            span=span,
            interval=interval,
        )
        return points_to_dataframe(data_list)

    # -------------------------------------------------------------------------
    # Convenience Indicators: Inflation & Bond Yields
    # -------------------------------------------------------------------------

    def fetch_inflation(
        self,
        country: str | None = None,
        core: bool = False,
        span: str = DEFAULT_SPAN,
    ) -> list[EconomicData]:
        """Convenience method to fetch inflation rate (CPI or Core Inflation)."""
        indicator = CORE_INFLATION_INDICATOR if core else INFLATION_INDICATOR
        return self.fetch_series(indicator=indicator, country=country, span=span)

    def fetch_inflation_df(
        self,
        country: str | None = None,
        core: bool = False,
        span: str = DEFAULT_SPAN,
    ) -> pd.DataFrame:
        """Convenience method to fetch inflation rate as a DataFrame with UTC DatetimeIndex."""
        data_list = self.fetch_inflation(country=country, core=core, span=span)
        return points_to_dataframe(data_list)

    def fetch_bond_yield(
        self,
        country: str | None = None,
        span: str = DEFAULT_SPAN,
        interval: str | None = "1w",
    ) -> list[EconomicData]:
        """Convenience method to fetch benchmark 10-year government bond yield."""
        return self.fetch_series(
            indicator=BOND_YIELD_INDICATOR,
            country=country,
            span=span,
            interval=interval,
        )

    def fetch_bond_yield_df(
        self,
        country: str | None = None,
        span: str = DEFAULT_SPAN,
        interval: str | None = "1w",
    ) -> pd.DataFrame:
        """Convenience method to fetch benchmark government bond yield as a DataFrame with UTC DatetimeIndex."""
        data_list = self.fetch_bond_yield(country=country, span=span, interval=interval)
        return points_to_dataframe(data_list)

    # -------------------------------------------------------------------------
    # Indicator Discovery
    # -------------------------------------------------------------------------

    def list_indicators(
        self,
        country: str | None = None,
    ) -> pd.DataFrame:
        """Discovers all available economic indicator slugs and URLs for a country from TradingEconomics."""
        resolved_country = self.resolve_country(country or self.default_country)
        url = f"{self.base_url}/{resolved_country}/indicators"

        try:
            res = self._session.get(url, timeout=self.timeout)
            res.raise_for_status()
        except requests.exceptions.RequestException as err:
            logger.error("Failed to list indicators for %s: %s", resolved_country, err)
            raise ConnectionError(f"Failed to list indicators for {resolved_country}: {err}") from err

        pattern = rf'href=[\"\'](/{resolved_country}/[a-zA-Z0-9_\-]+)[\"\']'
        raw_links = list(dict.fromkeys(re.findall(pattern, res.text)))

        records = []
        for path in raw_links:
            feat = path.split("/")[-1]
            if feat in FEATS_IGNORED:
                continue
            full_url = f"{self.base_url}{path}"
            code = f"{resolved_country.replace('-', '_').upper()}_{feat.replace('-', '_').upper()}"
            records.append({
                "country": resolved_country,
                "indicator": feat,
                "url": full_url,
                "code": code,
            })

        return pd.DataFrame(records)

    # -------------------------------------------------------------------------
    # Nautilus ParquetDataCatalog Persistence
    # -------------------------------------------------------------------------

    def get_catalog(self, catalog_path: str | Path | None = None) -> ParquetDataCatalog:
        """Returns or creates a Nautilus ParquetDataCatalog instance."""
        target_path = Path(catalog_path).expanduser().resolve() if catalog_path else self.catalog_path
        if target_path is None:
            raise ValueError(
                "Catalog path is required. Provide 'catalog_path' to method or initialize EconomicFetcher(catalog_path=...)."
            )
        target_path.mkdir(parents=True, exist_ok=True)
        return ParquetDataCatalog(str(target_path))

    def save_to_catalog(
        self,
        data: list[EconomicData] | dict[str, list[EconomicData]],
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> ParquetDataCatalog:
        """Writes EconomicData custom data directly into a Nautilus ParquetDataCatalog."""
        cat = catalog or self.get_catalog(catalog_path)

        if isinstance(data, dict):
            for _, items in data.items():
                if items:
                    cat.write_data(items)
        elif data:
            cat.write_data(data)

        return cat

    def fetch_and_catalog(
        self,
        country: str | None = None,
        indicators: Sequence[str] | str = (INFLATION_INDICATOR, BOND_YIELD_INDICATOR),
        span: str = DEFAULT_SPAN,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> dict[str, list[EconomicData]]:
        """End-to-end pipeline: fetches macroeconomic series and persists to Nautilus ParquetDataCatalog.

        Returns
        -------
        dict[str, list[EconomicData]]
            Mapping of indicator slug to list of saved EconomicData objects.
        """
        indicator_list = [indicators] if isinstance(indicators, str) else list(indicators)
        cat = catalog or self.get_catalog(catalog_path)

        results: dict[str, list[EconomicData]] = {}
        for ind in indicator_list:
            clean_ind = self.resolve_indicator(ind)
            try:
                data_items = self.fetch_series(indicator=clean_ind, country=country, span=span)
                if data_items:
                    self.save_to_catalog(data=data_items, catalog=cat)
                    results[clean_ind] = data_items
            except Exception as err:
                logger.error("Failed to fetch and catalog %s for %s: %s", clean_ind, country, err)

        return results
