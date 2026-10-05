import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.ssi import (
    Dividend,
    SSIFetcher,
    calculate_price_increment,
)

def main() -> None:
    print("=" * 70)
    print("DEMO: SSIFetcher tích hợp toàn diện với Nautilus Trader")
    print("=" * 70)

    with SSIFetcher() as fetcher:
        # ---------------------------------------------------------------------
        # 7. Lưu trữ & Kiểm tra toàn vẹn End-to-End trên ParquetDataCatalog
        # ---------------------------------------------------------------------
        target_symbols = ["SZC"]
        print(f"\n[7] Chạy pipeline fetch_and_catalog trọn bộ cho {target_symbols}...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            equities, all_divs, all_bars = fetcher.fetch_and_catalog(
                symbols=target_symbols,
                interval="1d",
                include_bars=True,
                include_dividends=True,
                catalog_path=tmp_dir,
            )
            print(
                f"  Đã lưu {len(equities)} mã Equity, {len(all_divs)} sự kiện cổ tức, "
                f"và {len(all_bars):,} nến OHLCV vào Catalog: {tmp_dir}"
            )

            # Kiểm tra truy vấn ngược từ ParquetDataCatalog
            cat = ParquetDataCatalog(tmp_dir)
            queried_equities = cat.instruments()
            queried_dividends = cat.custom_data(cls=Dividend)
            queried_bars = cat.bars()

            print(f"  Truy vấn từ Catalog -> Instruments : {len(queried_equities)}")
            print(f"  Truy vấn từ Catalog -> Dividends   : {len(queried_dividends)}")
            print(f"  Truy vấn từ Catalog -> OHLCV Bars  : {len(queried_bars):,}")

            assert len(queried_equities) == len(equities), "Lỗi số lượng Instruments!"
            assert len(queried_dividends) == len(all_divs), "Lỗi số lượng Dividends!"
            assert len(queried_bars) == len(all_bars), "Lỗi số lượng OHLCV Bars!"
            print("  => Kiểm tra toàn vẹn dữ liệu (Instruments + Dividends + Bars) THÀNH CÔNG!")

if __name__ == "__main__":
    main()