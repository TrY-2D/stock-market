from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from src.utils.time import datetime_to_nanoseconds, to_nanoseconds_array


@customdataclass
class EconomicData(Data):
    """Represents a macroeconomic observation formatted for Nautilus Trader backtesting and data catalogs.

    Attributes
    ----------
    instrument_id : InstrumentId
        Unique Nautilus instrument identifier (e.g. INFLATION_CPI.VIETNAM, GOVERNMENT_BOND_YIELD.VIETNAM).
    name : str
        Canonical indicator name (e.g. 'INFLATION_RATE', 'GOVERNMENT_BOND_YIELD').
    country : str
        Country in uppercase (e.g. 'VIETNAM', 'UNITED_STATES').
    symbol : str
        Unique indicator series code (e.g. 'VIETNAM_INFLATION_RATE', 'VNMGOVBON10Y:GOV').
    date : str
        Observation date in 'YYYY-MM-DD' format.
    value : float
        Numerical value of the indicator (e.g. 5.08 for 5.08% inflation).
    unit : str
        Unit of measure (e.g. '%', 'points', 'USD').
    """

    instrument_id: InstrumentId
    name: str
    country: str
    symbol: str
    date: str
    value: float
    unit: str


@dataclass
class EconomicDataPoint:
    """Raw observation point from economic data provider."""

    name: str
    country: str
    symbol: str
    date: str
    value: float
    unit: str = "%"
    instrument_id: InstrumentId | None = None

    def to_economic_data(self) -> EconomicData:
        """Converts to Nautilus Trader EconomicData custom data object."""
        inst_id = self.instrument_id or InstrumentId(
            symbol=Symbol(self.name.upper()),
            venue=Venue(self.country.upper()),
        )
        ts = datetime_to_nanoseconds(self.date)
        return EconomicData(
            instrument_id=inst_id,
            name=self.name,
            country=self.country,
            symbol=self.symbol,
            date=self.date,
            value=self.value,
            unit=self.unit,
            ts_event=ts,
            ts_init=ts,
        )


def points_to_dataframe(
    points: Sequence[EconomicData | EconomicDataPoint],
) -> pd.DataFrame:
    """Converts a sequence of EconomicData or EconomicDataPoint to a pandas DataFrame with UTC DatetimeIndex.

    Columns: ['value', 'indicator', 'country', 'symbol', 'unit', 'instrument_id']
    Index: 'datetime' (pd.DatetimeIndex UTC)
    """
    if not points:
        return pd.DataFrame(
            columns=["value", "indicator", "country", "symbol", "unit", "instrument_id"]
        )

    records = []
    for p in points:
        inst_str = str(p.instrument_id) if hasattr(p, "instrument_id") and p.instrument_id is not None else f"{p.name}.{p.country}"
        records.append({
            "datetime": pd.to_datetime(p.date, utc=True),
            "value": float(p.value),
            "indicator": p.name,
            "country": p.country,
            "symbol": p.symbol,
            "unit": p.unit,
            "instrument_id": inst_str,
        })

    df = pd.DataFrame(records)
    df = df.sort_values(by="datetime", ascending=True)
    df = df.drop_duplicates(subset=["datetime"], keep="last")
    return df.set_index("datetime")


def points_to_bars(
    points: Sequence[EconomicData | EconomicDataPoint],
    bar_type: BarType | str,
    price_precision: int = 4,
    size_precision: int = 0,
) -> list[Bar]:
    """Converts a sequence of economic observations to a list of Nautilus Bar objects.

    Useful when modeling bond yields or rates as tradable price bars or benchmark indicators in Nautilus Trader.
    """
    if not points:
        return []

    resolved_bar_type = BarType.from_str(bar_type) if isinstance(bar_type, str) else bar_type
    df = points_to_dataframe(points)
    if df.empty:
        return []

    ts_events = np.ascontiguousarray(to_nanoseconds_array(df.index)).copy()
    values = np.ascontiguousarray(df["value"].to_numpy(dtype=np.float64)).copy()
    volumes = np.zeros_like(values, dtype=np.float64)

    return Bar.from_raw_arrays_to_list(
        resolved_bar_type,
        price_precision,
        size_precision,
        values,  # open
        values,  # high
        values,  # low
        values,  # close
        volumes, # volume
        ts_events,
        ts_events,
    )
