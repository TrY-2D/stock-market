from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class SymbolListResponse(BaseModel):
    symbols: list[str]


class BacktestRunRequest(BaseModel):
    symbol: str = "FPT"
    start_date: str = "2021-01-01"
    end_date: str = "2024-07-31"
    initial_cash: float = Field(default=1_000_000_000.0, description="Vốn ban đầu VNĐ")
    base_nav_pct: float = Field(default=0.04, description="Tỷ trọng cơ sở N% cho factor Fibonacci = 1")
    lot_size: int = Field(default=100, description="Kích thước lô giao dịch tối thiểu")
    window: int = Field(default=30, description="Cửa sổ trượt mặc định")
    linear_window: int = Field(default=30, ge=5, le=300, description="Độ dài đường hồi quy tuyến tính (LRC)")
    sma_window: int = Field(default=30, ge=5, le=300, description="Độ dài đường SMA thống kê")
    beta_window: int = Field(default=30, ge=5, le=300, description="Độ dài cửa sổ hồi quy đa biến Beta")
    z_score_window: int = Field(default=120, ge=10, le=500, description="Độ dài cửa sổ chuẩn hóa Z-Score")
    sma20_period: int = Field(default=20, ge=2, le=100, description="Chu kỳ SMA bộ lọc xu hướng")
    atr_period: int = Field(default=14, ge=2, le=50, description="Chu kỳ ATR")
    atr_multiplier: float = Field(default=1.0, ge=0.1, le=5.0, description="Hệ số nhân ATR cho Vùng Mua/Bán (+/- N ATR)")
    min_theses: int = Field(default=3, ge=1, le=5, description="Số luận điểm tối thiểu để kích hoạt Mua (1-5)")
    expanding: bool = Field(default=False, description="Sử dụng cửa sổ mở rộng expanding (không giới hạn window)")
    all_history: bool = Field(default=False, description="Backtest toàn bộ dữ liệu lịch sử (từ năm 2000 đến nay)")
    use_synthetic: bool = Field(default=False, description="Sử dụng dữ liệu giả lập chuẩn hóa")
    engine_type: str = Field(default="nautilus", description="Nền tảng backtest: 'nautilus' hoặc 'direct'")


class CandleBar(BaseModel):
    time: int  # Unix timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float


class LinePoint(BaseModel):
    time: int
    value: float


class ChartMarker(BaseModel):
    time: int
    position: str  # 'aboveBar' | 'belowBar'
    color: str
    shape: str     # 'arrowUp' | 'arrowDown' | 'circle' | 'square'
    text: str
    size: int = 1


class TradeItem(BaseModel):
    trade_id: int
    date: str
    action: str  # 'BUY' | 'SELL'
    price: float
    shares: int
    amount: float
    fee_tax: float
    factor: int
    theses_count: int
    reason: str
    nav: float


class BacktestSummaryMetrics(BaseModel):
    initial_nav: float
    final_nav: float
    total_return_pct: float
    cagr_pct: float
    benchmark_return_pct: float
    alpha_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    buy_trades: int
    sell_trades: int


class BacktestRunResponse(BaseModel):
    symbol: str
    engine: str
    summary: BacktestSummaryMetrics
    candles: list[CandleBar]
    p_suggest: list[LinePoint]
    buy_threshold: list[LinePoint]
    sell_threshold: list[LinePoint]
    sma20: list[LinePoint]
    expected_return: list[LinePoint]
    pqr_series: list[LinePoint] = []
    pqt_series: list[LinePoint] = []
    pr_series: list[LinePoint] = []
    pt_series: list[LinePoint] = []
    div_yield_series: list[LinePoint] = []
    theses_count: list[LinePoint]
    equity_curve: list[LinePoint]
    benchmark_curve: list[LinePoint]
    drawdown_curve: list[LinePoint] = []
    markers: list[ChartMarker]
    trades: list[TradeItem]
