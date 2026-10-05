import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from src.data_pipeline.economics import (
    EconomicData,
    EconomicFetcher,
    points_to_bars,
)


def main():
    print("=" * 65)
    print("DEMO: EconomicFetcher (Lạm phát & Lợi suất trái phiếu - Nautilus)")
    print("=" * 65)

    with EconomicFetcher(default_country="vietnam") as fetcher:
        # 1. Khám phá các chỉ số kinh tế vĩ mô có sẵn
        print("\n[1] Khám phá danh mục chỉ số vĩ mô cho Việt Nam (TradingEconomics)...")
        indicators_df = fetcher.list_indicators("vietnam")
        print(f"  Tổng số chỉ số tìm thấy: {len(indicators_df)}")
        print("  Mẫu 5 chỉ số tiêu biểu:")
        for _, row in indicators_df.head(5).iterrows():
            print(f"   -> {row['indicator']:<30} | {row['code']:<35} | {row['url']}")

        # 2. Lấy dữ liệu lạm phát Việt Nam (CPI)
        print("\n[2] Lấy dữ liệu lạm phát (Inflation Rate - CPI) Việt Nam (10 năm)...")
        inflation_data = fetcher.fetch_inflation(country="vietnam", span="10Y")
        print(f"  Số điểm dữ liệu lạm phát: {len(inflation_data)}")
        if inflation_data:
            print(f"  Điểm đầu tiên: {inflation_data[0].date} -> {inflation_data[0].value}%")
            print(f"  Điểm mới nhất: {inflation_data[-1].date} -> {inflation_data[-1].value}%")

        # Dạng DataFrame
        inf_df = fetcher.fetch_inflation_df(country="vietnam", span="10Y")
        print("\n  DataFrame lạm phát (phục vụ phân tích / kết hợp factor):")
        print(inf_df[["value", "indicator", "unit"]].tail(4))

        # 3. Lấy dữ liệu lợi suất trái phiếu chính phủ Việt Nam 10 năm
        print("\n[3] Lấy dữ liệu lợi suất trái phiếu chính phủ 10Y Việt Nam (10 năm)...")
        bond_data = fetcher.fetch_bond_yield(country="vietnam", span="10Y")
        print(f"  Số điểm dữ liệu lợi suất: {len(bond_data)}")
        if bond_data:
            print(f"  Lợi suất điểm đầu: {bond_data[0].date} -> {bond_data[0].value}%")
            print(f"  Lợi suất mới nhất: {bond_data[-1].date} -> {bond_data[-1].value}%")

        bond_df = fetcher.fetch_bond_yield_df(country="vietnam", span="10Y")
        print("\n  DataFrame lợi suất trái phiếu:")
        print(bond_df[["value", "indicator", "unit"]].tail(4))

        # 4. Hỗ trợ đa quốc gia: Hoa Kỳ (United States)
        print("\n[4] Kiểm tra tính linh hoạt đa quốc gia: Lạm phát & Lợi suất TPCP Hoa Kỳ...")
        us_inf = fetcher.fetch_inflation(country="us", span="3Y")
        us_bond = fetcher.fetch_bond_yield(country="us", span="3Y")
        print(f"  US Inflation mới nhất ({us_inf[-1].date}): {us_inf[-1].value}%")
        print(f"  US 10Y Bond Yield mới nhất ({us_bond[-1].date}): {us_bond[-1].value}%")

        # 5. Chuyển đổi thành Nautilus Bar objects (khi coi yield/macro như market bars)
        print("\n[5] Chuyển đổi lợi suất TPCP thành chuỗi Bar chuẩn Nautilus Trader...")
        bars = points_to_bars(
            bond_data[-5:],
            bar_type="VNM10Y.MACRO-1-DAY-LAST-EXTERNAL",
            price_precision=4,
        )
        print(f"  Số lượng nến Bar được sinh ra: {len(bars)}")
        for b in bars:
            print(f"   -> {b}")

        # 6. Lưu trữ vào Nautilus ParquetDataCatalog và truy vấn lại
        print("\n[6] Tích hợp lưu trữ vào Nautilus ParquetDataCatalog...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_results = fetcher.fetch_and_catalog(
                country="vietnam",
                indicators=["inflation-cpi", "government-bond-yield"],
                span="3Y",
                catalog_path=tmp_dir,
            )
            print(f"  Đã lưu vào catalog tại: {tmp_dir}")
            for ind, items in catalog_results.items():
                print(f"   -> {ind}: {len(items)} bản ghi")

            # Đọc ngược lại từ ParquetDataCatalog thông qua API chuẩn Nautilus
            cat = ParquetDataCatalog(tmp_dir)
            queried_inf = cat.custom_data(
                cls=EconomicData,
                instrument_ids=["INFLATION_CPI.VIETNAM"],
            )
            queried_yield = cat.custom_data(
                cls=EconomicData,
                instrument_ids=["GOVERNMENT_BOND_YIELD.VIETNAM"],
            )
            all_queried = cat.custom_data(cls=EconomicData)

            print(f"  Truy vấn từ Catalog - Lạm phát: {len(queried_inf)} bản ghi")
            print(f"  Truy vấn từ Catalog - Lợi suất: {len(queried_yield)} bản ghi")
            print(f"  Tổng số bản ghi trong Catalog: {len(all_queried)}")
            assert len(all_queried) == len(queried_inf) + len(queried_yield)
            print("  => Kiểm tra toàn vẹn dữ liệu trong Data Catalog thành công!")

    print("\n" + "=" * 65)
    print("HOÀN THÀNH DEMO EconomicFetcher THÀNH CÔNG!")
    print("=" * 65)


if __name__ == "__main__":
    main()
