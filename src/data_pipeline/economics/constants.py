from __future__ import annotations

import os
from typing import Final

# Base URLs
HOME_URL: Final[str] = "https://tradingeconomics.com"
DATASOURCE_BASE_URL: Final[str] = "https://d3ii0wo49og5mi.cloudfront.net"

# Networking defaults
DEFAULT_TIMEOUT: Final[float] = 15.0
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_BACKOFF_FACTOR: Final[float] = 0.5
RETRY_STATUS_CODES: Final[tuple[int, ...]] = (429, 500, 502, 503, 504)

DEFAULT_LOCALE: Final[str] = os.getenv("TRADING_ECONOMICS_LOCALE", "en-US")
DEFAULT_USER_AGENT: Final[str] = os.getenv(
    "TRADING_ECONOMICS_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
)

DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": f"{DEFAULT_LOCALE},en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://tradingeconomics.com/matrix",
}

# API Credentials & Deobfuscation defaults
DEFAULT_CHARTS_TOKEN: Final[str] = "20260324:loboantunes"
DEFAULT_OBFUSCATION_KEY: Final[bytes] = b"tradingeconomics-charts-core-api-key"

# Domain defaults
DEFAULT_COUNTRY: Final[str] = "vietnam"
DEFAULT_SPAN: Final[str] = "10Y"

# Country name normalizations
COUNTRY_ALIASES: Final[dict[str, str]] = {
    "vn": "vietnam",
    "vietnam": "vietnam",
    "việt nam": "vietnam",
    "us": "united-states",
    "usa": "united-states",
    "united states": "united-states",
    "united-states": "united-states",
    "uk": "united-kingdom",
    "united kingdom": "united-kingdom",
    "united-kingdom": "united-kingdom",
    "jp": "japan",
    "japan": "japan",
    "cn": "china",
    "china": "china",
    "de": "germany",
    "germany": "germany",
    "sg": "singapore",
    "singapore": "singapore",
    "th": "thailand",
    "thailand": "thailand",
}

# Standard economic indicator slugs on TradingEconomics
INFLATION_INDICATOR: Final[str] = "inflation-cpi"
CORE_INFLATION_INDICATOR: Final[str] = "core-inflation-rate"
BOND_YIELD_INDICATOR: Final[str] = "government-bond-yield"
INTEREST_RATE_INDICATOR: Final[str] = "interest-rate"
GDP_GROWTH_INDICATOR: Final[str] = "gdp-growth-annual"
UNEMPLOYMENT_INDICATOR: Final[str] = "unemployment-rate"

# Indicator query aliases
INDICATOR_ALIASES: Final[dict[str, str]] = {
    # Inflation
    "inflation": INFLATION_INDICATOR,
    "inflation-rate": INFLATION_INDICATOR,
    "inflation_rate": INFLATION_INDICATOR,
    "cpi": INFLATION_INDICATOR,
    "inflation-cpi": INFLATION_INDICATOR,
    "inflation_cpi": INFLATION_INDICATOR,
    "core-inflation": CORE_INFLATION_INDICATOR,
    "core_inflation": CORE_INFLATION_INDICATOR,
    "core-inflation-rate": CORE_INFLATION_INDICATOR,
    # Bond yields
    "bond-yield": BOND_YIELD_INDICATOR,
    "bond_yield": BOND_YIELD_INDICATOR,
    "government-bond-yield": BOND_YIELD_INDICATOR,
    "government_bond_yield": BOND_YIELD_INDICATOR,
    "gov-bond-yield": BOND_YIELD_INDICATOR,
    "yield": BOND_YIELD_INDICATOR,
    "10y-bond": BOND_YIELD_INDICATOR,
    # Interest rate
    "interest-rate": INTEREST_RATE_INDICATOR,
    "interest_rate": INTEREST_RATE_INDICATOR,
    "rate": INTEREST_RATE_INDICATOR,
    # GDP
    "gdp": GDP_GROWTH_INDICATOR,
    "gdp-growth": GDP_GROWTH_INDICATOR,
    "gdp-growth-annual": GDP_GROWTH_INDICATOR,
    # Unemployment
    "unemployment": UNEMPLOYMENT_INDICATOR,
    "unemployment-rate": UNEMPLOYMENT_INDICATOR,
}

# Ignored features when parsing country indicator index
FEATS_IGNORED: Final[set[str]] = {
    "calendar",
    "forecast",
    "news",
    "indicators",
    "matrix",
    "stream",
}
