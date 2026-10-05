from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity, Instrument
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.ssi.constants import (
    CAP_AND_DIVIDEND_ENDPOINT,
    COMPANY_PROFILE_ENDPOINT,
    CORPORATE_ACTIONS_ENDPOINT,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    IBOARD_API_BASE_URL,
    IBOARD_QUERY_BASE_URL,
    RETRY_STATUS_CODES,
    SECTORS_DATA_ENDPOINT,
    STOCK_INFO_ENDPOINT,
)
from src.data_pipeline.ssi.models import (
    CompanyListingInfo,
    Dividend,
    calculate_price_increment,
)
from src.utils.time import datetime_to_nanoseconds

logger = logging.getLogger(__name__)


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


class SSIFetcher:
    """Fetcher for SSI iBoard market data APIs with Nautilus Trader integration."""

    def __init__(
        self,
        *,
        query_base_url: str = IBOARD_QUERY_BASE_URL,
        api_base_url: str = IBOARD_API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        catalog_path: str | Path | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initializes SSIFetcher HTTP client and Nautilus Trader catalog settings.

        Parameters
        ----------
        query_base_url : str
            Base URL for SSI iBoard query services.
        api_base_url : str
            Base URL for SSI iBoard statistics and company API services.
        timeout : float
            Request timeout in seconds.
        max_retries : int
            Max retry attempts on network failures or 5xx/429 HTTP statuses.
        backoff_factor : float
            Multiplier for exponential backoff on retries.
        catalog_path : str | Path, optional
            Default root path for Nautilus Trader ParquetDataCatalog.
        headers : dict[str, str], optional
            Custom request headers.
        """
        self.query_base_url = query_base_url.rstrip("/")
        self.api_base_url = api_base_url.rstrip("/")
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
    # Listed Companies & Listing Info
    # -------------------------------------------------------------------------

    def get_listed_companies(
        self,
        exchange: str | None = None,
        stock_type_only: bool = True,
        refresh_cache: bool = False,
    ) -> pd.DataFrame:
        """Fetches all listed companies and securities tracked by SSI iBoard.

        Parameters
        ----------
        exchange : str, optional
            Filter by exchange: 'HOSE', 'HNX', 'UPCOM'. If None, returns all.
        stock_type_only : bool, default True
            If True, only returns equity shares (type == 's'), filtering out
            warrants ('w'), futures ('f'), bonds ('b'), etc.
        refresh_cache : bool, default False
            If True, forces re-fetching from SSI endpoint.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: ['symbol', 'exchange', 'company_name', 'client_name_en', 'isin', 'type']
        """
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

    def get_listing_info(
        self,
        symbol: str,
        language: str = "vn",
    ) -> CompanyListingInfo:
        """Fetches comprehensive company profile and listing metadata for a given symbol.

        Parameters
        ----------
        symbol : str
            Ticker symbol (e.g. 'VCB', 'HPG', 'FPT').
        language : str, default 'vn'
            Language code ('vn' or 'en').

        Returns
        -------
        CompanyListingInfo
            Standardized listing metadata object.
        """
        clean_sym = symbol.strip().upper()
        url = f"{self.api_base_url}{COMPANY_PROFILE_ENDPOINT}"
        params = {"symbol": clean_sym, "language": language}
        payload = self._request("GET", url, params=params)

        record = payload.get("data")
        if not isinstance(record, dict):
            raise ValueError(f"Missing or invalid 'data' object in company profile for {clean_sym}")

        # Try to resolve ISIN from profile, fallback to stock-info cache
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
            # Fallback exchange lookup from stock-info
            try:
                stocks = self.get_listed_companies()
                matched = stocks[stocks["symbol"] == clean_sym]
                if not matched.empty:
                    exchange = matched.iloc[0]["exchange"]
            except Exception:
                exchange = "HOSE"

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

    def create_equity(
        self,
        symbol: str,
        venue: str | None = None,
        listing_info: CompanyListingInfo | None = None,
        current_price: float | None = None,
        price_precision: int = 2,
        size_precision: int = 0,
        lot_size: float = 100.0,
    ) -> Equity:
        """Creates a standardized Nautilus Trader Equity instrument with enriched listing metadata."""
        info = listing_info or self.get_listing_info(symbol)
        if venue:
            info.exchange = venue.strip().upper()

        return info.to_equity(
            current_price=current_price,
            price_precision=price_precision,
            size_precision=size_precision,
            lot_size=lot_size,
        )

    def create_equities_batch(
        self,
        symbols: Sequence[str],
        venue: str | None = None,
        price_precision: int = 2,
        size_precision: int = 0,
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
        """Fetches historical annual capital, assets, and dividend distribution series for a symbol.

        Returns DataFrame indexed by year with columns: ['year', 'cash_dividend', 'asset', 'owner_capital'].
        """
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
        """Fetches complete cash dividend distribution history formatted for Nautilus Trader backtesting.

        Combines exact corporate action records (exrightDate, recordDate, paymentDate, value)
        and multi-year historical dividend distributions (cap-and-dividend).

        Returns
        -------
        list[Dividend]
            List of Nautilus Trader Dividend custom data objects sorted monotonically by ts_event.
        """
        clean_sym = symbol.strip().upper()
        exch = exchange or "HOSE"
        if exchange is None:
            try:
                info = self.get_listing_info(clean_sym)
                exch = info.exchange
            except Exception:
                exch = "HOSE"

        inst_id = InstrumentId(Symbol(clean_sym), Venue(exch))

        dividends: list[Dividend] = []
        covered_years: set[int] = set()

        # 1. Detailed corporate actions from SSI
        try:
            corp_actions = self.get_corporate_actions(clean_sym, dividend_only=True)
            for a in corp_actions:
                name = str(a.get("eventName") or "").lower()
                title = str(a.get("eventTitle") or "").lower()
                # Ensure cash dividend
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

                # Fallback ex_date to record or pay or public date
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
                    if amt <= 0:
                        continue

                    # If this year was already covered by corporate actions, skip duplicate
                    if yr in covered_years:
                        continue

                    covered_years.add(yr)
                    # For historical annual summaries, anchor date to year end (December 31)
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

        # Sort strictly ascending by ts_event (required by Nautilus Trader Data monotonicity)
        dividends.sort(key=lambda d: d.ts_event)
        return dividends

    def get_cash_dividends_df(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """Fetches historical cash dividends as a pandas DataFrame with UTC DatetimeIndex.

        Columns: ['instrument_id', 'symbol', 'amount', 'ex_date', 'record_date', 'payment_date', 'fiscal_year', 'ratio', 'description']
        Indexed by: 'datetime' (ex-dividend date in UTC).
        """
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
    # Nautilus ParquetDataCatalog persistence
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
        instruments: Sequence[Instrument] | Instrument | None = None,
        dividends: Sequence[Dividend] | None = None,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> ParquetDataCatalog:
        """Writes instruments and dividends directly into a Nautilus ParquetDataCatalog."""
        cat = catalog or self.get_catalog(catalog_path)

        if instruments is not None:
            if isinstance(instruments, Instrument):
                cat.write_data([instruments])
            elif len(instruments) > 0:
                cat.write_data(list(instruments))

        if dividends is not None and len(dividends) > 0:
            cat.write_data(list(dividends))

        return cat

    def fetch_and_catalog(
        self,
        symbols: str | Sequence[str],
        exchange: str | None = None,
        catalog_path: str | Path | None = None,
        catalog: ParquetDataCatalog | None = None,
    ) -> tuple[list[Equity], list[Dividend]]:
        """Fetches listing info, creates Nautilus Equities, fetches dividend history, and persists to catalog.

        Returns
        -------
        tuple[list[Equity], list[Dividend]]
            Created equities and collected dividend events.
        """
        symbol_list = [symbols] if isinstance(symbols, str) else list(symbols)
        cat = catalog or self.get_catalog(catalog_path)

        equities: list[Equity] = []
        all_dividends: list[Dividend] = []

        for sym in symbol_list:
            clean = sym.strip().upper()
            try:
                eq = self.create_equity(clean, venue=exchange)
                equities.append(eq)
                divs = self.get_cash_dividends(clean, exchange=eq.venue.value)
                all_dividends.extend(divs)
                self.save_to_catalog(instruments=[eq], dividends=divs, catalog=cat)
            except Exception as err:
                logger.error("Failed in fetch_and_catalog for %s: %s", clean, err)

        return equities, all_dividends
