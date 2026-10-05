from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yfinance as yf

from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair, Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.utils.time import to_nanoseconds_array

logger = logging.getLogger(__name__)

# ISO 4217 Fiat Currencies & Precious Metals for Forex detection
FIAT_CURRENCIES: frozenset[str] = frozenset({
    "USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD",
    "CNY", "CNH", "VND", "HKD", "SGD", "THB", "KRW", "INR",
    "MYR", "IDR", "PHP", "TWD", "MXN", "BRL", "ZAR", "TRY",
    "SEK", "NOK", "DKK", "PLN", "HUF", "CZK", "ILS", "AED",
    "SAR", "RUB", "XAU", "XAG",
})

# Supported interval mapping:
# key -> (normalized_interval, yf_base_interval, step, BarAggregation, pandas_resample_rule)
INTERVAL_LOOKUP: dict[str, tuple[str, str, int, BarAggregation, str | None]] = {
    "1m": ("1m", "1m", 1, BarAggregation.MINUTE, None),
    "2m": ("2m", "2m", 2, BarAggregation.MINUTE, None),
    "3m": ("3m", "1m", 3, BarAggregation.MINUTE, "3min"),
    "5m": ("5m", "5m", 5, BarAggregation.MINUTE, None),
    "15m": ("15m", "15m", 15, BarAggregation.MINUTE, None),
    "30m": ("30m", "30m", 30, BarAggregation.MINUTE, None),
    "45m": ("45m", "15m", 45, BarAggregation.MINUTE, "45min"),
    "1h": ("1h", "1h", 1, BarAggregation.HOUR, None),
    "2h": ("2h", "1h", 2, BarAggregation.HOUR, "2h"),
    "3h": ("3h", "1h", 3, BarAggregation.HOUR, "3h"),
    "4h": ("4h", "1h", 4, BarAggregation.HOUR, "4h"),
    "6h": ("6h", "1h", 6, BarAggregation.HOUR, "6h"),
    "8h": ("8h", "1h", 8, BarAggregation.HOUR, "8h"),
    "12h": ("12h", "1h", 12, BarAggregation.HOUR, "12h"),
    "1d": ("1d", "1d", 1, BarAggregation.DAY, None),
    "3d": ("3d", "1d", 3, BarAggregation.DAY, "3D"),
    "1w": ("1w", "1wk", 1, BarAggregation.WEEK, None),
    "1M": ("1M", "1mo", 1, BarAggregation.MONTH, None),
}

# Yahoo Finance intraday lookback limits (in days)
YF_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 29,
    "2m": 59,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "60m": 729,
    "90m": 59,
    "1h": 729,
}

# Default start date for full daily/weekly/monthly Forex history
FX_DEFAULT_START_DATE: str = "1990-01-01"


def parse_utc_timestamp(val: Any) -> pd.Timestamp:
    """Parses any timestamp (nanoseconds, milliseconds, seconds, string, datetime) into a UTC Timestamp."""
    if val is None:
        return pd.Timestamp.now(tz="UTC")
    if isinstance(val, pd.Timestamp):
        return val.tz_localize("UTC") if val.tzinfo is None else val.tz_convert("UTC")
    if isinstance(val, datetime):
        return pd.Timestamp(val).tz_localize("UTC") if val.tzinfo is None else pd.Timestamp(val).tz_convert("UTC")
    if isinstance(val, (int, float)):
        if val > 1e14:  # Nanoseconds (Nautilus Trader format)
            return pd.to_datetime(int(val), unit="ns", utc=True)
        elif val > 1e11:  # Milliseconds (CCXT format)
            return pd.to_datetime(int(val), unit="ms", utc=True)
        else:  # Seconds
            return pd.to_datetime(float(val), unit="s", utc=True)
    return pd.to_datetime(val, utc=True)


