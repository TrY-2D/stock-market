import numpy as np
import pandas as pd
from typing import Any

def parse_utc_timestamp(val: Any) -> pd.Timestamp:
    """Parses any timestamp (nanoseconds, milliseconds, seconds, string, Timestamp) to UTC Timestamp."""
    if val is None:
        return pd.Timestamp.now(tz="UTC")
    if isinstance(val, (int, float)):
        if val > 1e14:  # Nanoseconds (Nautilus Trader format)
            return pd.to_datetime(int(val), unit="ns", utc=True)
        elif val > 1e11:  # Milliseconds (CCXT format)
            return pd.to_datetime(int(val), unit="ms", utc=True)
        else:  # Seconds
            return pd.to_datetime(float(val), unit="s", utc=True)
    return pd.to_datetime(val, utc=True)

def datetime_to_nanoseconds(val: Any) -> int:
    """Converts any timestamp to integer UNIX timestamp in nanoseconds (Nautilus Trader standard)."""
    ts = parse_utc_timestamp(val)
    return int(ts.as_unit("ns").value)

def to_nanoseconds_array(dt_series_or_index: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Converts a DatetimeIndex or Series of timestamps to an array of uint64 nanoseconds."""
    if isinstance(dt_series_or_index, pd.DatetimeIndex):
        s = dt_series_or_index.to_series()
    else:
        s = dt_series_or_index
    if s.dt.tz is None:
        s = s.dt.tz_localize("UTC")
    else:
        s = s.dt.tz_convert("UTC")
    return s.dt.as_unit("ns").astype("int64").to_numpy(dtype=np.uint64)
