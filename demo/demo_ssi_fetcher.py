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


def main():
    print("=" * 60)
    print("DEMO: SSIFetcher tích hợp Nautilus Trader")
    print("=" * 60)

    with SSIFetcher() as fetcher:
        # 1. Danh sách doanh nghiệp niêm yết
        print("\n[1] Lấy danh sách doanh nghiệp niêm yết trên HOSE...")
        hose_companies = fetcher.get_listed_companies(exchange="HOSE")
        print(f"  Tổng số cổ phiếu niêm yết trên HOSE: {len(hose_companies)}")
        print("  Mẫu 3 mã đầu tiên:")
        for _, row in hose_companies.head(3).iterrows():
            print(f"   -> {row['symbol']} | {row['exchange']} | {row['company_name']} | ISIN: {row['isin']}")

        # 2. Thông tin niêm yết chi tiết
        print("\n[2] Lấy thông tin niêm yết chi tiết cho mã 'VCB'...")
        info = fetcher.get_listing_info("VCB")
        print(f"  Mã: {info.symbol} | Sàn: {info.exchange}")
        print(f"  Tên doanh nghiệp: {info.company_name}")
        print(f"  Ngày niêm yết: {info.listing_date}")
        print(f"  Số lượng CP niêm yết: {info.issue_shares:,.0f} CP" if info.issue_shares else "  N/A")
        print(f"  Số lượng CP lưu hành: {info.circulating_shares:,.0f} CP" if info.circulating_shares else "  N/A")
        print(f"  Vốn điều lệ: {info.charter_capital:,.0f} VND" if info.charter_capital else "  N/A")
        print(f"  Giá chào sàn (first price): {info.first_price:,.0f} VND" if info.first_price else "  N/A")
        print(f"  Ngành nghề: {info.industry_name} ({info.sector})")

        # 3. Chuyển đổi thành Nautilus Equity Model
        print("\n[3] Khởi tạo Nautilus Trader Equity Instrument...")
        equity = fetcher.create_equity("VCB", listing_info=info, current_price=57500.0)
        print(f"  Instrument ID: {equity.id}")
        print(f"  Asset Class: {equity.asset_class}")
        print(f"  Quote Currency: {equity.quote_currency}")
        print(f"  Bước giá (price_increment): {equity.price_increment}")
        print(f"  Lô chuẩn (lot_size): {equity.lot_size}")
        print(f"  Listing Date (ts_event): {equity.ts_event} ns")
        print(f"  ISIN: {equity.isin}")
        print(f"  Metadata fields trong equity.info: {len(equity.info)} trường")

        # 4. Lịch sử chi trả cổ tức bằng tiền
        print("\n[4] Lấy lịch sử chi trả cổ tức bằng tiền cho 'VCB'...")
        dividends = fetcher.get_cash_dividends("VCB")
        print(f"  Tổng số đợt chi trả cổ tức tìm thấy: {len(dividends)}")
        for d in dividends[:5]:
            print(f"   -> Năm {d.fiscal_year} | Ngày GDKHQ: {d.ex_date} | Cổ tức: {d.amount:,.0f} VND/CP ({d.ratio*100:.1f}%) | Ngày TT: {d.payment_date}")

        div_df = fetcher.get_cash_dividends_df("VCB")
        print(f"\n  Định dạng DataFrame cổ tức (phục vụ backtesting/yield):")
        print(div_df[["amount", "fiscal_year", "ex_date", "payment_date"]].head(4))

        # 5. Lưu trữ và kiểm tra toàn vẹn trên Nautilus ParquetDataCatalog
        print("\n[5] Lưu trữ vào Nautilus ParquetDataCatalog...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetcher.save_to_catalog(
                instruments=[equity],
                dividends=dividends,
                catalog_path=tmp_dir,
            )
            print(f"  Đã lưu Equity và {len(dividends)} sự kiện cổ tức vào: {tmp_dir}")

            cat = ParquetDataCatalog(tmp_dir)
            queried_equities = cat.instruments(instrument_ids=[str(equity.id)])
            queried_dividends = cat.custom_data(cls=Dividend)

            print(f"  Truy vấn từ Catalog - Instruments: {len(queried_equities)}")
            print(f"  Truy vấn từ Catalog - Dividends: {len(queried_dividends)}")
            assert len(queried_equities) == 1
            assert len(queried_dividends) == len(dividends)
            print("  => Kiểm tra toàn vẹn dữ liệu thành công!")

    print("\n" + "=" * 60)
    print("DEMO SSIFetcher HOÀN TẤT THÀNH CÔNG!")
    print("=" * 60)


if __name__ == "__main__":
    main()
