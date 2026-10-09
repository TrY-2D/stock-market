from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from src.strategies.indicators.candlestick import CandlestickPatternDetector, CandlestickSignal
from src.strategies.valuation import ExpectedReturnEngine, ValuationSnapshot


class NautilusQuantitativeConfig(StrategyConfig, kw_only=True):
    """Cấu hình cho chiến lược định lượng chạy trên nền tảng Nautilus Trader."""
    instrument_id: InstrumentId
    bar_type: BarType
    shares_outstanding: float = 1_000_000_000.0
    dividend_history: list[float] | None = None
    base_nav_pct: float = 0.04
    lot_size: int = 100
    window: int = 30
    linear_window: int | None = None
    sma_window: int | None = None
    beta_window: int | None = None
    z_score_window: int = 120
    sma20_period: int = 20
    atr_period: int = 14
    atr_multiplier: float = 1.0
    linear_k: float = 5.0
    min_theses: int = 3
    expanding: bool = False
    macro_lookup: dict[str, dict[str, float]] | None = None

class NautilusQuantitativeStrategy(Strategy):
    """Chiến lược giao dịch định lượng chuẩn Nautilus Trader.

    Triển khai toàn bộ quy tắc:
    - ExpectedReturnEngine: Dự phóng lợi nhuận E, cụm Q, Beta đa biến, LRC, SMA, Cổ tức D.
    - 5 Luận điểm định lượng (Yêu cầu >= 3/5 để mở vị thế).
    - CandlestickPatternDetector: Nhận diện nến đảo chiều tăng/giảm.
    - Phân bổ vốn theo dãy Fibonacci: 1, 1, 2, 3, 5 cho Mua; 5, 3, 2, 1, 1 cho Bán.
    - Vùng giá gợi ý P_suggest +/- 1 ATR.
    """

    BUY_FACTORS: tuple[int, ...] = (1, 1, 2, 3, 5)
    SELL_FACTORS: tuple[int, ...] = (5, 3, 2, 1, 1)

    def __init__(self, config: NautilusQuantitativeConfig):
        super().__init__(config)
        self.instrument_id: InstrumentId = config.instrument_id
        self.bar_type: BarType = config.bar_type
        self.instrument: Instrument | None = None
        self.dividend_history = config.dividend_history or [1500.0, 1500.0, 2000.0, 2000.0, 2500.0]

        # Khởi tạo mô hình định giá E và nhận diện nến
        self.engine = ExpectedReturnEngine(
            window=config.window,
            linear_window=config.linear_window,
            sma_window=config.sma_window,
            beta_window=config.beta_window,
            z_score_window=config.z_score_window,
            atr_period=config.atr_period,
            atr_multiplier=config.atr_multiplier,
            linear_k=config.linear_k,
            expanding=config.expanding,
        )
        self.macro_lookup = config.macro_lookup or {}

        # Tranche Fibonacci pointers
        self.buy_tranche_idx = 0
        self.sell_tranche_idx = 0

        # Lịch sử nến trước đó và SMA20
        self.prev_open: float | None = None
        self.prev_close: float | None = None
        self.sma20_buffer: list[float] = []

        # Nhật ký và snapshot phục vụ phân tích
        self.snapshots: list[ValuationSnapshot] = []
        self.strategy_logs: list[dict[str, Any]] = []

    def on_start(self) -> None:
        self.log.info(f"Khởi động NautilusQuantitativeStrategy cho {self.instrument_id}")
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.warning(f"Chưa tìm thấy instrument {self.instrument_id} trong cache, sẽ tải khi nhận bar đầu tiên")
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None:
            self.instrument = self.cache.instrument(self.instrument_id)
            if self.instrument is None:
                return

        # 1. Trích xuất dữ liệu giá từ Bar
        o = bar.open.as_double()
        h = bar.high.as_double()
        l = bar.low.as_double()
        c = bar.close.as_double()
        v = bar.volume.as_double()

        # 2. Ngày giao dịch và dữ liệu vĩ mô
        dt = pd.to_datetime(bar.ts_event, unit="ns", utc=True).strftime("%Y-%m-%d")
        macro = self.macro_lookup.get(dt, {})
        vni = macro.get("vnindex", 1200.0)
        eur = macro.get("eurusd", 1.08)
        dxy = macro.get("dxy", 104.0)
        fx = macro.get("usdvnd", 25000.0)
        inf = macro.get("inflation", 3.5)
        by = macro.get("bond_yield_10y", 2.5)

        # 3. Cập nhật SMA20
        self.sma20_buffer.append(c)
        sma20 = float(np.mean(self.sma20_buffer[-self.config.sma20_period:]))

        # 4. Nhận diện nến đảo chiều
        candle_sig: CandlestickSignal = CandlestickPatternDetector.analyze(
            open_p=o,
            high_p=h,
            low_p=l,
            close_p=c,
            prev_open=self.prev_open,
            prev_close=self.prev_close,
        )
        self.prev_open = o
        self.prev_close = c

        # 5. Cập nhật mô hình định giá E và 5 luận điểm
        snapshot = self.engine.update(
            stock_open=o,
            stock_high=h,
            stock_low=l,
            stock_close=c,
            stock_volume=v,
            shares_outstanding=self.config.shares_outstanding,
            dividend_5y_history=self.dividend_history,
            eurusd_close=eur,
            dxy_close=dxy,
            usdvnd_close=fx,
            inflation_rate=inf,
            bond_yield_10y=by,
        )
        self.snapshots.append(snapshot)

        # 6. Kiểm tra tài khoản & NAV
        equities = self.portfolio.equity(venue=self.instrument_id.venue)
        quote_curr = self.instrument.quote_currency
        equity_money = equities.get(quote_curr) if equities else None
        total_nav = equity_money.as_double() if equity_money is not None and equity_money.as_double() > 0 else 1_000_000_000.0

        net_pos = self.portfolio.net_position(self.instrument_id)
        shares_held = int(net_pos) if net_pos is not None else 0

        # 7. Kiểm tra tín hiệu DMI & Đảo chiều (với delay khi trend_strength > 30)
        # Bỏ cooling signal; Bỏ yêu cầu trend_strength >= 10.
        # Khi trend_strength > 30: tín hiệu đảo chiều bị delay chỉ kích hoạt khi trend_strength bắt đầu giảm.
        dmi = self.engine.stock_dmi
        dmi_buy_signal = dmi.check_buy_reversal_signal(candle_sig.is_bullish)
        dmi_sell_signal = dmi.check_sell_reversal_signal(candle_sig.is_bearish)

        executed = False

        # =============================================================
        # 8. Quy tắc MUA (Buy Rules)
        # =============================================================
        if (
            snapshot.theses_count >= self.config.min_theses
            and c <= snapshot.buy_threshold
            and dmi_buy_signal
            and sma20 > snapshot.p_suggest
            and self.buy_tranche_idx < len(self.BUY_FACTORS)
        ):
            factor = self.BUY_FACTORS[self.buy_tranche_idx]
            target_value = factor * self.config.base_nav_pct * total_nav
            raw_shares = target_value / c
            lot_sz = self.config.lot_size
            shares_to_buy = int(math.floor(raw_shares / lot_sz) * lot_sz)

            if shares_to_buy >= lot_sz:
                order = self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity(shares_to_buy, 0),
                )
                self.submit_order(order)
                self.log.info(
                    f"BUY Lệnh #{self.buy_tranche_idx + 1} (Factor {factor}) | {shares_to_buy:,d} CP @ {c:,.0f} | "
                    f"Luận điểm {snapshot.theses_count}/5 | E={snapshot.expected_return:+.2%}"
                )
                self.buy_tranche_idx += 1
                self.sell_tranche_idx = 0
                dmi.pending_buy_reversal = False
                executed = True

        # =============================================================
        # 9. Quy tắc BÁN (Sell Rules)
        # =============================================================
        if (
            not executed
            and shares_held >= self.config.lot_size
            and c >= snapshot.sell_threshold
            and dmi_sell_signal
            and sma20 < snapshot.p_suggest
            and self.sell_tranche_idx < len(self.SELL_FACTORS)
        ):
            factor = self.SELL_FACTORS[self.sell_tranche_idx]
            sell_ratio = min(1.0, factor / sum(self.SELL_FACTORS[self.sell_tranche_idx:]))
            raw_shares = shares_held * sell_ratio
            lot_sz = self.config.lot_size
            shares_to_sell = int(math.floor(raw_shares / lot_sz) * lot_sz)

            if self.sell_tranche_idx == len(self.SELL_FACTORS) - 1 or shares_held - shares_to_sell < lot_sz:
                shares_to_sell = shares_held

            if shares_to_sell >= lot_sz:
                order = self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=Quantity(shares_to_sell, 0),
                )
                self.submit_order(order)
                self.log.info(
                    f"SELL Lệnh #{self.sell_tranche_idx + 1} (Factor {factor}) | {shares_to_sell:,d} CP @ {c:,.0f} | "
                    f"Vùng bán (>{snapshot.sell_threshold:,.0f})"
                )
                self.sell_tranche_idx += 1
                if shares_held - shares_to_sell == 0:
                    self.buy_tranche_idx = 0
                dmi.pending_sell_reversal = False
    def on_stop(self) -> None:
        self.log.info(f"Dừng NautilusQuantitativeStrategy. Tổng số snapshot định giá: {len(self.snapshots)}")