def parse_fx_symbol(symbol: str) -> tuple[str, str, str]:
    """Parses a symbol into (base_currency, quote_currency, yahoo_ticker).

    Examples
    --------
    - 'EUR/USD', 'EUR-USD', 'EURUSD', 'EURUSD=X' -> ('EUR', 'USD', 'EURUSD=X')
    - 'USD/VND', 'USDVND', 'VND=X'               -> ('USD', 'VND', 'USDVND=X')
    - 'DXY', 'DX-Y.NYB'                          -> ('DXY', 'USD', 'DX-Y.NYB')
    - 'BTC/USDT', 'BTC-USD'                      -> ('BTC', 'USD', 'BTC-USD')
    """
    s = symbol.strip().upper()
    if "." in s and not s.endswith(".NYB"):
        # Strip Nautilus venue suffix if passed like 'EUR/USD.YAHOO' or 'EURUSD.SIM'
        left, right = s.rsplit(".", 1)
        if right in ("YAHOO", "SIM", "FX", "FOREX", "IDEALPRO"):
            s = left

    # Special macro tickers
    if s in ("DXY", "DX-Y.NYB", "USDX"):
        return "DXY", "USD", "DX-Y.NYB"

    # Already formatted as Yahoo FX ticker (e.g. 'EURUSD=X' or 'VND=X')
    if s.endswith("=X"):
        core = s[:-2]
        if len(core) == 6:
            return core[:3], core[3:], f"{core}=X"
        elif len(core) == 3:
            return "USD", core, f"USD{core}=X"
        return core, "USD", s

    # Separated by '/' or '-'
    if "/" in s or "-" in s:
        sep = "/" if "/" in s else "-"
        base, quote = s.split(sep, 1)
        base, quote = base.strip(), quote.strip()
        if base in FIAT_CURRENCIES and quote in FIAT_CURRENCIES:
            return base, quote, f"{base}{quote}=X"
        if quote in ("USDT", "USD", "BUSD", "USDC"):
            return base, "USD", f"{base}-USD"
        return base, quote, f"{base}-{quote}"

    # 6-character contiguous Forex pair (e.g. 'EURUSD', 'USDVND', 'USDJPY')
    if len(s) == 6 and s[:3] in FIAT_CURRENCIES and s[3:] in FIAT_CURRENCIES:
        return s[:3], s[3:], f"{s}=X"

    # 3-character single fiat currency (e.g. 'VND', 'JPY' -> USD/XXX)
    if len(s) == 3 and s in FIAT_CURRENCIES and s != "USD":
        return "USD", s, f"USD{s}=X"

    # Crypto contiguous fallbacks
    if s.endswith("USDT") and len(s) > 4:
        base = s[:-4]
        return base, "USD", f"{base}-USD"
    if s.endswith("USD") and len(s) > 3:
        base = s[:-3]
        if base in FIAT_CURRENCIES:
            return base, "USD", f"{base}USD=X"
        return base, "USD", f"{base}-USD"

    return s, "USD", s


def to_yahoo_ticker(symbol: str) -> str:
    """Translates a symbol or currency pair into a Yahoo Finance compatible ticker string."""
    _, _, yf_ticker = parse_fx_symbol(symbol)
    return yf_ticker


def to_yahoo_interval(timeframe: str) -> tuple[str, bool]:
    """Translates timeframe string to (yf_interval, needs_resample) for backward compatibility."""
    _, yf_int, _, _, resample_rule = YahooFinanceFetcher._resolve_interval_details(timeframe)
    return yf_int, (resample_rule is not None)


def infer_fx_precision(quote_currency: str) -> tuple[int, float]:
    """Infers standard Forex price_precision and price_increment (pip/tick size) from quote currency."""
    q = quote_currency.strip().upper()
    if q in ("VND", "IDR", "KRW", "CLP", "HUF"):
        return 2, 0.01
    if q in ("JPY", "XAG"):
        return 3, 0.001
    if q in ("XAU",):
        return 2, 0.01
    # Standard 5-decimal pip pricing for major/minor FX pairs (EUR/USD, GBP/USD, USD/CNY, etc.)
    return 5, 0.00001


