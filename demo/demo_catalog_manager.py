from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import pandas as pd

from nautilus_trader.model.data import Bar
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from src.data_pipeline.ssi.fetcher import SSIFetcher
from src.data_pipeline.catalog import DataCatalogManager


SYMBOL = "FPT"
INTERVAL = "1d"
START_DATE = "2025-04-01"
END_DATE = "2025-07-31"


def main():
    print("=" * 70)
    print("DEMO: DataCatalogManager - SSI -> Nautilus ParquetDataCatalog")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Khởi tạo SSI Fetcher
    # ------------------------------------------------------------------
    print("\n[1] Khởi tạo SSIFetcher...")

    with SSIFetcher() as fetcher:

        # --------------------------------------------------------------
        # 2. Tạo Equity Instrument
        # --------------------------------------------------------------
        print(f"\n[2] Tạo Nautilus Equity Instrument cho {SYMBOL}...")

        instrument = fetcher.create_equity(
            symbol=SYMBOL,
            fetch_profile=False,
        )

        print(f"  Instrument ID : {instrument.id}")
        print(f"  Raw symbol    : {instrument.raw_symbol}")
        print(f"  Currency      : {instrument.get_settlement_currency()}")
        print(f"  Price precision: {instrument.price_precision}")
        print(f"  Size precision : {instrument.size_precision}")

        # BarType chuẩn của Nautilus
        bar_type = fetcher.get_bar_type(
            instrument=instrument,
            interval=INTERVAL,
        )

        print(f"  BarType       : {bar_type}")

        # --------------------------------------------------------------
        # 3. Fetch OHLCV từ SSI
        # --------------------------------------------------------------
        print(
            f"\n[3] Fetch OHLCV {SYMBOL} "
            f"({START_DATE} -> {END_DATE})..."
        )

        bars = fetcher.fetch_bars(
            symbol=SYMBOL,
            instrument=instrument,
            interval=INTERVAL,
            start_date=START_DATE,
            end_date=END_DATE,
        )

        print(f"  Số lượng Bar nhận được: {len(bars)}")

        if not bars:
            raise RuntimeError("SSI không trả về dữ liệu OHLCV.")

        print("  5 Bar đầu tiên:")
        for bar in bars[:5]:
            print(f"   -> {bar}")

        print("  Bar cuối:")
        print(f"   -> {bars[-1]}")

        # --------------------------------------------------------------
        # 4. Tạo DataFrame từ SSI để kiểm tra clean_ohlcv()
        # --------------------------------------------------------------
        print("\n[4] Kiểm tra dữ liệu OHLCV dạng DataFrame...")

        df = fetcher.fetch_df(
            symbol=SYMBOL,
            exchange=instrument.venue.value,
            interval=INTERVAL,
            start_date=START_DATE,
            end_date=END_DATE,
        )

        print(f"  DataFrame shape: {df.shape}")
        print(f"  Columns        : {list(df.columns)}")
        print("\n  5 dòng cuối:")
        print(df[["open", "high", "low", "close", "volume"]].tail())

        # --------------------------------------------------------------
        # 5. Lưu vào DataCatalogManager
        # --------------------------------------------------------------
        print("\n[5] Ghi Instrument + OHLCV vào DataCatalog...")

        with tempfile.TemporaryDirectory() as tmp_dir:

            print(f"  Catalog path: {tmp_dir}")

            manager = DataCatalogManager(tmp_dir)

            manager.write_df(
                df=df,
                bar_type=bar_type,
                instrument=instrument,
                merge_existing=True,
            )

            print("  => Ghi dữ liệu thành công.")

            # ----------------------------------------------------------
            # 6. Kiểm tra summary
            # ----------------------------------------------------------
            print("\n[6] Kiểm tra Catalog summary...")

            summary = manager.summary()

            for key, value in summary.items():
                print(f"  {key:<18}: {value}")

            # ----------------------------------------------------------
            # 7. Đọc Instrument từ Catalog
            # ----------------------------------------------------------
            print("\n[7] Đọc Instrument ngược lại từ Catalog...")

            loaded_instrument = manager.get_instrument(
                instrument.id
            )

            if loaded_instrument is None:
                raise RuntimeError(
                    f"Không tìm thấy Instrument {instrument.id}"
                )

            print(f"  Instrument đọc lại: {loaded_instrument.id}")
            print(
                f"  Currency          : "
                f"{loaded_instrument.get_settlement_currency()}"
            )
            print(
                f"  Price precision   : "
                f"{loaded_instrument.price_precision}"
            )

            assert str(loaded_instrument.id) == str(instrument.id)

            # ----------------------------------------------------------
            # 8. Đọc Bars từ Catalog
            # ----------------------------------------------------------
            print("\n[8] Đọc OHLCV Bars từ Catalog...")

            loaded_bars = manager.get_bars(bar_type)

            print(f"  Số Bar đọc lại: {len(loaded_bars)}")

            if not loaded_bars:
                raise RuntimeError("Không đọc được Bars từ Catalog.")

            print("  3 Bar cuối:")
            for bar in loaded_bars[-3:]:
                print(f"   -> {bar}")

            assert len(loaded_bars) == len(bars)

            # ----------------------------------------------------------
            # 9. Kiểm tra khoảng thời gian
            # ----------------------------------------------------------
            print("\n[9] Kiểm tra thời gian của Bar data...")

            bar_range = manager.get_bar_range(bar_type)

            if bar_range is None:
                raise RuntimeError("Không xác định được bar range.")

            first_ts, last_ts = bar_range

            print(f"  First bar: {first_ts}")
            print(f"  Last bar : {last_ts}")

            assert first_ts <= last_ts

            # ----------------------------------------------------------
            # 10. Kiểm tra query theo thời gian
            # ----------------------------------------------------------
            print("\n[10] Query Bars theo khoảng thời gian...")

            query_start = pd.Timestamp(START_DATE, tz="UTC")
            query_end = pd.Timestamp(END_DATE, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)

            queried_bars = manager.get_bars(
                bar_type=bar_type,
                start=query_start,
                end=query_end,
            )

            print(
                f"  Số Bar trong khoảng "
                f"{START_DATE} -> {END_DATE}: "
                f"{len(queried_bars)}"
            )

            assert len(queried_bars) > 0

            # ----------------------------------------------------------
            # 11. Kiểm tra upsert / merge
            # ----------------------------------------------------------
            print("\n[11] Kiểm tra cơ chế merge/upsert...")

            # Ghi lại một phần dữ liệu cũ.
            # Nếu catalog manager hoạt động đúng thì không bị duplicate.
            partial_bars = bars[-10:]

            manager.write_bars(
                partial_bars,
                merge_existing=True,
            )

            merged_bars = manager.get_bars(bar_type)

            print(f"  Bar trước khi ghi lại : {len(loaded_bars)}")
            print(f"  Bar sau khi ghi lại   : {len(merged_bars)}")

            assert len(merged_bars) == len(loaded_bars)

            print(
                "  => Ghi lại dữ liệu không tạo duplicate."
            )

            # ----------------------------------------------------------
            # 12. Kiểm tra trực tiếp bằng ParquetDataCatalog
            # ----------------------------------------------------------
            print("\n[12] Kiểm tra bằng API gốc của Nautilus...")

            cat = ParquetDataCatalog(tmp_dir)

            catalog_instruments = cat.instruments(
                instrument_ids=[str(instrument.id)]
            )

            catalog_bars = cat.bars(
                bar_types=[str(bar_type)]
            )

            print(
                f"  Instruments trong Nautilus Catalog: "
                f"{len(catalog_instruments)}"
            )

            print(
                f"  Bars trong Nautilus Catalog       : "
                f"{len(catalog_bars)}"
            )

            assert len(catalog_instruments) == 1
            assert len(catalog_bars) == len(merged_bars)

            # ----------------------------------------------------------
            # 13. Kiểm tra cấu trúc file
            # ----------------------------------------------------------
            print("\n[13] Cấu trúc Catalog...")

            catalog_root = Path(tmp_dir)

            for path in sorted(
                catalog_root.rglob("*.parquet")
            ):
                print(
                    "   ->",
                    path.relative_to(catalog_root),
                )

            # ----------------------------------------------------------
            # 14. Kết luận
            # ----------------------------------------------------------
            print("\n[14] Kiểm tra toàn vẹn dữ liệu...")

            assert loaded_instrument.id == instrument.id
            assert len(loaded_bars) > 0
            assert len(merged_bars) == len(loaded_bars)
            assert len(catalog_bars) == len(merged_bars)

            print(
                "  => Instrument: OK"
            )
            print(
                "  => OHLCV Bars: OK"
            )
            print(
                "  => Query theo thời gian: OK"
            )
            print(
                "  => Merge/Upsert: OK"
            )
            print(
                "  => Nautilus Catalog API: OK"
            )

    print("\n" + "=" * 70)
    print("HOÀN THÀNH DEMO DataCatalogManager THÀNH CÔNG!")
    print("=" * 70)


if __name__ == "__main__":
    main()
