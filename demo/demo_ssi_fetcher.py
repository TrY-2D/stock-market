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
        # 1. Danh sách doanh nghiệp niêm yết
        # ---------------------------------------------------------------------
        print("\n[1] Lấy danh sách doanh nghiệp niêm yết trên HOSE...")
        hose_companies = fetcher.get_listed_companies(exchange="HOSE")
        print(f"  Tổng số cổ phiếu niêm yết trên HOSE: {len(hose_companies)}")
        print("  Mẫu 3 mã đầu tiên:")
        for _, row in hose_companies.head(3).iterrows():
            print(
                f"   -> {row['symbol']} | {row['exchange']} | "
                f"{row['company_name']} | ISIN: {row['isin']}"
            )

        # ---------------------------------------------------------------------
        # 2. Thông tin niêm yết chi tiết
        # ---------------------------------------------------------------------
        print("\n[2] Lấy thông tin niêm yết chi tiết cho mã 'VCB'...")
        info = fetcher.get_listing_info("VCB")
        print(f"  Mã: {info.symbol} | Sàn: {info.exchange}")
        print(f"  Tên doanh nghiệp: {info.company_name}")
        print(f"  Ngày niêm yết: {info.listing_date}")
        print(
            f"  Số lượng CP phát hành: {info.issue_shares:,.0f} CP"
            if info.issue_shares
            else "  Số lượng CP phát hành: N/A"
        )
        print(
            f"  Số lượng CP lưu hành: {info.circulating_shares:,.0f} CP"
            if info.circulating_shares
            else "  Số lượng CP lưu hành: N/A"
        )
        print(
            f"  Vốn điều lệ: {info.charter_capital:,.0f} VND"
            if info.charter_capital
            else "  Vốn điều lệ: N/A"
        )
        print(
            f"  Giá chào sàn (first price): {info.first_price:,.0f} VND"
            if info.first_price
            else "  Giá chào sàn: N/A"
        )
        print(f"  Ngành nghề: {info.industry_name} ({info.sector})")

        # ---------------------------------------------------------------------
        # 3. Chuyển đổi thành Nautilus Equity Instrument
        # ---------------------------------------------------------------------
        print("\n[3] Khởi tạo Nautilus Trader Equity Instrument...")
        current_vcb_price = 57500.0
        equity = fetcher.create_equity("VCB", listing_info=info, current_price=current_vcb_price)
        print(f"  Instrument ID: {equity.id}")
        print(f"  Asset Class: {equity.asset_class}")
        print(f"  Quote Currency: {equity.quote_currency}")
        print(
            f"  Bước giá (price_increment): {equity.price_increment} "
            f"(Chuẩn HOSE tại mức giá {current_vcb_price:,.0f}: {calculate_price_increment(current_vcb_price, 'HOSE'):,.0f} VND)"
        )
        print(f"  Lô chuẩn (lot_size): {equity.lot_size}")
        print(f"  Listing Date (ts_event): {equity.ts_event} ns")
        print(f"  ISIN: {equity.isin}")
        print(f"  Metadata fields trong equity.info: {len(equity.info)} trường")

        # ---------------------------------------------------------------------
        # 4. Lịch sử chi trả cổ tức bằng tiền
        # ---------------------------------------------------------------------
        print("\n[4] Lấy lịch sử chi trả cổ tức bằng tiền cho 'VCB'...")
        dividends = fetcher.get_cash_dividends("VCB", exchange=info.exchange)
        print(f"  Tổng số đợt chi trả cổ tức tìm thấy: {len(dividends)}")
        for d in dividends[:5]:
            print(
                f"   -> Năm {d.fiscal_year} | Ngày GDKHQ: {d.ex_date} | "
                f"Cổ tức: {d.amount:,.0f} VND/CP ({d.ratio * 100:.1f}%) | Ngày TT: {d.payment_date}"
            )

        div_df = fetcher.get_cash_dividends_df("VCB", exchange=info.exchange)
        print("\n  Định dạng DataFrame cổ tức (4 dòng đầu):")
        if not div_df.empty:
            print(div_df[["amount", "fiscal_year", "ex_date", "payment_date"]].head(4))

        # ---------------------------------------------------------------------
        # 5. Lấy toàn bộ lịch sử OHLCV (DataFrame & Nautilus Bar)
        # ---------------------------------------------------------------------
        print("\n[5] Lấy toàn bộ lịch sử OHLCV của 'HPG' (từ khi niêm yết đến nay)...")
        df_hpg = fetcher.get_ohlcv("HPG", interval="1d")
        print(f"  Tổng số phiên giao dịch của HPG: {len(df_hpg):,} phiên")
        if not df_hpg.empty:
            print(f"  Từ ngày: {df_hpg.index.min()} -> Đến ngày: {df_hpg.index.max()}")
            print("  5 phiên gần nhất:")
            print(df_hpg.tail(5))

        hpg_bars = fetcher.fetch_bars("HPG", exchange="HOSE", interval="1d")
        print(f"  Chuyển đổi sang Nautilus Bar thành công: {len(hpg_bars):,} bars")
        if hpg_bars:
            print(f"  Mẫu Bar cuối cùng: {hpg_bars[-1]}")

        # ---------------------------------------------------------------------
        # 6. Lấy lịch sử OHLCV hàng loạt (Batch OHLCV)
        # ---------------------------------------------------------------------
        bank_symbols = ["VCB", "ACB", "MBB", "TCB", "VIB"]
        print(f"\n[6] Lấy toàn bộ lịch sử OHLCV hàng loạt cho nhóm Ngân hàng {bank_symbols}...")
        df_bank = fetcher.fetch_all_ohlcv(symbols=bank_symbols, interval="1d")
        print(f"  Tổng số dòng dữ liệu OHLCV thu thập được: {len(df_bank):,} dòng")
        if not df_bank.empty:
            counts_by_sym = df_bank.groupby("symbol").size().to_dict()
            print(f"  Số phiên theo từng mã: {counts_by_sym}")
            print(df_bank.tail(5))

        # ---------------------------------------------------------------------
        # 7. Lưu trữ & Kiểm tra toàn vẹn End-to-End trên ParquetDataCatalog
        # ---------------------------------------------------------------------
        target_symbols = ["HPG", "FPT", "ACB"]
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

    print("\n" + "=" * 70)
    print("DEMO SSIFetcher HOÀN TẤT THÀNH CÔNG!")
    print("=" * 70)


if __name__ == "__main__":
    main()