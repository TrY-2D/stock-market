import os
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.tradingview import TradingviewFetcher


def main():
    print("=" * 60)
    print("DEMO: TradingviewFetcher với Nautilus Trader")
    print("=" * 60)

    fetcher = TradingviewFetcher(
        default_venue="HOSE",
        default_currency="VND",
        default_price_precision=2,
        default_size_precision=0,
    )

    # 1. Tìm kiếm mã cổ phiếu
    print("\n[1] Tìm kiếm mã cổ phiếu 'VCB' trên HOSE...")
    search_results = fetcher.search_symbol(query="VCB", country="VN", limit=3)
    for res in search_results:
        print(f"  -> {res.get('symbol')} | {res.get('exchange')} | {res.get('description')}")

    # 2. Khởi tạo Instrument mô hình Equity
    print("\n[2] Khởi tạo mô hình Instrument chuẩn Nautilus Trader (Equity)...")
    equity = fetcher.create_equity(
        symbol="VCB",
        venue="HOSE",
        currency="VND",
        price_increment=100.0,
        lot_size=100.0,
    )
    print(f"  Equity ID: {equity.id}")
    print(f"  Asset Class: {equity.asset_class}")
    print(f"  Quote Currency: {equity.quote_currency}")
    print(f"  Tick Size (price_increment): {equity.price_increment}")
    print(f"  Lot Size: {equity.lot_size}")

    # 3. Tạo BarType theo tiêu chuẩn Nautilus
    print("\n[3] Khởi tạo BarType chuẩn Nautilus Trader...")
    bar_type_1d = fetcher.get_bar_type(equity, interval="1d")
    print(f"  BarType (1d): {bar_type_1d}")

    # 4. Tải dữ liệu và chuyển đổi thành Bar
    print("\n[4] Tải dữ liệu OHLCV và chuyển đổi thành list[Bar] của Nautilus...")
    bars = fetcher.fetch_bars(
        symbol="VCB",
        exchange="HOSE",
        interval="1d",
        instrument=equity,
        bar_type=bar_type_1d,
    )
    print(f"  Tổng số nến Bar đã tải: {len(bars)}")
    if bars:
        print(f"  Bar đầu tiên: {bars[0]}")
        print(f"  Bar mới nhất: {bars[-1]}")

    # 5. Lưu vào ParquetDataCatalog và truy vấn lại
    print("\n[5] Tích hợp với Nautilus ParquetDataCatalog...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        catalog = fetcher.save_to_catalog(
            bars=bars,
            instruments=[equity],
            catalog_path=tmp_dir,
        )
        print(f"  Đã lưu dữ liệu vào Data Catalog tại: {tmp_dir}")

        # Đọc ngược lại từ catalog thông qua API chuẩn của Nautilus Trader
        queried_instruments = catalog.instruments(instrument_ids=[str(equity.id)])
        queried_bars = catalog.bars(bar_types=[str(bar_type_1d)])

        print(f"  Truy vấn từ Catalog - Số instruments: {len(queried_instruments)}")
        print(f"  Truy vấn từ Catalog - Số bars: {len(queried_bars)}")
        assert len(queried_bars) == len(bars)
        print("  => Kiểm tra toàn vẹn dữ liệu thành công!")

    print("\n" + "=" * 60)
    print("HOÀN THÀNH DEMO THÀNH CÔNG!")
    print("=" * 60)


if __name__ == "__main__":
    main()
