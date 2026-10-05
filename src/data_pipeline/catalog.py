from __future__ import annotations

"""Nautilus Trader ParquetDataCatalog manager for the SSI fetch pipeline."""

import shutil
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.identifiers import InstrumentId
from src.data_pipeline.ssi.models import Dividend
from nautilus_trader.persistence.catalog import ParquetDataCatalog


class DataCatalogManager:
    """Manage a Nautilus ParquetDataCatalog used by fetching and backtesting."""

    def __init__(self, catalog_path: str | Path):
        self.catalog_path = Path(catalog_path).expanduser().resolve()
        self.catalog_path.mkdir(parents=True, exist_ok=True)
        self._catalog = ParquetDataCatalog(str(self.catalog_path))

    @property
    def catalog(self) -> ParquetDataCatalog:
        return self._catalog

    # ------------------------------------------------------------------
    # Instruments
    # ------------------------------------------------------------------

    def save_instrument(self, instrument: Instrument) -> None:
        self._catalog.write_data([instrument])

    def save_instruments(self, instruments: Sequence[Instrument]) -> None:
        items = list(instruments)
        if items:
            self._catalog.write_data(items)

    def get_instruments(self, instrument_type: type | None = None) -> list[Instrument]:
        return self._catalog.instruments(instrument_type=instrument_type)

    def get_instrument(self, instrument_id: str | InstrumentId) -> Instrument | None:
        items = self._catalog.instruments(instrument_ids=[str(instrument_id)])
        return items[0] if items else None

    # ------------------------------------------------------------------
    # OHLCV -> Nautilus Bar
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_datetime_index(df: pd.DataFrame) -> pd.DatetimeIndex:
        if isinstance(df.index, pd.DatetimeIndex):
            index = df.index
        elif "datetime" in df.columns:
            index = pd.to_datetime(df["datetime"], utc=True)
        elif "timestamp" in df.columns:
            values = df["timestamp"]
            if pd.api.types.is_numeric_dtype(values):
                valid = values.dropna()
                sample = abs(float(valid.iloc[0])) if not valid.empty else 0.0
                if sample > 1e17:
                    unit = "ns"
                elif sample > 1e14:
                    unit = "us"
                elif sample > 1e11:
                    unit = "ms"
                else:
                    unit = "s"
                index = pd.to_datetime(values, unit=unit, utc=True)
            else:
                index = pd.to_datetime(values, utc=True)
        else:
            raise ValueError("DataFrame must contain a DatetimeIndex, 'datetime', or 'timestamp'")

        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")

        # BẮT BUỘC trong Pandas 2.0+: ép về nanoseconds trước khi ép sang int64
        if hasattr(index, "as_unit"):
            index = index.as_unit("ns")
        return index

    @staticmethod
    def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize SSI OHLCV into ascending UTC OHLCV."""
        if df.empty:
            empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            empty.index = pd.DatetimeIndex([], name="datetime", tz="UTC")
            return empty

        out = df.copy()
        out.columns = [str(c).strip().lower() for c in out.columns]
        out.index = DataCatalogManager._normalize_datetime_index(out)

        required = ["open", "high", "low", "close"]
        missing = [c for c in required if c not in out.columns]
        if missing:
            raise ValueError(f"Missing required OHLC columns: {missing}")

        if "volume" not in out.columns:
            out["volume"] = 0.0

        for col in ["open", "high", "low", "close", "volume"]:
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = out.dropna(subset=["open", "high", "low", "close", "volume"])
        out = out[~out.index.duplicated(keep="last")].sort_index()

        o = out["open"].to_numpy(dtype=np.float64)
        h = out["high"].to_numpy(dtype=np.float64)
        l = out["low"].to_numpy(dtype=np.float64)
        c = out["close"].to_numpy(dtype=np.float64)
        out["high"] = np.maximum(h, np.maximum(o, c))
        out["low"] = np.minimum(l, np.minimum(o, c))

        return out[["open", "high", "low", "close", "volume"]]

    @staticmethod
    def df_to_bars(
        df: pd.DataFrame,
        bar_type: BarType | str,
        price_precision: int,
        size_precision: int,
        ts_init_delta: int = 0,
    ) -> list[Bar]:
        resolved = BarType.from_str(bar_type) if isinstance(bar_type, str) else bar_type
        cleaned = DataCatalogManager.clean_ohlcv(df)
        if cleaned.empty:
            return []

        ts_events = np.ascontiguousarray(
            cleaned.index.astype("int64").to_numpy(dtype=np.uint64, copy=True)
        )
        ts_inits = ts_events + np.uint64(ts_init_delta)

        arrays = [
            np.ascontiguousarray(cleaned[col].to_numpy(dtype=np.float64, copy=True))
            for col in ["open", "high", "low", "close", "volume"]
        ]

        return Bar.from_raw_arrays_to_list(
            resolved,
            price_precision,
            size_precision,
            *arrays,
            ts_events,
            ts_inits,
        )

    # ------------------------------------------------------------------
    # Bars
    # ------------------------------------------------------------------

    @staticmethod
    def _group_bars(bars: Iterable[Bar]) -> dict[str, list[Bar]]:
        grouped: dict[str, list[Bar]] = {}
        for bar in bars:
            grouped.setdefault(str(bar.bar_type), []).append(bar)
        return grouped

    def _bar_directory(self, bar_type: BarType | str) -> Path:
        # Nautilus 2.x canonical layout is data/bars/<bar_type>/.
        safe = str(bar_type).replace("/", "").replace("^", "_")
        return self.catalog_path / "data" / "bars" / safe

    def _read_existing_bars(self, bar_type: BarType | str) -> list[Bar]:
        try:
            return list(self._catalog.query_bars(bar_types=[str(bar_type)]))
        except (AttributeError, TypeError):
            # Compatibility with older Nautilus versions.
            try:
                return list(self._catalog.bars(bar_types=[str(bar_type)]))
            except Exception:
                return []

    def write_bars(self, bars: Sequence[Bar], *, merge_existing: bool = True) -> None:
        """Persist bars, optionally consolidating overlapping incremental downloads."""
        incoming = list(bars)
        if not incoming:
            return

        for bar_type_str, new_bars in self._group_bars(incoming).items():
            if not merge_existing:
                self._catalog.write_data(sorted(new_bars, key=lambda x: x.ts_init))
                continue

            old_bars = self._read_existing_bars(bar_type_str)
            merged = {int(b.ts_event): b for b in old_bars}
            merged.update({int(b.ts_event): b for b in new_bars})
            merged_bars = [merged[k] for k in sorted(merged)]

            bar_dir = self._bar_directory(bar_type_str)
            if bar_dir.exists():
                shutil.rmtree(bar_dir)

            self._catalog.write_data(merged_bars)

    def write_df(
        self,
        df: pd.DataFrame,
        bar_type: BarType | str,
        instrument: Instrument,
        *,
        merge_existing: bool = True,
        ts_init_delta: int = 0,
    ) -> list[Bar]:
        self.save_instrument(instrument)
        bars = self.df_to_bars(
            df,
            bar_type,
            instrument.price_precision,
            instrument.size_precision,
            ts_init_delta,
        )
        self.write_bars(bars, merge_existing=merge_existing)
        return bars

    @staticmethod
    def _timestamp_to_ns(value: pd.Timestamp | str | int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, np.integer)):
            return int(value)
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        if hasattr(ts, "as_unit"):
            ts = ts.as_unit("ns")
        return int(ts.value)

    def _read_existing_bars(self, bar_type: BarType | str) -> list[Bar]:
        return self.get_bars(bar_type)

    def get_bars(
        self,
        bar_type: BarType | str,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> list[Bar]:
        start_ns = self._timestamp_to_ns(start)
        end_ns = self._timestamp_to_ns(end)
        kwargs = {
            "bar_types": [str(bar_type)],
            "start": start_ns,
            "end": end_ns,
        }
        try:
            bars = list(self._catalog.query_bars(**kwargs))
        except (AttributeError, TypeError):
            bars = list(self._catalog.bars(**kwargs))

        if not bars and (start_ns is not None or end_ns is not None):
            all_bars = self.get_bars(bar_type, start=None, end=None)
            bars = [
                b for b in all_bars
                if (start_ns is None or int(b.ts_init) >= start_ns)
                and (end_ns is None or int(b.ts_init) <= end_ns)
            ]
        return bars

    def get_bar_range(self, bar_type: BarType | str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        bars = self.get_bars(bar_type)
        if not bars:
            return None
        return (
            pd.Timestamp(bars[0].ts_init, unit="ns", tz="UTC"),
            pd.Timestamp(bars[-1].ts_init, unit="ns", tz="UTC"),
        )

    # ------------------------------------------------------------------
    # Dividends
    # ------------------------------------------------------------------

    def save_dividends(self, dividends: Sequence[Dividend]) -> None:
        items = list(dividends)
        if items:
            # Keep compatibility with the current fetcher, which writes Dividend
            # through the generic catalog writer.
            self._catalog.write_data(items)

    def get_dividends(
        self,
        instrument_id: str | InstrumentId | None = None,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> list[Dividend]:
        kwargs: dict[str, object] = {}
        if start is not None:
            kwargs["start"] = self._timestamp_to_ns(start)
        if end is not None:
            kwargs["end"] = self._timestamp_to_ns(end)
        if instrument_id is not None:
            kwargs["identifiers"] = [str(instrument_id)]

        query_dividends = getattr(self._catalog, "query_dividends", None)
        if query_dividends is not None:
            return list(query_dividends(**kwargs))

        dividends = getattr(self._catalog, "dividends", None)
        if dividends is not None:
            return list(dividends(**kwargs))

        raise NotImplementedError(
            "The installed Nautilus version does not expose a typed Dividend query API."
        )

    # ------------------------------------------------------------------
    # Unified persistence / diagnostics
    # ------------------------------------------------------------------

    def save_data(
        self,
        *,
        instruments: Sequence[Instrument] | None = None,
        bars: Sequence[Bar] | None = None,
        dividends: Sequence[Dividend] | None = None,
        merge_bars: bool = True,
    ) -> None:
        if instruments:
            self.save_instruments(instruments)
        if dividends:
            self.save_dividends(dividends)
        if bars:
            self.write_bars(bars, merge_existing=merge_bars)

    def list_bar_types(self) -> list[str]:
        root = self.catalog_path / "data" / "bars"
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir())

    def summary(self) -> dict[str, object]:
        root = self.catalog_path / "data" / "bars"
        return {
            "path": str(self.catalog_path),
            "instrument_count": len(self.get_instruments()),
            "bar_file_count": len(list(root.rglob("*.parquet"))) if root.exists() else 0,
            "bar_types": self.list_bar_types(),
        }
