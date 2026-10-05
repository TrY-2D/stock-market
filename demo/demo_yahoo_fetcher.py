import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


from src.data_pipeline.yahoo import YahooFinanceFetcher
from src.utils import plot_series_groups

def main() -> None:
    print("=" * 70)
    print("DEMO: YahooFinanceFetcher tích hợp toàn diện với Nautilus Trader")
    print("=" * 70)

    with YahooFinanceFetcher() as fx_fetcher:
        # 1. Lấy toàn bộ lịch sử tỷ giá USD/VND và EUR/USD (DataFrame)
        df_usdvnd = fx_fetcher.get_ohlcv("EUR/USD", interval="1d", start_date="2000-01-01")
        print(df_usdvnd.tail())

        plot_series_groups(
            [
                [df_usdvnd["open"], df_usdvnd["high"], df_usdvnd["low"], df_usdvnd["close"]]
            ],
            x=df_usdvnd.index.to_series()
        )

        # 2. Lấy hàng loạt các cặp Forex & DXY phục vụ mô hình vĩ mô
        df_fx_all = fx_fetcher.fetch_all_ohlcv(
            symbols=["USD/VND", "EUR/USD", "USD/JPY", "USD/CNY", "DXY"],
            interval="1d",
            start_date="2020-01-01",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            # 3. Lưu trực tiếp CurrencyPair + OHLCV Bars vào Nautilus ParquetDataCatalog
            pairs, bars = fx_fetcher.fetch_and_catalog(
                symbols=["EUR/USD", "USD/VND", "USD/JPY"],
                interval="1d",
                start_date="2020-01-01",
                catalog_path=tmp_dir
            )

if __name__ == "__main__":
    main()