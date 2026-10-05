from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair, Equity, Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.ssi.constants import (
    CAP_AND_DIVIDEND_ENDPOINT,
    CHARTS_HISTORY_ENDPOINT,
    COMPANY_PROFILE_ENDPOINT,
    CORPORATE_ACTIONS_ENDPOINT,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    IBOARD_API_BASE_URL,
    IBOARD_QUERY_BASE_URL,
    MARKET_INDICES,
    RETRY_STATUS_CODES,
    SECTORS_DATA_ENDPOINT,
    STOCK_INFO_ENDPOINT,
)
from src.data_pipeline.ssi.models import (
    CompanyListingInfo,
    Dividend,
    calculate_price_increment,
)
from src.utils.time import datetime_to_nanoseconds, to_nanoseconds_array

logger = logging.getLogger(__name__)

# Supported interval mapping:
# key -> (normalized_interval, ssi_base_resolution, step, BarAggregation, pandas_resample_rule)
INTERVAL_LOOKUP: dict[str, tuple[str, str, int, BarAggregation, str | None]] = {
    "1m": ("1m", "1", 1, BarAggregation.MINUTE, None),
    "3m": ("3m", "1", 3, BarAggregation.MINUTE, "3min"),
    "5m": ("5m", "5", 5, BarAggregation.MINUTE, None),
    "15m": ("15m", "15", 15, BarAggregation.MINUTE, None),
    "30m": ("30m", "30", 30, BarAggregation.MINUTE, None),
    "45m": ("45m", "15", 45, BarAggregation.MINUTE, "45min"),
    "1h": ("1h", "60", 1, BarAggregation.HOUR, None),
    "2h": ("2h", "60", 2, BarAggregation.HOUR, "2h"),
    "3h": ("3h", "60", 3, BarAggregation.HOUR, "3h"),
    "4h": ("4h", "60", 4, BarAggregation.HOUR, "4h"),
    "1d": ("1d", "1D", 1, BarAggregation.DAY, None),
    "1w": ("1w", "1W", 1, BarAggregation.WEEK, None),
    "1M": ("1M", "1M", 1, BarAggregation.MONTH, None),
}

# Epoch timestamp for 2000-01-01 00:00:00 UTC (captures full Vietnam stock market history)
VN_MARKET_GENESIS_TS: int = 946684800


