from __future__ import annotations

from typing import Final

# Base URLs
IBOARD_QUERY_BASE_URL: Final[str] = "https://iboard-query.ssi.com.vn"
IBOARD_API_BASE_URL: Final[str] = "https://iboard-api.ssi.com.vn"

# Endpoints
STOCK_INFO_ENDPOINT: Final[str] = "/stock/stock-info"
COMPANY_PROFILE_ENDPOINT: Final[str] = "/statistics/company/ssmi/company-profile"
CAP_AND_DIVIDEND_ENDPOINT: Final[str] = "/statistics/company/ssmi/cap-and-dividend"
CORPORATE_ACTIONS_ENDPOINT: Final[str] = "/statistics/company/ssmi/corporate-actions"
FINANCE_INDICATOR_ENDPOINT: Final[str] = "/statistics/company/ssmi/finance-indicator"
SECTORS_DATA_ENDPOINT: Final[str] = "/statistics/company/sectors-data"

# Networking defaults
DEFAULT_TIMEOUT: Final[float] = 10.0
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_BACKOFF_FACTOR: Final[float] = 0.5
RETRY_STATUS_CODES: Final[tuple[int, ...]] = (429, 500, 502, 503, 504)

DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "application/json",
}

# Industry mapping for Vietnamese markets
INDUSTRY_MAP: Final[dict[str, str]] = {
    "Dầu khí": "OILGAS",
    "Hóa chất": "CHEM",
    "Tài nguyên Cơ bản": "BASICRES",
    "Xây dựng và Vật liệu": "CONSMAT",
    "Hàng & Dịch vụ Công nghiệp": "INDGOODS",
    "Ô tô và phụ tùng": "AUTOPARTS",
    "Thực phẩm và đồ uống": "FOODBEV",
    "Hàng cá nhân & Gia dụng": "PERSONAL",
    "Y tế": "HEALTH",
    "Bán lẻ": "RETAIL",
    "Truyền thông": "MEDIA",
    "Du lịch và Giải trí": "TRAVEL",
    "Viễn thông": "TELECOM",
    "Điện, nước & xăng dầu khí đốt": "UTIL",
    "Ngân hàng": "BANKS",
    "Bảo hiểm": "INSUR",
    "Bất động sản": "REAL",
    "Dịch vụ tài chính": "FIN",
    "Công nghệ Thông tin": "TECH",
}