class YahooFinanceFetcher:
    """Fetcher for Yahoo Finance Forex & macro market data with Nautilus Trader integration."""

    def __init__(
        self,
        *,
        default_venue: str = "YAHOO",
        default_price_precision: int | None = None,
        default_size_precision: int = 2,
        catalog_path: str | Path | None = None,
        raw_dir: str | Path = "data/raw",
    ) -> None:
        """Initializes YahooFinanceFetcher with Nautilus Trader catalog and raw cache settings.

        Parameters
        ----------
        default_venue : str, default 'YAHOO'
            Default venue identifier for Nautilus Trader instruments.
        default_price_precision : int, optional
            Default price precision. If None, inferred automatically per FX quote currency.
        default_size_precision : int, default 2
            Default quantity/volume precision.
        catalog_path : str | Path, optional
            Root path for Nautilus Trader ParquetDataCatalog.
        raw_dir : str | Path, default 'data/raw'
            Directory for raw Parquet snapshots (backward compatibility).
        """
        self.default_venue = default_venue.strip().upper()
        self.default_price_precision = default_price_precision
        self.default_size_precision = default_size_precision
        self.catalog_path = Path(catalog_path).expanduser().resolve() if catalog_path else None
        self.raw_dir = Path(raw_dir).expanduser().resolve()

    def close(self) -> None:
        """No-op session close for interface compatibility with SSIFetcher."""
        pass

    def __enter__(self) -> YahooFinanceFetcher:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Interval and BarType Helpers (Synchronized with SSIFetcher)
    # -------------------------------------------------------------------------

    @staticmethod
    def _resolve_interval_details(interval: str) -> tuple[str, str, int, BarAggregation, str | None]:
        """Resolves interval string into (norm_interval, yf_interval, step, BarAggregation, resample_rule)."""
        raw = interval.strip()
        if raw in INTERVAL_LOOKUP:
            return INTERVAL_LOOKUP[raw]

        low = raw.lower()
        if low in ("1d", "d", "daily"):
            return INTERVAL_LOOKUP["1d"]
        if low in ("1w", "1wk", "w", "weekly"):
            return INTERVAL_LOOKUP["1w"]
        if raw in ("1M", "M") or low in ("1mo", "month", "monthly"):
            return INTERVAL_LOOKUP["1M"]
        if low in ("1h", "60m", "60"):
            return INTERVAL_LOOKUP["1h"]
        if low in INTERVAL_LOOKUP:
            return INTERVAL_LOOKUP[low]

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
        """Parses an interval string into (normalized_interval, step, BarAggregation)."""
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
        """Constructs a standardized Nautilus BarType for the given FX instrument and interval."""
        if isinstance(instrument, Instrument):
            inst_id = instrument.id
        elif isinstance(instrument, InstrumentId):
            inst_id = instrument
        elif isinstance(instrument, str):
            venue_str = venue.value if isinstance(venue, Venue) else (venue or self.default_venue)
            inst = self.create_currency_pair(instrument, venue=venue_str)
            inst_id = inst.id
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
    # Instrument Creation (Forex CurrencyPair)
    # -------------------------------------------------------------------------

    def create_currency_pair(
        self,
        symbol: str,
        venue: str | Venue | None = None,
        *,
        base: str | Currency | None = None,
        quote: str | Currency | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        price_increment: float | Price | None = None,
        size_increment: float | Quantity | None = None,
        lot_size: float | Quantity | None = None,
        max_quantity: float | Quantity | None = 1e9,
        min_quantity: float | Quantity | None = 0.01,
        max_price: float | Price | None = 1e9,
        min_price: float | Price | None = 0.00001,
        ts_event: int = 0,
        ts_init: int = 0,
    ) -> CurrencyPair:
        """Creates a standardized Nautilus CurrencyPair instrument with smart Forex precision defaults."""
        parsed_base, parsed_quote, yf_ticker = parse_fx_symbol(symbol)

        base_obj = (
            base
            if isinstance(base, Currency)
            else Currency.from_str(base.strip().upper() if base else parsed_base)
        )
        quote_obj = (
            quote
            if isinstance(quote, Currency)
            else Currency.from_str(quote.strip().upper() if quote else parsed_quote)
        )
        venue_obj = venue if isinstance(venue, Venue) else Venue((venue or self.default_venue).strip().upper())

        inferred_p_prec, inferred_p_inc = infer_fx_precision(quote_obj.code)
        p_prec = (
            price_precision
            if price_precision is not None
            else (self.default_price_precision if self.default_price_precision is not None else inferred_p_prec)
        )
        s_prec = size_precision if size_precision is not None else self.default_size_precision

        p_inc_val = price_increment if price_increment is not None else round(10 ** (-p_prec), p_prec)
        s_inc_val = size_increment if size_increment is not None else round(10 ** (-s_prec), s_prec)
        lot_val = lot_size if lot_size is not None else 1.0

        price_inc = p_inc_val if isinstance(p_inc_val, Price) else Price(float(p_inc_val), precision=p_prec)
        size_inc = s_inc_val if isinstance(s_inc_val, Quantity) else Quantity(float(s_inc_val), precision=s_prec)
        lot_q = lot_val if isinstance(lot_val, Quantity) else Quantity(float(lot_val), precision=s_prec)

        max_q = (
            max_quantity
            if isinstance(max_quantity, Quantity) or max_quantity is None
            else Quantity(float(max_quantity), precision=s_prec)
        )
        min_q = (
            min_quantity
            if isinstance(min_quantity, Quantity) or min_quantity is None
            else Quantity(max(float(min_quantity), float(s_inc_val)), precision=s_prec)
        )
        max_p = (
            max_price
            if isinstance(max_price, Price) or max_price is None
            else Price(float(max_price), precision=p_prec)
        )
        min_p = (
            min_price
            if isinstance(min_price, Price) or min_price is None
            else Price(max(float(min_price), float(p_inc_val)), precision=p_prec)
        )

        # Standardize symbol as 'BASE/QUOTE' (e.g. 'EUR/USD.YAHOO', 'USD/VND.YAHOO')
        pair_symbol = f"{base_obj.code}/{quote_obj.code}"
        raw_sym = f"{base_obj.code}{quote_obj.code}"
        inst_id = InstrumentId(symbol=Symbol(pair_symbol), venue=venue_obj)

        return CurrencyPair(
            instrument_id=inst_id,
            raw_symbol=Symbol(raw_sym),
            base_currency=base_obj,
            quote_currency=quote_obj,
            price_precision=p_prec,
            size_precision=s_prec,
            price_increment=price_inc,
            size_increment=size_inc,
            lot_size=lot_q,
            max_quantity=max_q,
            min_quantity=min_q,
            max_price=max_p,
            min_price=min_p,
            ts_event=int(ts_event),
            ts_init=int(ts_init),
            info={"yahoo_ticker": yf_ticker, "base": base_obj.code, "quote": quote_obj.code},
        )

    def create_instrument(
        self,
        symbol: str,
        venue_str: str | None = None,
        **kwargs: Any,
    ) -> CurrencyPair:
        """Creates a standardized Nautilus CurrencyPair instrument (alias for backward compatibility)."""
        return self.create_currency_pair(symbol=symbol, venue=venue_str, **kwargs)

    # -------------------------------------------------------------------------
    # DataFrame Cleaning & Vectorized Nautilus Bar Conversion
    # -------------------------------------------------------------------------

    @staticmethod
    def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Sanitizes raw OHLCV DataFrame from Yahoo Finance.

        Standardizes columns, normalizes index to UTC DatetimeIndex named 'datetime',
        fills missing FX volume with 0.0, removes duplicate timestamps, and enforces
        OHLC boundary invariants (high >= max(open, close), low <= min(open, close)).
        """
        required_cols = ["open", "high", "low", "close", "volume"]
        if df is None or df.empty:
            empty_df = pd.DataFrame(columns=required_cols)
            empty_df.index = pd.DatetimeIndex([], name="datetime", tz="UTC")
            return empty_df

        cleaned = df.copy()
        # Handle MultiIndex columns if yfinance returns ticker-level columns
        if isinstance(cleaned.columns, pd.MultiIndex):
            cleaned.columns = [str(c[0]).strip().lower() for c in cleaned.columns]
        else:
            cleaned.columns = [str(c).strip().lower() for c in cleaned.columns]

        if isinstance(cleaned.index, pd.DatetimeIndex) or cleaned.index.name in (
            "datetime",
            "timestamp",
            "date",
            "Date",
            "Datetime",
        ):
            if "datetime" not in cleaned.columns and "timestamp" not in cleaned.columns:
                cleaned = cleaned.reset_index(names=["datetime"])
            else:
                cleaned = cleaned.reset_index(drop=True)

        if "datetime" in cleaned.columns:
            dt_series = pd.to_datetime(cleaned["datetime"], utc=True)
        elif "timestamp" in cleaned.columns:
            dt_series = pd.to_datetime(cleaned["timestamp"], utc=True)
        elif "date" in cleaned.columns:
            dt_series = pd.to_datetime(cleaned["date"], utc=True)
        else:
            raise ValueError("DataFrame must contain 'datetime'/'timestamp' column or DatetimeIndex")

        cleaned["datetime"] = dt_series

        # Yahoo Finance Forex feeds occasionally omit volume or report 0
        if "volume" not in cleaned.columns:
            cleaned["volume"] = 0.0

        missing = [c for c in required_cols if c not in cleaned.columns]
        if missing:
            raise ValueError(f"DataFrame missing required OHLCV columns: {missing}")

        for col in ("open", "high", "low", "close"):
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")
        cleaned["volume"] = pd.to_numeric(cleaned["volume"], errors="coerce").fillna(0.0).clip(lower=0.0)

        cleaned = cleaned.dropna(subset=["datetime", "open", "high", "low", "close"])
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

        if price_precision is None:
            sym_str = resolved_bar_type.instrument_id.symbol.value
            _, quote_code, _ = parse_fx_symbol(sym_str)
            p_prec, _ = infer_fx_precision(quote_code)
            if self.default_price_precision is not None:
                p_prec = self.default_price_precision
        else:
            p_prec = price_precision

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
    # OHLCV Market Data Fetching (Synchronized with SSIFetcher)
    # -------------------------------------------------------------------------

    def fetch_df(
        self,
        symbol: str,
        exchange: str | None = None,
        interval: str = "1d",
        start_date: str | pd.Timestamp | datetime | int | float | None = None,
        end_date: str | pd.Timestamp | datetime | int | float | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetches historical Forex/market OHLCV data from Yahoo Finance as a clean UTC DataFrame.

        Parameters
        ----------
        symbol : str
            Forex pair or symbol (e.g. 'EUR/USD', 'USD/VND', 'USDJPY', 'EURUSD=X', 'DXY').
        exchange : str, optional
            Venue identifier (defaults to `self.default_venue`, e.g. 'YAHOO').
        interval : str, default '1d'
            Timeframe ('1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1w', '1M').
        start_date : str | pd.Timestamp | datetime | int | float, optional
            Start time. Defaults to '1990-01-01' for daily/weekly/monthly (full history),
            or maximum allowed lookback window for intraday intervals.
        end_date : str | pd.Timestamp | datetime | int | float, optional
            End time. Defaults to current UTC timestamp.

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by UTC 'datetime' with columns: ['open', 'high', 'low', 'close', 'volume'].
        """
        # Support legacy `start`, `end`, `timeframe` keyword arguments if passed via kwargs
        if start_date is None and "start" in kwargs:
            start_date = kwargs.pop("start")
        if end_date is None and "end" in kwargs:
            end_date = kwargs.pop("end")
        if "timeframe" in kwargs:
            interval = kwargs.pop("timeframe")

        venue_str = (exchange or self.default_venue).strip().upper()
        base_code, quote_code, yf_ticker_str = parse_fx_symbol(symbol)
        pair_symbol = f"{base_code}/{quote_code}"
        norm_interval, yf_interval, _, _, resample_rule = self._resolve_interval_details(interval)

        empty_df = self.clean_dataframe(pd.DataFrame())
        empty_df.attrs["symbol"] = pair_symbol
        empty_df.attrs["yahoo_ticker"] = yf_ticker_str
        empty_df.attrs["exchange"] = venue_str
        empty_df.attrs["interval"] = norm_interval

        now_utc = pd.Timestamp.now(tz="UTC")
        end_dt = parse_utc_timestamp(end_date) if end_date is not None else now_utc

        if start_date is not None:
            start_dt = parse_utc_timestamp(start_date)
        else:
            if yf_interval in YF_MAX_LOOKBACK_DAYS:
                start_dt = now_utc - pd.Timedelta(days=YF_MAX_LOOKBACK_DAYS[yf_interval])
            else:
                start_dt = parse_utc_timestamp(FX_DEFAULT_START_DATE)

        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        # Respect Yahoo Finance lookback limits for intraday intervals
        query_start_dt = start_dt
        if yf_interval in YF_MAX_LOOKBACK_DAYS:
            limit_days = YF_MAX_LOOKBACK_DAYS[yf_interval]
            earliest_allowed = now_utc - pd.Timedelta(days=limit_days)
            if end_dt < earliest_allowed:
                logger.warning(
                    "[YahooFinance] %s (%s): Yahoo Finance retains %s data only for the last %d days. "
                    "Requested range (%s to %s) is before %s.",
                    yf_ticker_str,
                    yf_interval,
                    yf_interval,
                    limit_days,
                    start_dt.strftime("%Y-%m-%d"),
                    end_dt.strftime("%Y-%m-%d"),
                    earliest_allowed.strftime("%Y-%m-%d"),
                )
                return empty_df
            if start_dt < earliest_allowed:
                logger.info(
                    "[YahooFinance] Clamping start_date for %s (%s) from %s to %s (%d-day limit).",
                    yf_ticker_str,
                    yf_interval,
                    start_dt.strftime("%Y-%m-%d"),
                    earliest_allowed.strftime("%Y-%m-%d"),
                    limit_days,
                )
                query_start_dt = earliest_allowed

        try:
            ticker = yf.Ticker(yf_ticker_str)
            start_query = query_start_dt.strftime("%Y-%m-%d")
            end_query = (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            raw_df = ticker.history(
                start=start_query,
                end=end_query,
                interval=yf_interval,
                auto_adjust=False,
            )
        except Exception as err:
            logger.error("[YahooFinance] Error fetching %s (%s): %s", yf_ticker_str, yf_interval, err)
            return empty_df

        if raw_df is None or raw_df.empty:
            logger.warning("[YahooFinance] No data returned for %s (%s)", yf_ticker_str, yf_interval)
            return empty_df

        cleaned = self.clean_dataframe(raw_df)
        if cleaned.empty:
            return empty_df

        if resample_rule:
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

        cleaned = cleaned.loc[(cleaned.index >= query_start_dt) & (cleaned.index <= end_dt)]
        cleaned.attrs["symbol"] = pair_symbol
        cleaned.attrs["yahoo_ticker"] = yf_ticker_str
        cleaned.attrs["exchange"] = venue_str
        cleaned.attrs["interval"] = norm_interval
        return cleaned

    # Aliases matching SSIFetcher and legacy YahooFinanceFetcher
    get_ohlcv = fetch_df

    def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: str = "1h",
        start: str | pd.Timestamp | datetime | int | float | None = None,
        end: str | pd.Timestamp | datetime | int | float | None = None,
    ) -> pd.DataFrame:
        """Backward-compatible wrapper for `fetch_df`."""
        return self.fetch_df(
            symbol=symbol,
            interval=timeframe,
            start_date=start,
            end_date=end,
        )

    def fetch_batch_df(
        self,
        tickers: Sequence[dict[str, str] | tuple[str, str] | str],
        exchange: str | None = None,
        interval: str = "1d",
        start_date: str | pd.Timestamp | datetime | int | float | None = None,
        end_date: str | pd.Timestamp | datetime | int | float | None = None,
        delay_seconds: float = 0.1,
    ) -> dict[str, pd.DataFrame]:
        """Fetches historical OHLCV data in batch for multiple Forex pairs/symbols."""
        default_exch = (exchange or self.default_venue).strip().upper()
        norm_tickers: list[dict[str, str]] = []

        for item in tickers:
            if isinstance(item, dict):
                norm_tickers.append({
                    "exchange": item.get("exchange", default_exch).strip().upper(),
                    "symbol": item["symbol"].strip().upper(),
                })
            elif isinstance(item, tuple):
                sym_str, ex_str = item
                norm_tickers.append({"exchange": ex_str.strip().upper(), "symbol": sym_str.strip().upper()})
            elif isinstance(item, str):
                norm_tickers.append({"exchange": default_exch, "symbol": item.strip().upper()})
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
                )
                results[sym] = df
            except Exception as err:
                logger.warning("[%d/%d] Failed to fetch Yahoo OHLCV for %s: %s", idx, total, sym, err)

            if delay_seconds > 0 and idx < total:
                time.sleep(delay_seconds)

        return results

    def fetch_all_ohlcv(
        self,
        symbols: Sequence[str],
        exchange: str | None = None,
        interval: str = "1d",
        start_date: str | pd.Timestamp | datetime | int | float | None = None,
        end_date: str | pd.Timestamp | datetime | int | float | None = None,
        delay_seconds: float = 0.1,
    ) -> pd.DataFrame:
        """Fetches full historical OHLCV across multiple Forex pairs as a single combined DataFrame."""
        batch_dfs = self.fetch_batch_df(
            tickers=symbols,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            delay_seconds=delay_seconds,
        )

        frames: list[pd.DataFrame] = []
        for sym, df in batch_dfs.items():
            if not df.empty:
                frame = df.reset_index()
                frame.insert(1, "symbol", df.attrs.get("symbol", sym))
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
        start_date: str | pd.Timestamp | datetime | int | float | None = None,
        end_date: str | pd.Timestamp | datetime | int | float | None = None,
    ) -> list[Bar]:
        """Fetches Forex market data from Yahoo Finance and converts directly to Nautilus Bar objects."""
        exch = (exchange or self.default_venue).strip().upper()
        inst = instrument or self.create_currency_pair(
            symbol=symbol,
            venue=exch,
            price_precision=price_precision,
            size_precision=size_precision,
        )
        btype = bar_type or self.get_bar_type(instrument=inst, interval=interval, venue=exch)

        df = self.fetch_df(
            symbol=symbol,
            exchange=exch,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )

        p_prec = price_precision if price_precision is not None else inst.price_precision
        s_prec = size_precision if size_precision is not None else inst.size_precision

        return self.df_to_bars(
            df=df,
            bar_type=btype,
            price_precision=p_prec,
            size_precision=s_prec,
        )

    # Alias matching SSIFetcher
    get_ohlcv_bars = fetch_bars

    def fetch_bars_batch(
        self,
        tickers: Sequence[dict[str, str] | tuple[str, str] | str],
        exchange: str | None = None,
        interval: str = "1d",
        price_precision: int | None = None,
        size_precision: int | None = None,
        start_date: str | pd.Timestamp | datetime | int | float | None = None,
        end_date: str | pd.Timestamp | datetime | int | float | None = None,
        delay_seconds: float = 0.1,
    ) -> dict[str, list[Bar]]:
        """Fetches batch Forex market data and converts each to a list of Nautilus Bar objects."""
        dfs = self.fetch_batch_df(
            tickers=tickers,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            delay_seconds=delay_seconds,
        )

        bars_by_symbol: dict[str, list[Bar]] = {}
        for sym, df in dfs.items():
            exch = df.attrs.get("exchange", exchange or self.default_venue)
            inst = self.create_currency_pair(
                symbol=sym,
                venue=exch,
                price_precision=price_precision,
                size_precision=size_precision,
            )
            btype = self.get_bar_type(instrument=inst, interval=interval, venue=exch)
            bars_by_symbol[sym] = self.df_to_bars(
                df=df,
                bar_type=btype,
                price_precision=inst.price_precision,
                size_precision=inst.size_precision,
            )

        return bars_by_symbol

    # -------------------------------------------------------------------------
    # Nautilus ParquetDataCatalog & Raw File Persistence
    # -------------------------------------------------------------------------

    def get_catalog(self, catalog_path: str | Path | None = None) -> ParquetDataCatalog:
        """Returns or creates a Nautilus ParquetDataCatalog instance."""
        target_path = Path(catalog_path).expanduser().resolve() if catalog_path else self.catalog_path
        if target_path is None:
            raise ValueError(
                "Catalog path is required. Provide 'catalog_path' to method or initialize YahooFinanceFetcher(catalog_path=...)."
            )
        target_path.mkdir(parents=True, exist_ok=True)
        return ParquetDataCatalog(str(target_path))

    def save_to_catalog(
        self,
        bars: Sequence[Bar] | dict[str, list[Bar]] | None = None,
        instruments: Sequence[Instrument] | Instrument | None = None,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> ParquetDataCatalog:
        """Writes Forex CurrencyPair instruments and OHLCV bars into a Nautilus ParquetDataCatalog."""
        cat = catalog or self.get_catalog(catalog_path)

        if instruments is not None:
            if isinstance(instruments, Instrument):
                cat.write_data([instruments])
            elif len(instruments) > 0:
                cat.write_data(list(instruments))

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
        start_date: str | pd.Timestamp | datetime | int | float | None = None,
        end_date: str | pd.Timestamp | datetime | int | float | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> tuple[list[CurrencyPair], list[Bar]]:
        """End-to-end Forex pipeline: creates CurrencyPairs, fetches Yahoo OHLCV Bars, and persists to catalog."""
        symbol_list = [symbols] if isinstance(symbols, str) else list(symbols)
        exch = (exchange or self.default_venue).strip().upper()
        cat = catalog or self.get_catalog(catalog_path)

        instruments: list[CurrencyPair] = []
        all_bars: list[Bar] = []

        for sym in symbol_list:
            clean = sym.strip().upper()
            try:
                inst = self.create_currency_pair(
                    symbol=clean,
                    venue=exch,
                    price_precision=price_precision,
                    size_precision=size_precision,
                )
                bars = self.fetch_bars(
                    symbol=clean,
                    exchange=exch,
                    interval=interval,
                    instrument=inst,
                    price_precision=inst.price_precision,
                    size_precision=inst.size_precision,
                    start_date=start_date,
                    end_date=end_date,
                )
                instruments.append(inst)
                all_bars.extend(bars)
                self.save_to_catalog(bars=bars, instruments=[inst], catalog=cat)
            except Exception as err:
                logger.error("Failed in fetch_and_catalog for %s: %s", clean, err)

        return instruments, all_bars

    def save_raw(self, df: pd.DataFrame, symbol: str, timeframe: str = "1d") -> Path:
        """Saves raw DataFrame to `raw_dir` as Parquet for offline caching."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        clean_symbol = symbol.replace("/", "").replace("-", "").replace("=X", "").upper()
        start_str = df.index[0].strftime("%Y%m%d%H%M") if not df.empty else "empty"
        end_str = df.index[-1].strftime("%Y%m%d%H%M") if not df.empty else "empty"
        filename = f"yahoo_{clean_symbol}_{timeframe}_{start_str}_{end_str}.parquet"
        out_path = self.raw_dir / filename
        df.to_parquet(out_path)
        return out_path
