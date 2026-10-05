
from dataclasses import dataclass, field
from typing import Any

from nautilus_trader.core.data import Data
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Price, Quantity
from src.utils.time import datetime_to_nanoseconds


def calculate_price_increment(price: float | None = None, venue: str = "HOSE") -> float:
    """Calculates standardized tick size (price_increment) based on Vietnam exchange regulations.

    HOSE rules:
    - Price < 10,000 VND: tick size is 10 VND.
    - 10,000 <= Price < 50,000 VND: tick size is 50 VND.
    - Price >= 50,000 VND: tick size is 100 VND.

    HNX & UPCOM rules:
    - All price tiers: tick size is 100 VND.
    """
    v = (venue or "HOSE").strip().upper()
    if v != "HOSE" or price is None or price <= 0:
        return 100.0

    if price < 10000.0:
        return 10.0
    elif price < 50000.0:
        return 50.0
    else:
        return 100.0


@customdataclass
class Dividend(Data):
    """Represents a cash dividend distribution event for Nautilus Trader backtesting.

    Attributes
    ----------
    instrument_id : InstrumentId
        The instrument identifier (e.g. VCB.HOSE).
    amount : float
        Cash dividend amount per share in quote currency (VND).
    ex_date : str
        Ex-dividend date (ngày giao dịch không hưởng quyền) in 'YYYY-MM-DD' format.
    record_date : str
        Last registration / record date (ngày đăng ký cuối cùng) in 'YYYY-MM-DD' format.
    payment_date : str
        Payment date (ngày thực hiện chi trả) in 'YYYY-MM-DD' format.
    fiscal_year : int
        Fiscal year of the dividend distribution.
    ratio : float
        Dividend ratio relative to par value (e.g. 0.045 for 4.5% = 450 VND).
    description : str
        Details or announcement memo.
    """

    instrument_id: InstrumentId
    amount: float
    ex_date: str
    record_date: str
    payment_date: str
    fiscal_year: int
    ratio: float
    description: str


@dataclass
class CompanyListingInfo:
    """Standardized company listing metadata from SSI iBoard."""

    symbol: str
    exchange: str
    company_name: str
    client_name_en: str | None = None
    isin: str | None = None
    listing_date: str | None = None  # Format 'YYYY-MM-DD'
    founding_date: str | None = None  # Format 'YYYY-MM-DD'
    issue_shares: float | None = None  # Total issued shares
    circulating_shares: float | None = None  # Circulating / listed quantity
    charter_capital: float | None = None  # VND
    first_price: float | None = None  # First listing price in VND
    free_float_rate: float | None = None  # In percent
    industry_name: str | None = None
    sector: str | None = None
    sub_sector: str | None = None
    website: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Returns clean dictionary representation of listing metadata."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "company_name": self.company_name,
            "client_name_en": self.client_name_en,
            "isin": self.isin,
            "listing_date": self.listing_date,
            "founding_date": self.founding_date,
            "issue_shares": self.issue_shares,
            "circulating_shares": self.circulating_shares,
            "charter_capital": self.charter_capital,
            "first_price": self.first_price,
            "free_float_rate": self.free_float_rate,
            "industry_name": self.industry_name,
            "sector": self.sector,
            "sub_sector": self.sub_sector,
            "website": self.website,
        }

    def to_equity(
        self,
        current_price: float | None = None,
        price_precision: int = 2,
        size_precision: int = 0,
        lot_size: float = 100.0,
    ) -> Equity:
        """Constructs a standardized Nautilus Trader Equity instrument with enriched listing metadata."""
        clean_sym = self.symbol.strip().upper()
        clean_venue = self.exchange.strip().upper()

        ref_price = current_price or self.first_price or 10000.0
        tick_size = calculate_price_increment(ref_price, clean_venue)

        # Listing date as ts_event in nanoseconds UTC (if available, else 0)
        ts_event = datetime_to_nanoseconds(self.listing_date) if self.listing_date else 0

        max_q = self.circulating_shares if self.circulating_shares and self.circulating_shares > 0 else 1e9

        return Equity(
            instrument_id=InstrumentId(Symbol(clean_sym), Venue(clean_venue)),
            raw_symbol=Symbol(clean_sym),
            currency=Currency.from_str("VND"),
            price_precision=price_precision,
            price_increment=Price(tick_size, precision=price_precision),
            lot_size=Quantity(lot_size, precision=size_precision),
            max_quantity=Quantity(max_q, precision=size_precision),
            min_quantity=Quantity(1.0, precision=size_precision),
            ts_event=ts_event,
            ts_init=ts_event,
            isin=self.isin,
            info=self.to_dict(),
        )