def _parse_ssi_date(date_val: Any) -> str | None:
    """Parses date string from SSI (e.g. '30/06/2009', '2009-06-30') into 'YYYY-MM-DD'."""
    if not date_val:
        return None
    val_str = str(date_val).strip()
    if not val_str or val_str.lower() in ("none", "null", "nan"):
        return None

    try:
        if "/" in val_str:
            dt = datetime.strptime(val_str, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
        if "-" in val_str:
            dt = datetime.strptime(val_str[:10], "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    try:
        dt = pd.to_datetime(val_str, dayfirst=True)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _to_unix_timestamp(date_val: str | datetime | int | float | None, default_ts: int) -> int:
    """Converts date string ('YYYY-MM-DD' or 'DD/MM/YYYY'), datetime, or timestamp into Unix seconds."""
    if date_val is None:
        return default_ts
    if isinstance(date_val, (int, float)):
        return int(date_val)
    if isinstance(date_val, datetime):
        if date_val.tzinfo is None:
            return int(date_val.replace(tzinfo=timezone.utc).timestamp())
        return int(date_val.timestamp())

    parsed_str = _parse_ssi_date(date_val)
    if not parsed_str:
        raise ValueError(f"Invalid date format: {date_val!r}")
    dt = datetime.strptime(parsed_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


class SSIFetcher:
    """Fetcher for SSI iBoard market data, corporate actions, and OHLCV with Nautilus Trader integration."""

    def __init__(
        self,
        *,
        query_base_url: str = IBOARD_QUERY_BASE_URL,
        api_base_url: str = IBOARD_API_BASE_URL,
        default_venue: str = "HOSE",
        default_currency: str = "VND",
        default_price_precision: int = 2,
        default_size_precision: int = 0,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        catalog_path: str | Path | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.query_base_url = query_base_url.rstrip("/")
        self.api_base_url = api_base_url.rstrip("/")
        self.default_venue = default_venue.strip().upper()
        self.default_currency = default_currency.strip().upper()
        self.default_price_precision = default_price_precision
        self.default_size_precision = default_size_precision
        self.timeout = timeout
        self.catalog_path = Path(catalog_path).expanduser().resolve() if catalog_path else None

        self._session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=RETRY_STATUS_CODES,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update(DEFAULT_HEADERS)
        if headers:
            self._session.headers.update(headers)

        # Internal caches
        self._stocks_info_cache: pd.DataFrame | None = None

    def close(self) -> None:
        """Closes the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> SSIFetcher:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Executes HTTP request and parses JSON payload with robust error handling."""
        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            res = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=effective_timeout,
            )
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request error for %s: %s", url, err)
            raise ConnectionError(f"Connection failed for {url}: {err}") from err

        if not res.ok:
            logger.error("HTTP %d for %s: %s", res.status_code, url, res.text[:200])
            raise RuntimeError(f"SSI API returned status {res.status_code}: {res.text[:200]}")

        try:
            payload = res.json()
        except ValueError as err:
            raise ValueError(f"Invalid JSON returned from {url}: {res.text[:200]}") from err

        if not isinstance(payload, dict):
            raise ValueError(f"Expected dict from {url}, got {type(payload).__name__}")

        return payload

    # -------------------------------------------------------------------------
    # Interval and BarType helpers (Compatible with TradingviewFetcher)
    # -------------------------------------------------------------------------

    @staticmethod
    def _resolve_interval_details(interval: str) -> tuple[str, str, int, BarAggregation, str | None]:
        """Resolves interval string into (norm_interval, ssi_res, step, BarAggregation, resample_rule)."""
        raw = interval.strip()
        if raw in INTERVAL_LOOKUP:
            return INTERVAL_LOOKUP[raw]

        low = raw.lower()
        if low in ("1d", "d", "daily"):
            return INTERVAL_LOOKUP["1d"]
        if low in ("1w", "w", "weekly"):
            return INTERVAL_LOOKUP["1w"]
        if raw in ("1M", "M") or low == "monthly":
            return INTERVAL_LOOKUP["1M"]
        if low in ("1h", "2h", "3h", "4h"):
            return INTERVAL_LOOKUP[low]
        if low == "60":
            return INTERVAL_LOOKUP["1h"]

        if low.isdigit():
            val = f"{low}m"
            if val in INTERVAL_LOOKUP:
                return INTERVAL_LOOKUP[val]

        if low.endswith("min") or (low.endswith("m") and low[:-1].isdigit()):
            digits = "".join(filter(str.isdigit, low))
            val = f"{digits}m"
            if val in INTERVAL_LOOKUP:
                return INTERVAL_LOOKUP[val]

        raise ValueError(
            f"Unsupported interval: '{interval}'. Supported intervals are: "
            f"{list(INTERVAL_LOOKUP.keys())}"
        )

    @classmethod
    def parse_interval(cls, interval: str) -> tuple[str, int, BarAggregation]:
        """Parses an interval string into normalized interval string, step, and BarAggregation.

        Returns
        -------
        tuple[str, int, BarAggregation]
            (normalized_interval, step, bar_aggregation)
        """
        norm_interval, _, step, bar_agg, _ = cls._resolve_interval_details(interval)
        return norm_interval, step, bar_agg

    def get_bar_type(
        self,
        instrument: Instrument | InstrumentId | str,
        interval: str = "1d",
        venue: str | Venue | None = None,
        price_type: PriceType = PriceType.LAST,
        aggregation_source: AggregationSource = AggregationSource.EXTERNAL,
    ) -> BarType:
        """Constructs a standardized Nautilus BarType for the given instrument and interval."""
        if isinstance(instrument, Instrument):
            inst_id = instrument.id
        elif isinstance(instrument, InstrumentId):
            inst_id = instrument
        elif isinstance(instrument, str):
            clean_str = instrument.strip()
            if "." in clean_str:
                inst_id = InstrumentId.from_str(clean_str)
            else:
                venue_obj = venue if isinstance(venue, Venue) else Venue(venue or self.default_venue)
                inst_id = InstrumentId(symbol=Symbol(clean_str.upper()), venue=venue_obj)
        else:
            raise TypeError(f"Unsupported instrument type: {type(instrument)}")

        _, step, bar_aggregation = self.parse_interval(interval)
        spec = BarSpecification(step=step, aggregation=bar_aggregation, price_type=price_type)
        return BarType(
            instrument_id=inst_id,
            bar_spec=spec,
            aggregation_source=aggregation_source,
        )

    # -------------------------------------------------------------------------
    # Listed Companies, Symbol Discovery & Listing Info
    # -------------------------------------------------------------------------

    def get_listed_companies(
        self,
        exchange: str | None = None,
        stock_type_only: bool = True,
        refresh_cache: bool = False,
    ) -> pd.DataFrame:
        """Fetches all listed companies and securities tracked by SSI iBoard."""
        if self._stocks_info_cache is None or refresh_cache:
            url = f"{self.query_base_url}{STOCK_INFO_ENDPOINT}"
            payload = self._request("GET", url)
            records = payload.get("data") or []
            if not isinstance(records, list):
                raise ValueError(f"Expected list in 'data' from stock-info, got {type(records).__name__}")

            rows = []
            for item in records:
                if isinstance(item, dict):
                    rows.append({
                        "symbol": str(item.get("symbol", "")).strip().upper(),
                        "exchange": str(item.get("exchange", "")).strip().upper(),
                        "company_name": item.get("clientName") or item.get("fullName") or item.get("name") or "",
                        "client_name_en": item.get("clientNameEn") or item.get("companyNameEn") or "",
                        "isin": item.get("isin") or None,
                        "type": item.get("type") or "",
                    })

            self._stocks_info_cache = pd.DataFrame(rows)

        df = self._stocks_info_cache.copy()

        if stock_type_only:
            df = df[df["type"] == "s"]

        if exchange:
            exch_clean = exchange.strip().upper()
            df = df[df["exchange"] == exch_clean]

        return df.sort_values(by=["exchange", "symbol"]).reset_index(drop=True)

    def list_symbols(
        self,
        exchange: str | None = None,
        stock_type_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lists symbols matching the filters from SSI iBoard."""
        df = self.get_listed_companies(exchange=exchange, stock_type_only=stock_type_only)
        if limit is not None and limit > 0:
            df = df.head(limit)
        return df.to_dict(orient="records")

    def search_symbol(
        self,
        query: str,
        exchange: str | None = None,
        stock_type_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Searches symbols or company names on SSI iBoard."""
        df = self.get_listed_companies(exchange=exchange, stock_type_only=stock_type_only)
        q = query.strip().lower()
        if q:
            mask = (
                df["symbol"].str.lower().str.contains(q, na=False)
                | df["company_name"].str.lower().str.contains(q, na=False)
                | df["client_name_en"].str.lower().str.contains(q, na=False)
            )
            df = df[mask]
        if limit is not None and limit > 0:
            df = df.head(limit)
        return df.to_dict(orient="records")

    def get_listing_info(
        self,
        symbol: str,
        language: str = "vn",
    ) -> CompanyListingInfo:
        """Fetches comprehensive company profile and listing metadata for a given symbol."""
        clean_sym = symbol.strip().upper()
        url = f"{self.api_base_url}{COMPANY_PROFILE_ENDPOINT}"
        params = {"symbol": clean_sym, "language": language}
        payload = self._request("GET", url, params=params)

        record = payload.get("data")
        if not isinstance(record, dict):
            raise ValueError(f"Missing or invalid 'data' object in company profile for {clean_sym}")

        isin = record.get("isin")
        if not isin:
            try:
                stocks = self.get_listed_companies()
                matched = stocks[stocks["symbol"] == clean_sym]
                if not matched.empty and matched.iloc[0]["isin"]:
                    isin = matched.iloc[0]["isin"]
            except Exception:
                pass

        listing_date = _parse_ssi_date(record.get("listingDate"))
        founding_date = _parse_ssi_date(record.get("foundingDate"))

        def _to_float(val: Any) -> float | None:
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        issue_shares = _to_float(record.get("issueShare"))
        circulating_shares = _to_float(record.get("quantity"))
        charter_capital = _to_float(record.get("charterCapital"))
        first_price = _to_float(record.get("firstPrice"))
        free_float = _to_float(record.get("freeFloatRate"))

        exchange = str(record.get("exchange") or "").strip().upper()
        if not exchange:
            try:
                stocks = self.get_listed_companies()
                matched = stocks[stocks["symbol"] == clean_sym]
                if not matched.empty:
                    exchange = matched.iloc[0]["exchange"]
            except Exception:
                exchange = self.default_venue

        company_name = record.get("companyName") or clean_sym

        return CompanyListingInfo(
            symbol=clean_sym,
            exchange=exchange,
            company_name=company_name,
            client_name_en=None,
            isin=isin,
            listing_date=listing_date,
            founding_date=founding_date,
            issue_shares=issue_shares,
            circulating_shares=circulating_shares,
            charter_capital=charter_capital,
            first_price=first_price,
            free_float_rate=free_float,
            industry_name=record.get("industryName"),
            sector=record.get("sector"),
            sub_sector=record.get("subSector"),
            website=record.get("website"),
            raw_data=record,
        )

    def _resolve_symbol_exchange(self, symbol: str, exchange: str | None = None) -> str:
        """Resolves exchange for a symbol using cache or defaults."""
        if exchange:
            return exchange.strip().upper()
        clean_sym = symbol.strip().upper()
        try:
            stocks = self.get_listed_companies(stock_type_only=False)
            matched = stocks[stocks["symbol"] == clean_sym]
            if not matched.empty and matched.iloc[0]["exchange"]:
                return str(matched.iloc[0]["exchange"]).strip().upper()
        except Exception:
            pass
        return self.default_venue

    # -------------------------------------------------------------------------
    # Instrument Creation (Enriched SSI + Fallback Compatibility)
    # -------------------------------------------------------------------------

    def create_equity(
        self,
        symbol: str,
        venue: str | Venue | None = None,
        listing_info: CompanyListingInfo | None = None,
        current_price: float | None = None,
        *,
        currency: str | Currency | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        price_increment: float | Price | None = None,
        lot_size: float | Quantity = 100.0,
        max_quantity: float | Quantity | None = None,
        min_quantity: float | Quantity | None = None,
        ts_event: int | None = None,
        ts_init: int | None = None,
        fetch_profile: bool = True,
    ) -> Equity:
        """Creates a standardized Nautilus Trader Equity instrument with enriched SSI listing metadata."""
        clean_sym = symbol.strip().upper()
        venue_str = venue.value if isinstance(venue, Venue) else (venue.strip().upper() if venue else None)
        p_prec = self.default_price_precision if price_precision is None else price_precision
        s_prec = self.default_size_precision if size_precision is None else size_precision
        lot_val = float(lot_size.as_double()) if isinstance(lot_size, Quantity) else float(lot_size)

        info = listing_info
        if info is None and fetch_profile:
            try:
                info = self.get_listing_info(clean_sym)
            except Exception as err:
                logger.debug("Falling back to basic Equity creation for %s: %s", clean_sym, err)

        if info is not None:
            if venue_str:
                info.exchange = venue_str
            return info.to_equity(
                current_price=current_price,
                price_precision=p_prec,
                size_precision=s_prec,
                lot_size=lot_val,
            )

        # Fallback direct construction if profile is skipped or unavailable
        resolved_venue = Venue(venue_str or self._resolve_symbol_exchange(clean_sym))
        curr_obj = currency if isinstance(currency, Currency) else Currency.from_str(currency or self.default_currency)
        tick_val = calculate_price_increment(current_price, resolved_venue.value)
        price_inc = (
            price_increment
            if isinstance(price_increment, Price)
            else Price(price_increment if price_increment is not None else tick_val, precision=p_prec)
        )
        lot_q = lot_size if isinstance(lot_size, Quantity) else Quantity(lot_val, precision=s_prec)
        max_q = (
            max_quantity
            if isinstance(max_quantity, Quantity)
            else Quantity(max_quantity if max_quantity is not None else 1e9, precision=s_prec)
        )
        min_q = (
            min_quantity
            if isinstance(min_quantity, Quantity)
            else Quantity(min_quantity if min_quantity is not None else 1.0, precision=s_prec)
        )

        return Equity(
            instrument_id=InstrumentId(symbol=Symbol(clean_sym), venue=resolved_venue),
            raw_symbol=Symbol(clean_sym),
            currency=curr_obj,
            price_precision=p_prec,
            price_increment=price_inc,
            lot_size=lot_q,
            max_quantity=max_q,
            min_quantity=min_q,
            ts_event=int(ts_event or 0),
            ts_init=int(ts_init or 0),
        )

    def create_equities_batch(
        self,
        symbols: Sequence[str],
        venue: str | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
    ) -> dict[str, Equity]:
        """Creates standardized Nautilus Trader Equity instruments in batch."""
        result: dict[str, Equity] = {}
        for sym in symbols:
            try:
                eq = self.create_equity(
                    symbol=sym,
                    venue=venue,
                    price_precision=price_precision,
                    size_precision=size_precision,
                )
                result[eq.symbol.value] = eq
            except Exception as e:
                logger.warning("Failed to create equity for %s: %s", sym, e)
        return result

    def create_currency_pair(
        self,
        symbol: str,
        venue: str | Venue | None = None,
        *,
        base: str | Currency = "USD",
        quote: str | Currency = "VND",
        price_precision: int = 2,
        size_precision: int = 2,
        price_increment: float | Price = 1.0,
        size_increment: float | Quantity = 1.0,
        lot_size: float | Quantity = 1.0,
        max_quantity: float | Quantity | None = 1e9,
        min_quantity: float | Quantity | None = 1.0,
        max_price: float | Price | None = 1e9,
        min_price: float | Price | None = 0.01,
        ts_event: int = 0,
        ts_init: int = 0,
    ) -> CurrencyPair:
        """Creates a standardized Nautilus CurrencyPair instrument for FX or crypto."""
        venue_obj = venue if isinstance(venue, Venue) else Venue(venue or "SIM")
        clean_symbol = symbol.strip().upper()

        if "/" in clean_symbol:
            b_str, q_str = clean_symbol.split("/", 1)
            base_obj = Currency.from_str(b_str)
            quote_obj = Currency.from_str(q_str)
            raw_sym = clean_symbol.replace("/", "")
            formatted_sym = clean_symbol
        else:
            base_obj = base if isinstance(base, Currency) else Currency.from_str(base)
            quote_obj = quote if isinstance(quote, Currency) else Currency.from_str(quote)
            raw_sym = clean_symbol
            formatted_sym = f"{base_obj.code}/{quote_obj.code}"

        price_inc = (
            price_increment
            if isinstance(price_increment, Price)
            else Price(price_increment, precision=price_precision)
        )
        size_inc = (
            size_increment
            if isinstance(size_increment, Quantity)
            else Quantity(size_increment, precision=size_precision)
        )
        lot = lot_size if isinstance(lot_size, Quantity) else Quantity(lot_size, precision=size_precision)
        max_q = (
            max_quantity
            if isinstance(max_quantity, Quantity) or max_quantity is None
            else Quantity(max_quantity, precision=size_precision)
        )
        min_q = (
            min_quantity
            if isinstance(min_quantity, Quantity) or min_quantity is None
            else Quantity(min_quantity, precision=size_precision)
        )
        max_p = (
            max_price
            if isinstance(max_price, Price) or max_price is None
            else Price(max_price, precision=price_precision)
        )
        min_p = (
            min_price
            if isinstance(min_price, Price) or min_price is None
            else Price(min_price, precision=price_precision)
        )

        inst_id = InstrumentId(symbol=Symbol(formatted_sym), venue=venue_obj)

        return CurrencyPair(
            instrument_id=inst_id,
            raw_symbol=Symbol(raw_sym),
            base_currency=base_obj,
            quote_currency=quote_obj,
            price_precision=price_precision,
            size_precision=size_precision,
            price_increment=price_inc,
            size_increment=size_inc,
            lot_size=lot,
            max_quantity=max_q,
            min_quantity=min_q,
            max_price=max_p,
            min_price=min_p,
            ts_event=int(ts_event),
            ts_init=int(ts_init),
        )

    def create_instrument(
        self,
        symbol: str,
        venue_str: str | None = None,
        *,
        instrument_type: str = "equity",
        base: str = "VND",
        price_increment: float = 100.0,
        size_increment: float = 1.0,
        lot_size: float = 100.0,
        max_quantity: float = 1e9,
        min_quantity: float = 1.0,
        max_price: float = 1e9,
        min_price: float = 0.01,
        ts_event: int | float = 0,
        ts_init: int | float = 0,
    ) -> Instrument:
        """Creates a standardized Nautilus instrument (Equity or CurrencyPair)."""
        inst_type_lower = instrument_type.strip().lower()
        if inst_type_lower in ("currencypair", "currency_pair") or "/" in symbol:
            return self.create_currency_pair(
                symbol=symbol,
                venue=venue_str,
                base=base,
                quote="VND",
                price_increment=price_increment,
                size_increment=size_increment,
                lot_size=lot_size,
                max_quantity=max_quantity,
                min_quantity=min_quantity,
                max_price=max_price,
                min_price=min_price,
                ts_event=int(ts_event),
                ts_init=int(ts_init),
            )

        return self.create_equity(
            symbol=symbol,
            venue=venue_str or self.default_venue,
            currency=base,
            price_increment=price_increment,
            lot_size=lot_size,
            max_quantity=max_quantity,
            min_quantity=min_quantity,
            ts_event=int(ts_event),
            ts_init=int(ts_init),
        )

    # -------------------------------------------------------------------------
    # DataFrame Cleaning, Transformation & Vectorized Bar Conversion
    # -------------------------------------------------------------------------

    @staticmethod
    def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Sanitizes raw OHLCV DataFrame.

        Standardizes columns, cleans timestamps to UTC DatetimeIndex, drops nulls/invalids,
        removes duplicate timestamps, and enforces OHLC price boundary invariants.
        """
        if df.empty:
            empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            empty_df.index = pd.DatetimeIndex([], name="datetime", tz="UTC")
            return empty_df

        cleaned = df.copy()
        cleaned.columns = [str(c).strip().lower() for c in cleaned.columns]

        if isinstance(cleaned.index, pd.DatetimeIndex) or cleaned.index.name in ("datetime", "timestamp"):
            if "datetime" not in cleaned.columns and "timestamp" not in cleaned.columns:
                cleaned = cleaned.reset_index(names=["datetime"])
            else:
                cleaned = cleaned.reset_index(drop=True)

        if "datetime" in cleaned.columns:
            dt_series = pd.to_datetime(cleaned["datetime"], utc=True)
        elif "timestamp" in cleaned.columns:
            dt_series = pd.to_datetime(cleaned["timestamp"], utc=True)
        else:
            raise ValueError("DataFrame must contain 'datetime' column or DatetimeIndex")

        cleaned["datetime"] = dt_series

        required_cols = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in cleaned.columns]
        if missing:
            raise ValueError(f"DataFrame missing required OHLCV columns: {missing}")

        for col in required_cols:
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")

        cleaned = cleaned.dropna(subset=["datetime"] + required_cols)
        if cleaned.empty:
            empty_df = pd.DataFrame(columns=required_cols)
            empty_df.index = pd.DatetimeIndex([], name="datetime", tz="UTC")
            return empty_df

        cleaned = cleaned.sort_values(by="datetime", ascending=True)
        cleaned = cleaned.drop_duplicates(subset=["datetime"], keep="last")

        o = cleaned["open"].to_numpy(dtype=np.float64)
        h = cleaned["high"].to_numpy(dtype=np.float64)
        l = cleaned["low"].to_numpy(dtype=np.float64)
        c = cleaned["close"].to_numpy(dtype=np.float64)

        cleaned["high"] = np.maximum(h, np.maximum(o, c))
        cleaned["low"] = np.minimum(l, np.minimum(o, c))

        cleaned = cleaned.set_index("datetime")
        return cleaned[required_cols]

    def df_to_bars(
        self,
        df: pd.DataFrame,
        bar_type: BarType | str,
        price_precision: int | None = None,
        size_precision: int | None = None,
        ts_init_delta: int = 0,
    ) -> list[Bar]:
        """Converts an OHLCV DataFrame to a list of Nautilus Bar objects using vectorized Cython arrays."""
        resolved_bar_type = BarType.from_str(bar_type) if isinstance(bar_type, str) else bar_type

        cleaned = self.clean_dataframe(df)
        if cleaned.empty:
            return []

        p_prec = self.default_price_precision if price_precision is None else price_precision
        s_prec = self.default_size_precision if size_precision is None else size_precision

        ts_events = np.ascontiguousarray(to_nanoseconds_array(cleaned.index)).copy()
        ts_inits = ts_events + np.uint64(ts_init_delta)

        opens = np.ascontiguousarray(cleaned["open"].to_numpy(dtype=np.float64)).copy()
        highs = np.ascontiguousarray(cleaned["high"].to_numpy(dtype=np.float64)).copy()
        lows = np.ascontiguousarray(cleaned["low"].to_numpy(dtype=np.float64)).copy()
        closes = np.ascontiguousarray(cleaned["close"].to_numpy(dtype=np.float64)).copy()
        volumes = np.ascontiguousarray(cleaned["volume"].to_numpy(dtype=np.float64)).copy()

        return Bar.from_raw_arrays_to_list(
            resolved_bar_type,
            p_prec,
            s_prec,
            opens,
            highs,
            lows,
            closes,
            volumes,
            ts_events,
            ts_inits,
        )

    # -------------------------------------------------------------------------
    # OHLCV Market Data Fetching (Full History & Multi-Resolution)
    # -------------------------------------------------------------------------

    def fetch_df(
        self,
        symbol: str,
        exchange: str | None = None,
        interval: str = "1d",
        start_date: str | datetime | int | None = None,
        end_date: str | datetime | int | None = None,
        scale_to_vnd: bool = True,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetches full historical OHLCV data from SSI iBoard Charts API as a sanitized DataFrame.

        Parameters
        ----------
        symbol : str
            Ticker symbol (e.g. 'HPG', 'VCB', 'VNINDEX').
        exchange : str, optional
            Exchange venue ('HOSE', 'HNX', 'UPCOM').
        interval : str, default '1d'
            Timeframe interval ('1m', '3m', '5m', '15m', '30m', '45m', '1h', '2h', '3h', '4h', '1d', '1w', '1M').
        start_date : str | datetime | int, optional
            Start date. If None, fetches full history from 2000-01-01 (VN_MARKET_GENESIS_TS).
        end_date : str | datetime | int, optional
            End date. If None, fetches up to current timestamp.
        scale_to_vnd : bool, default True
            Multiplies equity prices by 1,000 to convert SSI's 1,000 VND chart unit into standard VND.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by UTC 'datetime' with columns: ['open', 'high', 'low', 'close', 'volume'].
        """
        sym = symbol.strip().upper()
        exch = self._resolve_symbol_exchange(sym, exchange)
        norm_interval, ssi_res, _, _, resample_rule = self._resolve_interval_details(interval)

        from_ts = _to_unix_timestamp(start_date, default_ts=VN_MARKET_GENESIS_TS)
        to_ts = _to_unix_timestamp(end_date, default_ts=int(time.time()) + 86400)

        url = f"{self.api_base_url}{CHARTS_HISTORY_ENDPOINT}"
        params = {
            "resolution": ssi_res,
            "symbol": sym,
            "from": from_ts,
            "to": to_ts,
        }

        payload = self._request("GET", url, params=params)
        data = payload.get("data", payload)

        if not isinstance(data, dict) or data.get("s") != "ok" or not data.get("t"):
            empty = self.clean_dataframe(pd.DataFrame())
            empty.attrs["symbol"] = sym
            empty.attrs["exchange"] = exch
            empty.attrs["interval"] = norm_interval
            return empty

        raw_df = pd.DataFrame({
            "datetime": pd.to_datetime(data["t"], unit="s", utc=True),
            "open": pd.to_numeric(data.get("o", []), errors="coerce"),
            "high": pd.to_numeric(data.get("h", []), errors="coerce"),
            "low": pd.to_numeric(data.get("l", []), errors="coerce"),
            "close": pd.to_numeric(data.get("c", []), errors="coerce"),
            "volume": pd.to_numeric(data.get("v", []), errors="coerce"),
        })

        # Scale equity prices from 1,000 VND to VND (skip market indices and derivatives)
        is_index_or_deriv = sym in MARKET_INDICES or (sym.startswith("VN30F") and len(sym) >= 7)
        if scale_to_vnd and not is_index_or_deriv and not raw_df.empty:
            for col in ("open", "high", "low", "close"):
                raw_df[col] = (raw_df[col] * 1000.0).round(2)

        cleaned = self.clean_dataframe(raw_df)

        # Resample if interval is a composite timeframe (e.g. 3m, 45m, 2h, 3h, 4h)
        if resample_rule and not cleaned.empty:
            cleaned = (
                cleaned.resample(resample_rule)
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna(subset=["open", "high", "low", "close"])
            )
            cleaned = self.clean_dataframe(cleaned)

        cleaned.attrs["symbol"] = sym
        cleaned.attrs["exchange"] = exch
        cleaned.attrs["interval"] = norm_interval
        return cleaned

    # Alias for convenience
    get_ohlcv = fetch_df

    def fetch_batch_df(
        self,
        tickers: Sequence[dict[str, str] | tuple[str, str] | str] | None = None,
        exchange: str | None = None,
        interval: str = "1d",
        start_date: str | datetime | int | None = None,
        end_date: str | datetime | int | None = None,
        scale_to_vnd: bool = True,
        delay_seconds: float = 0.1,
        **kwargs: Any,
    ) -> dict[str, pd.DataFrame]:
        """Fetches historical OHLCV market data in batch for multiple tickers (or entire exchange if tickers=None)."""
        default_exch = (exchange or self.default_venue).strip().upper()

        norm_tickers: list[dict[str, str]] = []
        if tickers is None:
            listed_df = self.get_listed_companies(exchange=exchange, stock_type_only=True)
            for row in listed_df.itertuples(index=False):
                norm_tickers.append({"exchange": row.exchange, "symbol": row.symbol})
        else:
            for item in tickers:
                if isinstance(item, dict):
                    sym_str = item["symbol"].strip().upper()
                    ex_str = item.get("exchange") or self._resolve_symbol_exchange(sym_str, default_exch)
                    norm_tickers.append({"exchange": ex_str.strip().upper(), "symbol": sym_str})
                elif isinstance(item, tuple):
                    sym_str, ex_str = item
                    norm_tickers.append({"exchange": ex_str.strip().upper(), "symbol": sym_str.strip().upper()})
                elif isinstance(item, str):
                    sym_str = item.strip().upper()
                    ex_str = self._resolve_symbol_exchange(sym_str, exchange)
                    norm_tickers.append({"exchange": ex_str, "symbol": sym_str})
                else:
                    raise TypeError(f"Unsupported ticker item type: {type(item)}")

        results: dict[str, pd.DataFrame] = {}
        total = len(norm_tickers)

        for idx, item in enumerate(norm_tickers, start=1):
            sym = item["symbol"]
            exch = item["exchange"]
            try:
                df = self.fetch_df(
                    symbol=sym,
                    exchange=exch,
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date,
                    scale_to_vnd=scale_to_vnd,
                )
                results[sym] = df
            except Exception as err:
                logger.warning("[%d/%d] Failed to fetch OHLCV for %s/%s: %s", idx, total, sym, exch, err)

            if delay_seconds > 0 and idx < total:
                time.sleep(delay_seconds)

        return results

    def fetch_all_ohlcv(
        self,
        symbols: Sequence[str] | None = None,
        exchange: str | None = None,
        interval: str = "1d",
        start_date: str | datetime | int | None = None,
        end_date: str | datetime | int | None = None,
        scale_to_vnd: bool = True,
        delay_seconds: float = 0.1,
    ) -> pd.DataFrame:
        """Fetches full historical OHLCV across all requested symbols (or entire exchange) as a single combined DataFrame."""
        batch_dfs = self.fetch_batch_df(
            tickers=symbols,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            scale_to_vnd=scale_to_vnd,
            delay_seconds=delay_seconds,
        )

        frames: list[pd.DataFrame] = []
        for sym, df in batch_dfs.items():
            if not df.empty:
                frame = df.reset_index()
                frame.insert(1, "symbol", sym)
                frame.insert(2, "exchange", df.attrs.get("exchange", exchange or self.default_venue))
                frames.append(frame)

        if not frames:
            return pd.DataFrame(columns=["datetime", "symbol", "exchange", "open", "high", "low", "close", "volume"])

        return pd.concat(frames, ignore_index=True)

    def fetch_bars(
        self,
        symbol: str,
        exchange: str | None = None,
        interval: str = "1d",
        instrument: Instrument | None = None,
        bar_type: BarType | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        start_date: str | datetime | int | None = None,
        end_date: str | datetime | int | None = None,
        scale_to_vnd: bool = True,
        **kwargs: Any,
    ) -> list[Bar]:
        """Fetches market data from SSI and converts directly to Nautilus Bar objects."""
        sym = symbol.strip().upper()
        exch = self._resolve_symbol_exchange(sym, exchange)

        if bar_type is None:
            inst = instrument or self.create_equity(symbol=sym, venue=exch, fetch_profile=False)
            bar_type = self.get_bar_type(instrument=inst, interval=interval, venue=exch)

        df = self.fetch_df(
            symbol=sym,
            exchange=exch,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            scale_to_vnd=scale_to_vnd,
        )

        p_prec = (
            price_precision
            if price_precision is not None
            else (instrument.price_precision if instrument else self.default_price_precision)
        )
        s_prec = (
            size_precision
            if size_precision is not None
            else (instrument.size_precision if instrument else self.default_size_precision)
        )

        return self.df_to_bars(
            df=df,
            bar_type=bar_type,
            price_precision=p_prec,
            size_precision=s_prec,
        )

    # Alias for convenience
    get_ohlcv_bars = fetch_bars

    def fetch_bars_batch(
        self,
        tickers: Sequence[dict[str, str] | tuple[str, str] | str] | None = None,
        exchange: str | None = None,
        interval: str = "1d",
        price_precision: int | None = None,
        size_precision: int | None = None,
        start_date: str | datetime | int | None = None,
        end_date: str | datetime | int | None = None,
        scale_to_vnd: bool = True,
        delay_seconds: float = 0.1,
        **kwargs: Any,
    ) -> dict[str, list[Bar]]:
        """Fetches batch market data from SSI and converts each to a list of Nautilus Bar objects."""
        dfs = self.fetch_batch_df(
            tickers=tickers,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            scale_to_vnd=scale_to_vnd,
            delay_seconds=delay_seconds,
        )

        bars_by_symbol: dict[str, list[Bar]] = {}
        for sym, df in dfs.items():
            exch = df.attrs.get("exchange", exchange or self.default_venue)
            inst = self.create_equity(symbol=sym, venue=exch, fetch_profile=False)
            btype = self.get_bar_type(instrument=inst, interval=interval, venue=exch)
            bars_by_symbol[sym] = self.df_to_bars(
                df=df,
                bar_type=btype,
                price_precision=price_precision,
                size_precision=size_precision,
            )

        return bars_by_symbol

    # -------------------------------------------------------------------------
    # Corporate Actions & Dividends
    # -------------------------------------------------------------------------

    def get_corporate_actions(
        self,
        symbol: str,
        dividend_only: bool = False,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetches corporate actions (cổ tức, chia tách, quyền mua, đại hội, ...) for a stock symbol."""
        clean_sym = symbol.strip().upper()
        url = f"{self.api_base_url}{CORPORATE_ACTIONS_ENDPOINT}"
        params = {"symbol": clean_sym, "page": page, "pageSize": page_size}
        payload = self._request("GET", url, params=params)

        records = payload.get("data") or []
        if not isinstance(records, list):
            return []

        if not dividend_only:
            return records

        div_events = []
        for a in records:
            if not isinstance(a, dict):
                continue
            name = str(a.get("eventName") or "").lower()
            code = str(a.get("eventListCode") or "").upper()
            title = str(a.get("eventTitle") or "").lower()
            if code == "DIV" or "cổ tức" in name or "cổ tức" in title:
                div_events.append(a)

        return div_events

    def get_cap_and_dividend(self, symbol: str) -> pd.DataFrame:
        """Fetches historical annual capital, assets, and dividend distribution series for a symbol."""
        clean_sym = symbol.strip().upper()
        url = f"{self.api_base_url}{CAP_AND_DIVIDEND_ENDPOINT}"
        params = {"symbol": clean_sym}
        payload = self._request("GET", url, params=params)

        data = payload.get("data")
        if not isinstance(data, dict):
            return pd.DataFrame(columns=["year", "cash_dividend", "asset", "owner_capital"])

        result: pd.DataFrame | None = None
        for name, records in data.items():
            if not isinstance(records, list) or not records:
                continue
            frame = pd.DataFrame(records)
            if "year" not in frame.columns:
                continue

            target_col = name.removesuffix("List")
            val_cols = [col for col in frame.columns if col != "year"]
            if val_cols:
                frame = frame.rename(columns={val_cols[0]: target_col})[["year", target_col]]
            frame[target_col] = pd.to_numeric(frame[target_col], errors="coerce")

            if result is None:
                result = frame
            else:
                result = pd.merge(result, frame, on="year", how="outer")

        if result is None:
            return pd.DataFrame(columns=["year", "cash_dividend", "asset", "owner_capital"])

        rename_map = {
            "cashDividend": "cash_dividend",
            "ownerCapital": "owner_capital",
        }
        result = result.rename(columns=rename_map)

        result["year"] = pd.to_numeric(result["year"], errors="coerce")
        result = result.dropna(subset=["year"])
        result["year"] = result["year"].astype(int)
        return result.sort_values("year", ascending=False).reset_index(drop=True)

    def get_cash_dividends(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> list[Dividend]:
        """Fetches complete cash dividend distribution history formatted for Nautilus Trader backtesting."""
        clean_sym = symbol.strip().upper()
        exch = self._resolve_symbol_exchange(clean_sym, exchange)
        inst_id = InstrumentId(Symbol(clean_sym), Venue(exch))

        dividends: list[Dividend] = []
        covered_years: set[int] = set()

        # 1. Detailed corporate actions from SSI
        try:
            corp_actions = self.get_corporate_actions(clean_sym, dividend_only=True)
            for a in corp_actions:
                name = str(a.get("eventName") or "").lower()
                title = str(a.get("eventTitle") or "").lower()
                if "tiền" not in name and "tiền" not in title and a.get("eventListCode") != "DIV":
                    continue

                raw_val = a.get("value")
                try:
                    amount = float(raw_val) if raw_val is not None else 0.0
                except (ValueError, TypeError):
                    amount = 0.0

                if amount <= 0:
                    continue

                ex_date = _parse_ssi_date(a.get("exrightDate"))
                rec_date = _parse_ssi_date(a.get("recordDate"))
                pay_date = _parse_ssi_date(a.get("issueDate"))

                ref_date_str = ex_date or rec_date or pay_date or _parse_ssi_date(a.get("publicDate"))
                if not ref_date_str:
                    continue

                ex_date_final = ex_date or ref_date_str
                rec_date_final = rec_date or ex_date_final
                pay_date_final = pay_date or rec_date_final

                fiscal_year = int(ref_date_str[:4])
                covered_years.add(fiscal_year)

                raw_ratio = a.get("ratio")
                try:
                    ratio = float(raw_ratio) if raw_ratio is not None else (amount / 10000.0)
                except (ValueError, TypeError):
                    ratio = amount / 10000.0

                ts_event = datetime_to_nanoseconds(ex_date_final)
                div_obj = Dividend(
                    instrument_id=inst_id,
                    amount=amount,
                    ex_date=ex_date_final,
                    record_date=rec_date_final,
                    payment_date=pay_date_final,
                    fiscal_year=fiscal_year,
                    ratio=ratio,
                    description=a.get("eventTitle") or a.get("eventDescription") or f"{clean_sym} Cash Dividend",
                    ts_event=ts_event,
                    ts_init=ts_event,
                )
                dividends.append(div_obj)
        except Exception as err:
            logger.warning("Failed to fetch corporate actions for %s: %s", clean_sym, err)

        # 2. Historical annual distributions from cap-and-dividend
        try:
            cap_div = self.get_cap_and_dividend(clean_sym)
            if not cap_div.empty and "cash_dividend" in cap_div.columns:
                for _, row in cap_div.iterrows():
                    year_val = row["year"]
                    amount_val = row["cash_dividend"]
                    if pd.isna(year_val) or pd.isna(amount_val):
                        continue

                    yr = int(year_val)
                    amt = float(amount_val)
                    if amt <= 0 or yr in covered_years:
                        continue

                    covered_years.add(yr)
                    date_str = f"{yr}-12-31"
                    ts_event = datetime_to_nanoseconds(date_str)

                    div_obj = Dividend(
                        instrument_id=inst_id,
                        amount=amt,
                        ex_date=date_str,
                        record_date=date_str,
                        payment_date=date_str,
                        fiscal_year=yr,
                        ratio=amt / 10000.0,
                        description=f"{clean_sym} Annual Cash Dividend {yr}",
                        ts_event=ts_event,
                        ts_init=ts_event,
                    )
                    dividends.append(div_obj)
        except Exception as err:
            logger.warning("Failed to fetch cap-and-dividend for %s: %s", clean_sym, err)

        dividends.sort(key=lambda d: d.ts_event)
        return dividends

    def get_cash_dividends_df(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """Fetches historical cash dividends as a pandas DataFrame with UTC DatetimeIndex."""
        clean_sym = symbol.strip().upper()
        divs = self.get_cash_dividends(clean_sym, exchange=exchange)
        if not divs:
            return pd.DataFrame(
                columns=[
                    "instrument_id",
                    "symbol",
                    "amount",
                    "ex_date",
                    "record_date",
                    "payment_date",
                    "fiscal_year",
                    "ratio",
                    "description",
                ]
            )

        records = [
            {
                "datetime": pd.to_datetime(d.ex_date, utc=True),
                "instrument_id": str(d.instrument_id),
                "symbol": clean_sym,
                "amount": d.amount,
                "ex_date": d.ex_date,
                "record_date": d.record_date,
                "payment_date": d.payment_date,
                "fiscal_year": d.fiscal_year,
                "ratio": d.ratio,
                "description": d.description,
            }
            for d in divs
        ]

        df = pd.DataFrame(records)
        df = df.sort_values(by="datetime", ascending=True)
        return df.set_index("datetime")

    def get_sectors_data(self) -> list[dict[str, Any]]:
        """Fetches sector classifications and component company symbols from SSI."""
        url = f"{self.api_base_url}{SECTORS_DATA_ENDPOINT}"
        payload = self._request("GET", url)
        data = payload.get("data") or []
        if isinstance(data, list):
            return data
        return []

    # -------------------------------------------------------------------------
    # Nautilus ParquetDataCatalog Persistence
    # -------------------------------------------------------------------------

    def get_catalog(self, catalog_path: str | Path | None = None) -> ParquetDataCatalog:
        """Returns or creates a Nautilus ParquetDataCatalog instance."""
        target_path = Path(catalog_path).expanduser().resolve() if catalog_path else self.catalog_path
        if target_path is None:
            raise ValueError(
                "Catalog path is required. Provide 'catalog_path' to method or initialize SSIFetcher(catalog_path=...)."
            )
        target_path.mkdir(parents=True, exist_ok=True)
        return ParquetDataCatalog(str(target_path))

    def save_to_catalog(
        self,
        bars: Sequence[Bar] | dict[str, list[Bar]] | None = None,
        instruments: Sequence[Instrument] | Instrument | None = None,
        dividends: Sequence[Dividend] | None = None,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> ParquetDataCatalog:
        """Writes instruments, dividends, and OHLCV bars directly into a Nautilus ParquetDataCatalog."""
        cat = catalog or self.get_catalog(catalog_path)

        if instruments is not None:
            if isinstance(instruments, Instrument):
                cat.write_data([instruments])
            elif len(instruments) > 0:
                cat.write_data(list(instruments))

        if dividends is not None and len(dividends) > 0:
            cat.write_data(list(dividends))

        if bars is not None:
            if isinstance(bars, dict):
                for _, bar_list in bars.items():
                    if bar_list:
                        cat.write_data(bar_list)
            elif len(bars) > 0:
                cat.write_data(list(bars))

        return cat

    def fetch_and_catalog(
        self,
        symbols: str | Sequence[str],
        exchange: str | None = None,
        interval: str = "1d",
        include_bars: bool = True,
        include_dividends: bool = True,
        start_date: str | datetime | int | None = None,
        end_date: str | datetime | int | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
        **kwargs: Any,
    ) -> tuple[list[Equity], list[Dividend], list[Bar]]:
        """End-to-end SSI pipeline: fetches listing info, creates Equities, fetches Dividends & OHLCV Bars, and persists to catalog."""
        symbol_list = [symbols] if isinstance(symbols, str) else list(symbols)
        cat = catalog or self.get_catalog(catalog_path)

        equities: list[Equity] = []
        all_dividends: list[Dividend] = []
        all_bars: list[Bar] = []

        for sym in symbol_list:
            clean = sym.strip().upper()
            try:
                eq = self.create_equity(
                    clean,
                    venue=exchange,
                    price_precision=price_precision,
                    size_precision=size_precision,
                )
                venue_str = eq.venue.value
                equities.append(eq)

                divs: list[Dividend] = []
                if include_dividends:
                    divs = self.get_cash_dividends(clean, exchange=venue_str)
                    all_dividends.extend(divs)

                bars: list[Bar] = []
                if include_bars:
                    bars = self.fetch_bars(
                        symbol=clean,
                        exchange=venue_str,
                        interval=interval,
                        instrument=eq,
                        price_precision=price_precision,
                        size_precision=size_precision,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    all_bars.extend(bars)

                self.save_to_catalog(
                    bars=bars,
                    instruments=[eq],
                    dividends=divs,
                    catalog=cat,
                )
            except Exception as err:
                logger.error("Failed in fetch_and_catalog for %s: %s", clean, err)

        return equities, all_dividends, all_bars