from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import vnquantpy

from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair, Equity, Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.utils.time import to_nanoseconds_array

logger = logging.getLogger(__name__)

# Supported interval mapping: key -> (TradingView interval string, step, BarAggregation)
INTERVAL_LOOKUP: dict[str, tuple[str, int, BarAggregation]] = {
    "1m": ("1m", 1, BarAggregation.MINUTE),
    "3m": ("3m", 3, BarAggregation.MINUTE),
    "5m": ("5m", 5, BarAggregation.MINUTE),
    "15m": ("15m", 15, BarAggregation.MINUTE),
    "30m": ("30m", 30, BarAggregation.MINUTE),
    "45m": ("45m", 45, BarAggregation.MINUTE),
    "1h": ("1h", 1, BarAggregation.HOUR),
    "2h": ("2h", 2, BarAggregation.HOUR),
    "3h": ("3h", 3, BarAggregation.HOUR),
    "4h": ("4h", 4, BarAggregation.HOUR),
    "1d": ("1d", 1, BarAggregation.DAY),
    "1w": ("1w", 1, BarAggregation.WEEK),
    "1M": ("1M", 1, BarAggregation.MONTH),
}


class TradingviewFetcher:
    """Fetcher for TradingView market data via vnquantpy with Nautilus Trader model integration."""

    def __init__(
        self,
        auth_token: str | None = None,
        default_venue: str = "HOSE",
        default_currency: str = "VND",
        default_price_precision: int = 2,
        default_size_precision: int = 0,
        catalog_path: str | Path | None = None,
    ) -> None:
        """Initializes TradingviewFetcher.

        Parameters
        ----------
        auth_token : str, optional
            TradingView authentication token. If None, falls back to TV_AUTH_TOKEN
            environment variable, and then to 'unauthorized_user_token'.
        default_venue : str, default 'HOSE'
            Default exchange venue (e.g. 'HOSE', 'HNX', 'UPCOM').
        default_currency : str, default 'VND'
            Default quote currency for equity instruments.
        default_price_precision : int, default 2
            Default decimal precision for prices.
        default_size_precision : int, default 0
            Default decimal precision for quantities/volumes (shares are integers).
        catalog_path : str | Path, optional
            Path to the Nautilus ParquetDataCatalog root directory.
        """
        self._auth_token = auth_token
        self.default_venue = default_venue.strip().upper()
        self.default_currency = default_currency.strip().upper()
        self.default_price_precision = default_price_precision
        self.default_size_precision = default_size_precision
        self.catalog_path = Path(catalog_path).expanduser().resolve() if catalog_path else None
        self._catalog: ParquetDataCatalog | None = None

    @property
    def auth_token(self) -> str:
        """Resolves active auth token from instance, environment, or default guest token."""
        if self._auth_token:
            return self._auth_token
        env_token = os.environ.get("TV_AUTH_TOKEN")
        if env_token:
            return env_token
        return "unauthorized_user_token"

    # -------------------------------------------------------------------------
    # Interval and BarType helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_interval(interval: str) -> tuple[str, int, BarAggregation]:
        """Parses an interval string into TradingView format, step, and BarAggregation.

        Supported intervals:
        - Minutes: '1m', '3m', '5m', '15m', '30m', '45m' (also '1min', '15min', etc.)
        - Hours: '1h', '2h', '3h', '4h' (case-insensitive)
        - Days: '1d', 'd', 'daily' (case-insensitive)
        - Weeks: '1w', 'w', 'weekly' (case-insensitive)
        - Months: '1M', 'M', 'monthly'

        Returns
        -------
        tuple[str, int, BarAggregation]
            (tv_interval, step, bar_aggregation)
        """
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

        if low.endswith("min") or (low.endswith("m") and low[:-1].isdigit()):
            digits = "".join(filter(str.isdigit, low))
            val = f"{digits}m"
            if val in INTERVAL_LOOKUP:
                return INTERVAL_LOOKUP[val]

        raise ValueError(
            f"Unsupported interval: '{interval}'. Supported intervals are: "
            f"{list(INTERVAL_LOOKUP.keys())}"
        )

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
                venue_obj = Venue(venue) if venue else Venue(self.default_venue)
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
    # Instrument creation
    # -------------------------------------------------------------------------

    def create_equity(
        self,
        symbol: str,
        venue: str | Venue | None = None,
        *,
        currency: str | Currency | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        price_increment: float | Price | None = 100.0,
        lot_size: float | Quantity | None = 100.0,
        max_quantity: float | Quantity | None = 1e9,
        min_quantity: float | Quantity | None = 1.0,
        ts_event: int = 0,
        ts_init: int = 0,
    ) -> Equity:
        """Creates a standardized Nautilus Equity instrument for stock markets (HOSE, HNX, UPCOM)."""
        clean_symbol = symbol.strip().upper()
        venue_obj = venue if isinstance(venue, Venue) else Venue(venue or self.default_venue)
        curr_obj = currency if isinstance(currency, Currency) else Currency.from_str(currency or self.default_currency)

        p_prec = self.default_price_precision if price_precision is None else price_precision
        s_prec = self.default_size_precision if size_precision is None else size_precision

        price_inc = (
            price_increment
            if isinstance(price_increment, Price)
            else Price(price_increment if price_increment is not None else 100.0, precision=p_prec)
        )
        lot = (
            lot_size
            if isinstance(lot_size, Quantity)
            else Quantity(lot_size if lot_size is not None else 100.0, precision=s_prec)
        )
        max_q = (
            max_quantity
            if isinstance(max_quantity, Quantity) or max_quantity is None
            else Quantity(max_quantity, precision=s_prec)
        )
        min_q = (
            min_quantity
            if isinstance(min_quantity, Quantity) or min_quantity is None
            else Quantity(min_quantity, precision=s_prec)
        )

        inst_id = InstrumentId(symbol=Symbol(clean_symbol), venue=venue_obj)

        return Equity(
            instrument_id=inst_id,
            raw_symbol=Symbol(clean_symbol),
            currency=curr_obj,
            price_precision=p_prec,
            price_increment=price_inc,
            lot_size=lot,
            max_quantity=max_q,
            min_quantity=min_q,
            ts_event=int(ts_event),
            ts_init=int(ts_init),
        )

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
        """Creates a standardized Nautilus instrument (Equity or CurrencyPair).

        Maintains backward compatibility while supporting Equity instruments.
        """
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
    # DataFrame cleaning and transformation
    # -------------------------------------------------------------------------

    @staticmethod
    def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Sanitizes raw market data DataFrame from vnquantpy/TradingView.

        Standardizes columns, cleans timestamps to UTC DatetimeIndex, drops nulls/invalids,
        removes duplicate timestamps, and ensures OHLC price sanity.
        """
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        cleaned = df.copy()
        cleaned.columns = [str(c).strip().lower() for c in cleaned.columns]

        # Reset index if it was already a DatetimeIndex or named datetime/timestamp
        if isinstance(cleaned.index, pd.DatetimeIndex) or cleaned.index.name in ("datetime", "timestamp"):
            if "datetime" not in cleaned.columns and "timestamp" not in cleaned.columns:
                cleaned = cleaned.reset_index(names=["datetime"])
            else:
                cleaned = cleaned.reset_index(drop=True)

        # Extract datetime series
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
            return pd.DataFrame(columns=required_cols)

        # Sort chronologically and drop duplicates
        cleaned = cleaned.sort_values(by="datetime", ascending=True)
        cleaned = cleaned.drop_duplicates(subset=["datetime"], keep="last")

        # Guarantee OHLC boundary invariants (high >= max(open, close), low <= min(open, close))
        o = cleaned["open"].to_numpy(dtype=np.float64)
        h = cleaned["high"].to_numpy(dtype=np.float64)
        l = cleaned["low"].to_numpy(dtype=np.float64)
        c = cleaned["close"].to_numpy(dtype=np.float64)

        cleaned["high"] = np.maximum(h, np.maximum(o, c))
        cleaned["low"] = np.minimum(l, np.minimum(o, c))

        cleaned = cleaned.set_index("datetime")
        return cleaned

    # -------------------------------------------------------------------------
    # Nautilus Bar conversion
    # -------------------------------------------------------------------------

    def df_to_bars(
        self,
        df: pd.DataFrame,
        bar_type: BarType | str,
        price_precision: int | None = None,
        size_precision: int | None = None,
        ts_init_delta: int = 0,
    ) -> list[Bar]:
        """Converts a DataFrame of OHLCV data to a list of Nautilus Bar objects.

        Uses vectorized Rust/Cython memory construction with contiguous writable
        arrays, ensuring compatibility with Pandas 3.0 Copy-on-Write semantics.
        """
        resolved_bar_type = BarType.from_str(bar_type) if isinstance(bar_type, str) else bar_type

        cleaned = self.clean_dataframe(df)
        if cleaned.empty:
            return []

        p_prec = self.default_price_precision if price_precision is None else price_precision
        s_prec = self.default_size_precision if size_precision is None else size_precision

        # Extract timestamps in uint64 nanoseconds
        ts_events = np.ascontiguousarray(to_nanoseconds_array(cleaned.index)).copy()
        ts_inits = ts_events + np.uint64(ts_init_delta)

        # Ensure writable C-contiguous arrays for Cython memoryviews
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
    # Market data fetching
    # -------------------------------------------------------------------------

    def fetch_df(
        self,
        symbol: str,
        exchange: str | None = None,
        interval: str = "1d",
        with_replay: bool = False,
        auth_token: str | None = None,
    ) -> pd.DataFrame:
        """Fetches historical market data from TradingView via vnquantpy as a clean DataFrame."""
        exch = (exchange or self.default_venue).strip().upper()
        sym = symbol.strip().upper()
        tv_interval, _, _ = self.parse_interval(interval)
        token = auth_token or self.auth_token

        ticker = {"exchange": exch, "symbol": sym}
        try:
            raw_df = vnquantpy.fetch_market_data(
                ticker=ticker,
                interval=tv_interval,
                auth_token=token,
                with_replay=with_replay,
            )
        except Exception as e:
            logger.error("Failed to fetch market data for %s/%s [%s]: %s", sym, exch, tv_interval, e)
            raise

        cleaned = self.clean_dataframe(raw_df)
        cleaned.attrs["symbol"] = sym
        cleaned.attrs["exchange"] = exch
        cleaned.attrs["interval"] = tv_interval
        return cleaned

    def fetch_batch_df(
        self,
        tickers: Sequence[dict[str, str] | tuple[str, str] | str],
        exchange: str | None = None,
        interval: str = "1d",
        auth_token: str | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetches historical market data in batch for multiple tickers.

        Returns
        -------
        dict[str, pd.DataFrame]
            Mapping of symbol to sanitized DataFrame.
        """
        default_exch = (exchange or self.default_venue).strip().upper()
        tv_interval, _, _ = self.parse_interval(interval)
        token = auth_token or self.auth_token

        norm_tickers: list[dict[str, str]] = []
        for item in tickers:
            if isinstance(item, dict):
                norm_tickers.append({
                    "exchange": item.get("exchange", default_exch).strip().upper(),
                    "symbol": item["symbol"].strip().upper(),
                })
            elif isinstance(item, tuple):
                sym, exch = item
                norm_tickers.append({"exchange": exch.strip().upper(), "symbol": sym.strip().upper()})
            elif isinstance(item, str):
                norm_tickers.append({"exchange": default_exch, "symbol": item.strip().upper()})
            else:
                raise TypeError(f"Unsupported ticker item type: {type(item)}")

        if not norm_tickers:
            return {}

        try:
            df_list = vnquantpy.fetch_market_data_in_batch(
                tickers=norm_tickers,
                interval=tv_interval,
                auth_token=token,
            )
        except Exception as e:
            logger.error("Failed to fetch market data batch for %d tickers: %s", len(norm_tickers), e)
            raise

        results: dict[str, pd.DataFrame] = {}
        for raw_df in df_list:
            sym = getattr(raw_df, "symbol", None)
            exch = getattr(raw_df, "exchange", default_exch)
            cleaned = self.clean_dataframe(raw_df)
            if sym is not None:
                cleaned.attrs["symbol"] = sym
                cleaned.attrs["exchange"] = exch
                cleaned.attrs["interval"] = tv_interval
                results[sym] = cleaned

        return results

    def fetch_bars(
        self,
        symbol: str,
        exchange: str | None = None,
        interval: str = "1d",
        instrument: Instrument | None = None,
        bar_type: BarType | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
        with_replay: bool = False,
        auth_token: str | None = None,
    ) -> list[Bar]:
        """Fetches market data and converts directly to Nautilus Bar objects."""
        exch = (exchange or self.default_venue).strip().upper()
        sym = symbol.strip().upper()

        if bar_type is None:
            inst = instrument or self.create_equity(symbol=sym, venue=exch)
            bar_type = self.get_bar_type(instrument=inst, interval=interval, venue=exch)

        df = self.fetch_df(
            symbol=sym,
            exchange=exch,
            interval=interval,
            with_replay=with_replay,
            auth_token=auth_token,
        )

        p_prec = price_precision if price_precision is not None else (instrument.price_precision if instrument else self.default_price_precision)
        s_prec = size_precision if size_precision is not None else (instrument.size_precision if instrument else self.default_size_precision)

        return self.df_to_bars(
            df=df,
            bar_type=bar_type,
            price_precision=p_prec,
            size_precision=s_prec,
        )

    def fetch_bars_batch(
        self,
        tickers: Sequence[dict[str, str] | tuple[str, str] | str],
        exchange: str | None = None,
        interval: str = "1d",
        price_precision: int | None = None,
        size_precision: int | None = None,
        auth_token: str | None = None,
    ) -> dict[str, list[Bar]]:
        """Fetches batch market data and converts each to a list of Nautilus Bar objects."""
        dfs = self.fetch_batch_df(
            tickers=tickers,
            exchange=exchange,
            interval=interval,
            auth_token=auth_token,
        )

        bars_by_symbol: dict[str, list[Bar]] = {}
        for sym, df in dfs.items():
            exch = df.attrs.get("exchange", exchange or self.default_venue)
            inst = self.create_equity(symbol=sym, venue=exch)
            btype = self.get_bar_type(instrument=inst, interval=interval, venue=exch)
            bars_by_symbol[sym] = self.df_to_bars(
                df=df,
                bar_type=btype,
                price_precision=price_precision,
                size_precision=size_precision,
            )

        return bars_by_symbol

    # -------------------------------------------------------------------------
    # Nautilus Data Catalog persistence
    # -------------------------------------------------------------------------

    def get_catalog(self, catalog_path: str | Path | None = None) -> ParquetDataCatalog:
        """Returns or creates a Nautilus ParquetDataCatalog instance."""
        target_path = Path(catalog_path).expanduser().resolve() if catalog_path else self.catalog_path
        if target_path is None:
            raise ValueError(
                "Catalog path is required. Provide 'catalog_path' to method or initialize TradingviewFetcher(catalog_path=...)."
            )
        target_path.mkdir(parents=True, exist_ok=True)
        return ParquetDataCatalog(str(target_path))

    def save_to_catalog(
        self,
        bars: list[Bar] | dict[str, list[Bar]],
        instruments: Sequence[Instrument] | Instrument | None = None,
        catalog: ParquetDataCatalog | None = None,
        catalog_path: str | Path | None = None,
    ) -> ParquetDataCatalog:
        """Writes instruments and bars directly into a Nautilus ParquetDataCatalog."""
        cat = catalog or self.get_catalog(catalog_path)

        if instruments is not None:
            if isinstance(instruments, Instrument):
                cat.write_data([instruments])
            elif len(instruments) > 0:
                cat.write_data(list(instruments))

        if isinstance(bars, dict):
            for _, bar_list in bars.items():
                if bar_list:
                    cat.write_data(bar_list)
        elif bars:
            cat.write_data(bars)

        return cat

    def fetch_and_catalog(
        self,
        symbols: str | Sequence[str],
        exchange: str | None = None,
        interval: str = "1d",
        catalog: ParquetDataCatalog | None = None,
        catalog_path: str | Path | None = None,
        auth_token: str | None = None,
        price_precision: int | None = None,
        size_precision: int | None = None,
    ) -> tuple[list[Instrument], list[Bar]]:
        """End-to-end pipeline: fetches market data, models instruments and bars, and persists to Nautilus ParquetDataCatalog.

        Returns
        -------
        tuple[list[Instrument], list[Bar]]
            The created instruments and all generated bars.
        """
        exch = (exchange or self.default_venue).strip().upper()
        symbol_list = [symbols] if isinstance(symbols, str) else list(symbols)

        cat = catalog or self.get_catalog(catalog_path)
        all_instruments: list[Instrument] = []
        all_bars: list[Bar] = []

        if len(symbol_list) == 1:
            sym = symbol_list[0].strip().upper()
            inst = self.create_equity(symbol=sym, venue=exch)
            bars = self.fetch_bars(
                symbol=sym,
                exchange=exch,
                interval=interval,
                instrument=inst,
                price_precision=price_precision,
                size_precision=size_precision,
                auth_token=auth_token,
            )
            all_instruments.append(inst)
            all_bars.extend(bars)
            self.save_to_catalog(bars=bars, instruments=[inst], catalog=cat)
        else:
            batch_result = self.fetch_bars_batch(
                tickers=symbol_list,
                exchange=exch,
                interval=interval,
                price_precision=price_precision,
                size_precision=size_precision,
                auth_token=auth_token,
            )
            for sym, bars in batch_result.items():
                inst = self.create_equity(symbol=sym, venue=exch)
                all_instruments.append(inst)
                all_bars.extend(bars)
                self.save_to_catalog(bars=bars, instruments=[inst], catalog=cat)

        return all_instruments, all_bars

    # -------------------------------------------------------------------------
    # Symbol discovery and search
    # -------------------------------------------------------------------------

    @staticmethod
    def list_symbols(
        country: str = "VN",
        exchange: str | None = None,
        market_type: str = "stock",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lists symbols matching the filters from TradingView via vnquantpy."""
        return vnquantpy.list_symbols(
            country=country,
            market_type=market_type,
            exchange=exchange,
            limit=limit,
        )

    @staticmethod
    def search_symbol(
        query: str,
        country: str = "VN",
        exchange: str | None = None,
        market_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Searches symbols on TradingView via vnquantpy."""
        return vnquantpy.search_symbol(
            search=query,
            country=country,
            market_type=market_type,
            exchange=exchange,
            limit=limit,
        )
