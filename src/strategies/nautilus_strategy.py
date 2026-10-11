from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from src.strategies.execution import ExecutionResult, FibonacciExecuteEngine, PositionLevel
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
    v0: int | None = None
    initial_cash: float = 1_000_000_000.0
    buy_fee_rate: float = 0.0015
    sell_fee_tax_rate: float = 0.0025
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
    """Chiến lược giao dịch định lượng chuẩn Nautilus Trader (Fibonacci Multi-Level Trading).

    Triển khai toàn bộ quy tắc:
    - ExpectedReturnEngine: Dự phóng lợi nhuận (A), 6 luận điểm định lượng, Reversal Indicator (DMI, Nến, Linear, SMA).
    - FibonacciExecuteEngine: Quản lý vị thế đa cấp độc lập M = [1, 1, 2, 3, 5, 8], sức chứa 20*V0.
    - Logic Mua: Ưu tiên cấp thấp L1 -> L6, ràng buộc P_buy,i < P_buy,prev.
    - Logic Bán: Ưu tiên cấp cao L6 -> L1, PnL Barrier (PnL > 0 hoặc |PnL| <= Surplus).
    - Tích hợp phát lệnh qua order_factory của Nautilus Trader.
    """

    FIBONACCI_MULTIPLIERS: tuple[int, ...] = (1, 1, 2, 3, 5, 8)
    BUY_FACTORS: tuple[int, ...] = FIBONACCI_MULTIPLIERS
    SELL_FACTORS: tuple[int, ...] = (8, 5, 3, 2, 1, 1)

    def __init__(self, config: NautilusQuantitativeConfig):
        super().__init__(config)
        self.instrument_id: InstrumentId = config.instrument_id
        self.bar_type: BarType = config.bar_type
        self.instrument: Instrument | None = None
        self.dividend_history = config.dividend_history or [1500.0, 1500.0, 2000.0, 2000.0, 2500.0]

        # Khởi tạo mô hình định giá E và 6 luận điểm
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

        # Khởi tạo Execute Engine quản lý lệnh đa cấp Fibonacci
        self.execute_engine = FibonacciExecuteEngine(
            v0=config.v0 or max(config.lot_size, 100),
            initial_cash=config.initial_cash,
            initial_surplus=0.0,
            buy_fee_rate=config.buy_fee_rate,
            sell_fee_tax_rate=config.sell_fee_tax_rate,
            lot_size=config.lot_size,
            net_pnl=True,
        )

        # Lịch sử nến trước đó và SMA20
        self.prev_open: float | None = None
        self.prev_close: float | None = None
        self.sma20_buffer: list[float] = []

        # Nhật ký và snapshot phục vụ phân tích
        self.snapshots: list[ValuationSnapshot] = []
        self.strategy_logs: list[dict[str, Any]] = []
        self.strategy_trades: list[Any] = []

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
        v = bar.volume.as_double() if hasattr(bar, "volume") else 0.0

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

        # 5. Cập nhật mô hình định giá E và 6 luận điểm
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
        total_nav = equity_money.as_double() if equity_money is not None and equity_money.as_double() > 0 else self.config.initial_cash
        # Đồng bộ số dư tiền mặt của execute_engine
        if not self.execute_engine.open_levels:
            self.execute_engine.cash = total_nav

        # Cập nhật chu kỳ thanh toán bù trừ T+ và số luận điểm K
        self.execute_engine.advance_settlement(dt)
        self.execute_engine.update_theses_count(snapshot.theses_count)

        # 7. Tự động hiệu chỉnh V0 khi vị thế = 0 (nếu không cố định v0 từ config)
        if self.execute_engine.total_holding_shares == 0 and self.config.v0 is None and c > 0:
            raw_v0 = (self.config.base_nav_pct * total_nav) / c
            computed_v0 = max(self.config.lot_size, int(math.floor(raw_v0 / self.config.lot_size) * self.config.lot_size))
            while computed_v0 > self.config.lot_size and (20 * computed_v0 * c * (1.0 + self.config.buy_fee_rate) > total_nav):
                computed_v0 -= self.config.lot_size
            try:
                self.execute_engine.set_v0(computed_v0)
            except ValueError:
                pass

        # 8. Thực thi lệnh trực tiếp theo Số Luận Điểm K và V_order
        # Thêm 1 luận điểm -> Thêm khối lượng cổ phiếu; Bớt 1 luận điểm -> Bớt khối lượng cổ phiếu
        change_rate = getattr(snapshot, "change_rate", 1) or 1
        self.execute_engine.sync_theses_demand(snapshot.theses_count)

        v_action, v_level, v_order = self.execute_engine.calculate_v_order(change_rate=change_rate)

        if v_action == "BUY" and v_order >= self.config.lot_size:
            can_buy, level, vol, reason = self.execute_engine.can_buy(price=c, volume=v_order)
            if can_buy and level is not None and vol >= self.config.lot_size:
                order = self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity(vol, 0),
                )
                self.submit_order(order)
                exec_res = self.execute_engine.execute_buy(
                    price=c,
                    volume=vol,
                    timestamp=dt,
                    order_id=str(order.client_order_id),
                    metadata={"theses_count": snapshot.theses_count},
                )
                multiplier = self.FIBONACCI_MULTIPLIERS[level - 1]
                self.log.info(
                    f"BUY Lệnh Cấp {level} (V_order={vol:,d} CP @ {c:,.0f}) | "
                    f"Luận điểm {snapshot.theses_count}/7 | E={snapshot.expected_return:+.2%}"
                )
                self._record_trade(exec_res, snapshot, dt, c, level, multiplier)
            else:
                self.log.info(f"Bỏ qua phát lệnh BUY: {reason}")

        elif v_action == "SELL" and v_order >= self.config.lot_size:
            can_sell, level, vol, pnl, reason = self.execute_engine.can_sell(price=c, volume=v_order)
            if can_sell and level is not None and vol >= self.config.lot_size:
                order = self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=Quantity(vol, 0),
                )
                self.submit_order(order)
                exec_res = self.execute_engine.execute_sell(
                    price=c,
                    volume=vol,
                    timestamp=dt,
                )
                multiplier = self.FIBONACCI_MULTIPLIERS[level - 1]
                self.log.info(
                    f"SELL Lệnh Cấp {level} (V_order={vol:,d} CP @ {c:,.0f}) | PnL={exec_res.pnl:+,.0f} VNĐ | "
                    f"Thặng dư: {self.execute_engine.surplus:+,.0f} VNĐ"
                )
                self._record_trade(exec_res, snapshot, dt, c, level, multiplier)
            else:
                self.log.info(f"Bỏ qua phát lệnh SELL: {reason}")
    def _record_trade(
        self,
        exec_res: ExecutionResult,
        snapshot: ValuationSnapshot,
        dt: str,
        price: float,
        level: int,
        multiplier: int,
    ) -> None:
        """Ghi nhận bản ghi giao dịch để trích xuất báo cáo."""
        from src.backtest.engine import TradeRecord

        rec = TradeRecord(
            date=dt,
            action=exec_res.action,
            price=price,
            shares=exec_res.volume,
            amount=exec_res.volume * price,
            fee_tax=exec_res.fee_tax,
            factor=multiplier,
            theses_count=snapshot.theses_count,
            reason=exec_res.reason,
            cash_after=self.execute_engine.cash,
            shares_after=self.execute_engine.total_holding_shares,
            nav_after=self.execute_engine.total_nav(price),
            level=level,
            pnl=exec_res.pnl,
            surplus_after=self.execute_engine.surplus,
        )
        self.strategy_trades.append(rec)

    def on_stop(self) -> None:
        self.log.info(
            f"Dừng NautilusQuantitativeStrategy. Tổng số snapshot: {len(self.snapshots)}, "
            f"Tổng số lệnh thực thi: {len(self.strategy_trades)}, "
            f"Thặng dư tích lũy: {self.execute_engine.surplus:,.0f} VNĐ"
        )
