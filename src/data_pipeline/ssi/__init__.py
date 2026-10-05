from src.data_pipeline.ssi.fetcher import INTERVAL_LOOKUP, SSIFetcher
from src.data_pipeline.ssi.models import (
    CompanyListingInfo,
    Dividend,
    calculate_price_increment,
)

# Drop-in alias for backward compatibility with old TradingviewFetcher imports
TradingviewFetcher = SSIFetcher

__all__ = [
    "CompanyListingInfo",
    "Dividend",
    "INTERVAL_LOOKUP",
    "SSIFetcher",
    "TradingviewFetcher",
    "calculate_price_increment",
]