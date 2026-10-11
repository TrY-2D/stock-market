from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any, Sequence


@dataclass
class Lot:
    """
    Đại diện cho một Lô cổ phiếu độc lập trong Kho lưu ký chung (Lot Inventory Pool).
    Mỗi đợt khớp lệnh mua tạo ra một Lot độc lập với giá vốn P_entry và trạng thái thanh toán T+.
    """
    lot_id: str                         # Mã định danh lô cổ phiếu (ví dụ: LOT-001)
    volume: int                         # Tổng khối lượng cổ phiếu của lô
    available_volume: int               # Khối lượng khả dụng có thể giao dịch (V_avail)
    entry_price: float                  # Giá vốn khớp lệnh ban đầu (P_entry)
    entry_time: Any = None              # Thời điểm khớp lệnh mua
    buy_fee: float = 0.0                # Phí mua phát sinh của lô
    settlement_status: str = "T0_MATCHED"  # "T0_MATCHED", "T1_PENDING", "T2_SETTLING", "SETTLED_AVAILABLE"
    settlement_days: int = 0            # Số ngày giao dịch đã trôi qua kể từ ngày mua (T+0, T+1, T+2)
    order_id: str | None = None         # Mã lệnh mua gốc

    @property
    def is_tradable(self) -> bool:
        """Kiểm tra lô đã hoàn tất thanh toán bù trừ và có thể thanh lý ngay."""
        return self.settlement_status == "SETTLED_AVAILABLE" and self.available_volume > 0

    def calc_pnl(
        self,
        current_price: float,
        volume: int | None = None,
        sell_fee_tax_rate: float = 0.0025,
        net: bool = True,
    ) -> float:
        """Tính PnL của lô (toàn phần hoặc một phần volume) tại mức giá hiện tại."""
        v = self.volume if volume is None else min(int(volume), self.volume)
        if v <= 0:
            return 0.0
        gross_pnl = v * (float(current_price) - self.entry_price)
        if not net:
            return gross_pnl
        fee_portion = (v / self.volume) * self.buy_fee if self.volume > 0 else 0.0
        sell_fee_tax = v * float(current_price) * sell_fee_tax_rate
        return gross_pnl - fee_portion - sell_fee_tax


@dataclass
class PositionLevel:
    """
    Tiểu khoản Fibonacci (Sub-account Level) - Đóng vai trò 'khoang chứa hạn mức' (Capital Bucket).
    Quản lý hạn mức độc lập theo chuỗi trọng số M = [1, 1, 2, 3, 5, 8].
    """
    level: int                      # Cấp độ lệnh (1 đến 6)
    multiplier: int                 # Hệ số nhân Fibonacci (1, 1, 2, 3, 5, 8)
    volume: int = 0                 # Khối lượng cổ phiếu hiện phân bổ cho cấp này (V_hold, i)
    entry_price: float = 0.0        # Giá vốn bình quân gia quyền nội bộ cấp (P_VWAP, i)
    entry_time: Any = None          # Thời gian vào lệnh đầu tiên
    buy_fee: float = 0.0            # Tổng phí mua đã phân bổ cho cấp
    order_id: str | None = None     # Mã định danh lệnh gần nhất
    metadata: dict[str, Any] = field(default_factory=dict)
    target_volume: int = 0          # Hạn mức định mức của cấp (V_i^target = M_i * V0)
    status: str = "EMPTY"           # "EMPTY" | "PARTIALLY_FILLED" | "ACTIVE" | "CLOSING_PARTIAL" | "PENDING_EXIT"

    @property
    def cost_basis(self) -> float:
        """Tổng giá trị vốn mua của cấp (gồm phí mua)."""
        return self.volume * self.entry_price + self.buy_fee

    def calc_pnl(
        self,
        current_price: float,
        volume: int | None = None,
        sell_fee_tax_rate: float = 0.0025,
        net: bool = True,
    ) -> float:
        """Tính PnL của cấp tại mức giá hiện tại."""
        v = self.volume if volume is None else min(int(volume), self.volume)
        if v <= 0:
            return 0.0
        gross_pnl = v * (float(current_price) - self.entry_price)
        if not net:
            return gross_pnl
        fee_portion = (v / self.volume) * self.buy_fee if self.volume > 0 else 0.0
        sell_fee_tax = v * float(current_price) * sell_fee_tax_rate
        return gross_pnl - fee_portion - sell_fee_tax

    def add_fill(
        self,
        fill_volume: int,
        fill_price: float,
        fill_fee: float = 0.0,
        timestamp: Any = None,
        order_id: str | None = None,
    ) -> None:
        """Cập nhật giá vốn bình quân VWAP và trạng thái khi nạp khối lượng vào cấp."""
        fill_vol = int(fill_volume)
        if fill_vol <= 0:
            return
        new_vol = self.volume + fill_vol
        if new_vol > 0:
            self.entry_price = (self.volume * self.entry_price + fill_vol * float(fill_price)) / float(new_vol)
        self.volume = new_vol
        self.buy_fee += float(fill_fee)
        if timestamp is not None and self.entry_time is None:
            self.entry_time = timestamp
        if order_id is not None:
            self.order_id = order_id
        if self.target_volume > 0:
            self.status = "ACTIVE" if self.volume >= self.target_volume else "PARTIALLY_FILLED"

    def reduce_fill(self, fill_volume: int) -> int:
        """Cập nhật giảm vị thế của cấp khi thanh lý, giữ nguyên giá vốn P_VWAP."""
        actual_reduce = min(int(fill_volume), self.volume)
        self.volume -= actual_reduce
        if self.volume <= 0:
            self.status = "EMPTY"
        else:
            self.status = "CLOSING_PARTIAL"
        return actual_reduce


@dataclass
class ExecutionResult:
    """Kết quả xử lý và thực thi một lệnh giao dịch."""
    success: bool                   # Trạng thái thực thi (True: Khớp lệnh, False: Bị chặn/Từ chối)
    action: str                     # Hành động: "BUY", "SELL", "REJECT", "HOLD"
    level: int | None = None        # Cấp độ lệnh liên quan (1 đến 6)
    volume: int = 0                 # Khối lượng giao dịch (cổ phiếu)
    price: float = 0.0              # Giá khớp thực tế
    pnl: float = 0.0                # Lợi nhuận/thua lỗ thực hiện (Realized PnL khi SELL)
    fee_tax: float = 0.0            # Tổng phí & thuế phát sinh trong lượt này
    cash_after: float = 0.0         # Số dư tiền mặt sau lệnh
    shares_after: int = 0           # Tổng số cổ phiếu nắm giữ sau lệnh
    surplus_after: float = 0.0      # Quỹ thặng dư tích lũy sau lệnh
    reason: str = ""                # Lý do giải thích chi tiết
    timestamp: Any = None           # Thời điểm thực hiện


class FibonacciExecuteEngine:
    r"""
    TÀI LIỆU ĐẶC TẢ KỸ THUẬT HỆ THỐNG KIẾN TRÚC HOÀN CHỈNH (SYSTEM SPECIFICATION v3.0)
    Module: Execute Engine – Fibonacci Multi-Level Trading

    1. Kiến trúc phân tầng:
       - Tầng 1: Tiểu khoản Fibonacci (Sub-account Allocation): L1 -> L6 với M = [1, 1, 2, 3, 5, 8].
         Hạn mức từng cấp: V_i^target = M_i * V0. Sức chứa danh mục tối đa V_max = 20 * V0 (hoặc tối đa 21 * V0).
       - Tầng 2: Kho lưu ký chung (Lot Inventory Pool): Quản lý từng Lô Lot_k với giá vốn riêng và chu kỳ T+.

    2. Quản lý trạng thái theo Số Luận Điểm (K) & Cơ chế rút lui:
       - Ngưỡng cứng (Hard Gate): Chỉ có K tiểu khoản đầu tiên {L1, ..., LK} được phép hoạt động.
       - Chốt chặn số 0 (Zero-Argument Hard Lock): Khi K = 0, ĐÓNG BĂNG TOÀN DIỆN CHIỀU MUA. Xóa sạch C_buy = 0.
       - Cơ chế rút lui khi K giảm: Cưỡng bức rút lui tiểu khoản vượt hạn mức (L_old -> L_new+1).

    3. Định cỡ phiên (Rate Limit) & V_order:
       - S = change_rate * (0.2 * C + lot_size).
       - S_exec = floor(S / 100) * 100.
       - V_order = min(S_exec, C).

    4. Logic MUA: Điều phối cấp nhỏ nhất chưa đầy (L1 -> LK), tạo Lot mới (T0_MATCHED).
    5. Logic BÁN: Thuật toán bốc Lô tối ưu thanh khoản & PnL Barrier (Tradable T+ filter, PnL Barrier, Highest Entry Price First).
    6. Quy trình dự phòng: Khóa phòng vệ kẹt hàng T+ (EMERGENCY_DEFENSIVE_LOCK) & Cool-down 1 phiên sau khi K = 0.
    """

    FIBONACCI_MULTIPLIERS: tuple[int, ...] = (1, 1, 2, 3, 5, 8)
    MAX_LEVELS: int = 6
    MAX_CAPACITY_FACTOR: int = 21  # 21 * V0

    def __init__(
        self,
        v0: int = 100,
        initial_cash: float = 1_000_000_000.0,
        initial_surplus: float = 0.0,
        buy_fee_rate: float = 0.0015,
        sell_fee_tax_rate: float = 0.0025,
        lot_size: int = 100,
        net_pnl: bool = True,
        strict_reserve_check: bool = False,
        settlement_cycle_days: int = 0,
    ):
        self._validate_v0(v0, lot_size)
        self._v0 = int(v0)
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.surplus = float(initial_surplus)
        self.buy_fee_rate = float(buy_fee_rate)
        self.sell_fee_tax_rate = float(sell_fee_tax_rate)
        self.lot_size = int(lot_size)
        self.net_pnl = bool(net_pnl)
        self.strict_reserve_check = bool(strict_reserve_check)
        self.settlement_cycle_days = int(settlement_cycle_days)

        # -------------------------------------------------------------
        # Tầng 1: Tiểu khoản Fibonacci (Sub-account Allocation)
        # -------------------------------------------------------------
        self.sub_accounts: dict[int, PositionLevel] = {
            lvl: PositionLevel(
                level=lvl,
                multiplier=m,
                volume=0,
                entry_price=0.0,
                target_volume=m * self._v0,
                status="EMPTY",
            )
            for lvl, m in enumerate(self.FIBONACCI_MULTIPLIERS, start=1)
        }

        # -------------------------------------------------------------
        # Tầng 2: Kho lưu ký chung (Lot Inventory Pool)
        # -------------------------------------------------------------
        self.lot_pool: list[Lot] = []
        self._lot_counter: int = 0

        # Trạng thái Luận điểm (K) & Điều phối chu kỳ
        self.current_theses_count: int = 6
        self.previous_theses_count: int = 6
        self.pending_buy_volume: int = 0
        self.pending_sell_volume: int = 0
        self.emergency_defensive_lock: bool = False
        self.cool_down_bars: int = 0
        self.last_session_date: Any = None

        # Lịch sử các lệnh thực thi
        self.trade_history: list[ExecutionResult] = []

        # Thống kê hiệu suất
        self.total_buy_count: int = 0
        self.total_sell_count: int = 0
        self.total_win_count: int = 0
        self.total_loss_count: int = 0
        self.realized_pnl: float = 0.0

    # ==================================================================
    # Properties & Getters
    # ==================================================================

    @property
    def v0(self) -> int:
        """Lệnh sơ cấp V0 (cổ phiếu)."""
        return self._v0

    @property
    def max_position_limit(self) -> int:
        """Sức chứa tối đa V_max = 21 * V0."""
        return self.MAX_CAPACITY_FACTOR * self._v0

    @property
    def total_holding_shares(self) -> int:
        """Tổng khối lượng cổ phiếu hiện đang nắm giữ trong kho."""
        return sum(lot.volume for lot in self.lot_pool)

    @property
    def total_tradable_shares(self) -> int:
        """Tổng khối lượng cổ phiếu đã thanh toán T+ và có thể bán ngay."""
        return sum(lot.available_volume for lot in self.lot_pool if lot.is_tradable)

    @property
    def open_levels(self) -> list[int]:
        """Danh sách các cấp lệnh đang có vị thế mở (sắp xếp tăng dần)."""
        return sorted([lvl for lvl, acc in self.sub_accounts.items() if acc.volume > 0])

    @property
    def positions(self) -> dict[int, PositionLevel]:
        """Bản sao từ điển các vị thế tiểu khoản hiện tại (phục vụ tương thích ngược)."""
        return {lvl: acc for lvl, acc in self.sub_accounts.items() if acc.volume > 0}

    @property
    def _positions(self) -> dict[int, PositionLevel]:
        """Bí danh nội bộ hỗ trợ tương thích ngược với các hàm tham chiếu cũ."""
        return self.sub_accounts

    @property
    def last_buy_price(self) -> float | None:
        """Giá mua bình quân VWAP của cấp lệnh đã mở cao nhất hiện có."""
        active_lvls = self.open_levels
        if not active_lvls:
            return None
        highest_level = max(active_lvls)
        return self.sub_accounts[highest_level].entry_price

    def get_target_volume_for_level(self, level: int) -> int:
        """Khối lượng định mức cho một cấp lệnh cụ thể (V_i^target = M_i * V0)."""
        if 1 <= level <= self.MAX_LEVELS:
            return self.FIBONACCI_MULTIPLIERS[level - 1] * self._v0
        return 0

    # ==================================================================
    # Dynamic Configuration
    # ==================================================================

    def set_v0(self, new_v0: int) -> bool:
        """
        Thay đổi khối lượng lệnh sơ cấp V0.
        Ràng buộc bất biến: Chỉ cho phép điều chỉnh khi toàn bộ danh mục ở trạng thái Flat (Tổng vị thế = 0).
        """
        if self.total_holding_shares > 0:
            raise ValueError(
                f"Không thể thay đổi V0 khi đang có vị thế mở ({self.total_holding_shares:,d} cp). "
                f"Yêu cầu tổng vị thế = 0."
            )
        self._validate_v0(new_v0, self.lot_size)
        self._v0 = int(new_v0)
        for lvl, m in enumerate(self.FIBONACCI_MULTIPLIERS, start=1):
            self.sub_accounts[lvl].target_volume = m * self._v0
        return True

    @staticmethod
    def _validate_v0(v0: int, lot_size: int = 100) -> None:
        if v0 < 100:
            raise ValueError(f"Khối lượng sơ cấp V0 ({v0}) phải >= 100 cp theo quy định UBCKNN.")
        if v0 % lot_size != 0:
            raise ValueError(f"Khối lượng sơ cấp V0 ({v0}) phải là bội số của lô {lot_size} cp.")

    # ==================================================================
    # Settlement Tracking & T+ Protocol
    # ==================================================================

    def advance_settlement(self, session_date: Any = None) -> None:
        """
        Chuyển phiên giao dịch mới: cập nhật chu kỳ thanh toán bù trừ T+ cho các lô trong kho.
        - T0_MATCHED -> T1_PENDING (sau 1 phiên).
        - T1_PENDING -> SETTLED_AVAILABLE (sau 2 phiên / T+2).
        """
        if session_date is not None:
            if self.last_session_date == session_date:
                return
            self.last_session_date = session_date

        if self.cool_down_bars > 0:
            self.cool_down_bars -= 1

        for lot in self.lot_pool:
            lot.settlement_days += 1
            if lot.settlement_days >= self.settlement_cycle_days:
                lot.settlement_status = "SETTLED_AVAILABLE"
                lot.available_volume = lot.volume
            elif lot.settlement_days == 1:
                lot.settlement_status = "T1_PENDING"
                lot.available_volume = 0

        # Nếu đang ở chế độ Emergency Lock và hàng đã về -> tự động gỡ khóa phòng vệ
        if self.emergency_defensive_lock and self.total_tradable_shares > 0:
            self.emergency_defensive_lock = False
            self.pending_sell_volume = max(self.pending_sell_volume, self.total_tradable_shares)

    # ==================================================================
    # Quản lý trạng thái theo Số Luận Điểm (K) & Rút lui cưỡng bức
    # ==================================================================

    def update_theses_count(self, k: int) -> None:
        """
        Cập nhật số luận điểm K và kích hoạt cơ chế chốt chặn hoặc thoái lui cưỡng bức:
        1. K = 0 (Zero-Argument Hard Lock): Đóng băng toàn diện chiều Mua, xóa C_buy = 0.
        2. K_new < K_old: Kích hoạt thoái lui giải phóng các tiểu khoản L_m (m > K_new).
        3. Kẹt hàng T+ (T+ Lockout Protocol): Kích hoạt EMERGENCY_DEFENSIVE_LOCK.
        """
        k_val = max(int(k), 0)
        old_k = self.current_theses_count
        self.previous_theses_count = old_k
        self.current_theses_count = k_val

        # -------------------------------------------------------------
        # Chốt chặn số 0 (Zero-Argument Hard Lock)
        # -------------------------------------------------------------
        if k_val == 0:
            # Đóng băng toàn diện chiều MUA
            self.pending_buy_volume = 0
            self.cool_down_bars = 1  # Thời gian làm nguội tối thiểu 1 phiên

            if self.total_holding_shares > 0:
                # Kiểm tra hàng đã về T+ chưa
                if self.total_tradable_shares == 0:
                    # Kẹt hàng T+: kích hoạt khóa phòng vệ khẩn cấp
                    self.emergency_defensive_lock = True
                    for lvl in self.open_levels:
                        self.sub_accounts[lvl].status = "PENDING_EXIT"
                else:
                    # Có hàng khả dụng: phát lệnh thanh lý giải phóng toàn bộ danh mục
                    self.pending_sell_volume = max(self.pending_sell_volume, self.total_tradable_shares)
            return

        # -------------------------------------------------------------
        # Cơ chế rút lui khi số luận điểm suy giảm (K_new < K_old)
        # -------------------------------------------------------------
        if k_val < old_k:
            volume_to_release = 0
            for lvl in range(self.MAX_LEVELS, k_val, -1):
                acc = self.sub_accounts.get(lvl)
                if acc and acc.volume > 0:
                    acc.status = "PENDING_EXIT"
                    volume_to_release += acc.volume

            if volume_to_release > 0:
                # Nạp vào hàng chờ bán C_sell
                self.pending_sell_volume = max(self.pending_sell_volume, volume_to_release)

    # ==================================================================
    # Execution Rate Limit (Hạn mức phát lệnh phiên)
    # ==================================================================

    def calc_execution_rate_limit(
        self,
        pending_volume: int,
        change_rate: float | int = 1,
        min_step: int | None = None,
    ) -> int:
        r"""
        Tính toán hạn mức phiên (Execution Rate Limit) và khối lượng phát lệnh thực tế:
        S = change_rate * (0.2 * C + D)
        S_exec = floor(S / lot_size) * lot_size
        V_order = min(S_exec, C)
        """
        c = max(int(pending_volume), 0)
        if c <= 0:
            return 0
        f = max(float(change_rate), 0.0)
        if f <= 0.0:
            return 0
        d = float(min_step if min_step is not None else self.lot_size)
        s_raw = f * (0.2 * float(c) + d)
        s_exec = int(math.floor(s_raw / float(self.lot_size)) * self.lot_size)
        if s_exec < self.lot_size:
            return 0
        return min(s_exec, c)

    # ==================================================================
    # Hàng chờ C & Định mức V_order
    # ==================================================================

    def enqueue_buy(self, volume: int | None = None) -> int:
        """
        Nạp khối lượng hàng chờ MUA (C_buy).
        Nếu K = 0 hoặc đang khóa phòng vệ khẩn cấp: từ chối tuyệt đối.
        """
        if self.current_theses_count == 0 or self.emergency_defensive_lock or self.cool_down_bars > 0:
            self.pending_buy_volume = 0
            return 0

        self.pending_sell_volume = 0
        if volume is not None and volume > 0:
            self.pending_buy_volume = int(volume)
            return self.pending_buy_volume

        next_lvl = self.get_next_buy_level()
        if next_lvl is None:
            self.pending_buy_volume = 0
            return 0

        target_vol = self.get_target_volume_for_level(next_lvl)
        curr_vol = self.sub_accounts[next_lvl].volume
        rem_vol = max(target_vol - curr_vol, 0)
        self.pending_buy_volume = rem_vol
        return self.pending_buy_volume

    def enqueue_sell(self, volume: int | None = None) -> int:
        """
        Nạp khối lượng hàng chờ BÁN (C_sell).
        Nếu volume is None, lấy khối lượng nắm giữ của cấp cao nhất hiện có.
        """
        self.pending_buy_volume = 0
        if volume is not None and volume > 0:
            self.pending_sell_volume = int(volume)
            return self.pending_sell_volume

        highest_lvl = self.get_highest_sell_level()
        if highest_lvl is None:
            self.pending_sell_volume = 0
            return 0

        self.pending_sell_volume = self.sub_accounts[highest_lvl].volume
        return self.pending_sell_volume

    def target_volume_for_theses(self, k: int) -> int:
        """Tính toán tổng khối lượng nắm giữ mục tiêu theo số luận điểm K."""
        active_k = min(max(int(k), 0), self.MAX_LEVELS)
        if active_k <= 0:
            return 0
        return sum(self.FIBONACCI_MULTIPLIERS[i] * self._v0 for i in range(active_k))

    def sync_theses_demand(self, k: int) -> tuple[str, int]:
        """
        Đồng bộ trực tiếp nhu cầu hàng chờ (Pending Volume C) theo số luận điểm K:
        - Thêm 1 luận điểm -> Thêm khối lượng cổ phiếu (diff > 0 -> enqueue_buy)
        - Bớt 1 luận điểm -> Bớt khối lượng cổ phiếu (diff < 0 -> enqueue_sell)
        - Luận điểm không đổi -> Giữ nguyên trạng thái (HOLD)
        - K = 0 -> Xóa sạch hàng chờ mua, thoái lui toàn bộ về tiền mặt
        """
        self.update_theses_count(k)
        active_k = min(max(int(k), 0), self.MAX_LEVELS)
        target_vol = self.target_volume_for_theses(active_k)
        curr_vol = self.total_holding_shares

        diff = target_vol - curr_vol
        if diff > 0 and active_k > 0:
            self.enqueue_buy(diff)
            return "BUY", diff
        elif diff < 0:
            self.enqueue_sell(abs(diff))
            return "SELL", abs(diff)
        else:
            self.pending_buy_volume = 0
            self.pending_sell_volume = 0
            return "HOLD", 0

    def calculate_v_order(
        self,
        change_rate: float | int = 1,
    ) -> tuple[str, int | None, int]:
        """
        Xác định khối lượng phát lệnh thực tế V_order và chiều giao dịch.
        Returns:
            (action, level, v_order)
            action in ("BUY", "SELL", "HOLD")
        """
        # Nếu K = 0: đóng băng chiều mua ngay tức khắc
        if self.current_theses_count == 0 or self.emergency_defensive_lock:
            self.pending_buy_volume = 0

        f = max(float(change_rate), 0.0)
        if f <= 0.0:
            return "HOLD", None, 0

        # Ưu tiên chiều BÁN nếu có yêu cầu thoái lui hoặc hàng chờ bán
        if self.pending_sell_volume > 0:
            highest_lvl = self.get_highest_sell_level()
            if highest_lvl is None or self.total_tradable_shares == 0:
                return "HOLD", None, 0
            max_sellable = min(self.pending_sell_volume, self.total_tradable_shares)
            v_order = self.calc_execution_rate_limit(
                pending_volume=max_sellable,
                change_rate=f,
                min_step=self.lot_size,
            )
            if v_order >= self.lot_size:
                return "SELL", highest_lvl, v_order
            return "HOLD", highest_lvl, 0

        elif self.pending_buy_volume > 0 and self.current_theses_count > 0 and self.cool_down_bars == 0:
            next_lvl = self.get_next_buy_level()
            if next_lvl is None:
                self.pending_buy_volume = 0
                return "HOLD", None, 0
            v_order = self.calc_execution_rate_limit(
                pending_volume=self.pending_buy_volume,
                change_rate=f,
                min_step=self.lot_size,
            )
            if v_order >= self.lot_size:
                return "BUY", next_lvl, v_order
            return "HOLD", next_lvl, 0

        return "HOLD", None, 0

    # ==================================================================
    # Capital & Cash Reserve Check
    # ==================================================================

    def check_cash_reserve(self, current_price: float) -> tuple[bool, float, float]:
        """Kiểm tra ràng buộc dự phòng tiền mặt cho 100% V_max."""
        required_cash = self.max_position_limit * float(current_price) * (1.0 + self.buy_fee_rate)
        is_sufficient = self.cash >= required_cash
        return is_sufficient, required_cash, self.cash

    # ==================================================================
    # Buy Execution Logic
    # ==================================================================

    def get_next_buy_level(self) -> int | None:
        """
        Tìm cấp lệnh Li nhỏ nhất chưa đầy trong phạm vi K luận điểm hiện hành:
        - Chỉ xét cấp Li với i in [1, min(6, K)].
        - Ưu tiên cấp đang PARTIALLY_FILLED trước, sau đó đến cấp EMPTY nhỏ nhất.
        """
        max_allowed_level = min(self.MAX_LEVELS, max(self.current_theses_count, 0))
        if max_allowed_level <= 0:
            return None

        for lvl in range(1, max_allowed_level + 1):
            acc = self.sub_accounts.get(lvl)
            if acc is None or acc.volume == 0:
                return lvl
            target_vol = self.get_target_volume_for_level(lvl)
            if acc.volume < target_vol:
                return lvl
        return None

    def can_buy(
        self,
        price: float,
        volume: int | None = None,
        change_rate: float | int | None = None,
    ) -> tuple[bool, int | None, int, str]:
        """Kiểm tra điều kiện MUA theo quy tắc Hệ thống v3.0."""
        price = float(price)
        if price <= 0:
            return False, None, 0, f"Giá mua không hợp lệ ({price})."

        # 1. Chốt chặn số 0 & Khóa phòng vệ
        if self.current_theses_count == 0 or self.emergency_defensive_lock:
            return False, None, 0, "Chốt chặn số 0 kích hoạt (K=0): Đóng băng toàn diện chiều MUA."

        if self.cool_down_bars > 0:
            return False, None, 0, "Đang trong thời gian làm nguội (Cool-down) sau khi K sụt về 0."

        # 2. Tìm cấp nhỏ nhất chưa đầy trong hạn mức K
        next_level = self.get_next_buy_level()
        if next_level is None:
            return (
                False,
                None,
                0,
                "Tất cả 6 cấp lệnh Fibonacci đều đã mở vị thế."
                if self.current_theses_count >= self.MAX_LEVELS
                else f"Đã mở tối đa {min(self.MAX_LEVELS, self.current_theses_count)} cấp lệnh cho phép theo K={self.current_theses_count}.",
            )

        target_vol = self.get_target_volume_for_level(next_level)
        current_vol = self.sub_accounts[next_level].volume
        remaining_level_cap = max(target_vol - current_vol, 0)

        if remaining_level_cap <= 0:
            return False, next_level, 0, f"Cấp {next_level} đã đạt tối đa hạn mức."

        req_vol = remaining_level_cap if volume is None else min(int(volume), remaining_level_cap)
        if req_vol < self.lot_size:
            req_vol = self.lot_size

        # 3. Áp dụng Execution Rate Limit
        if change_rate is not None:
            rate_limited_vol = self.calc_execution_rate_limit(
                pending_volume=req_vol,
                change_rate=change_rate,
                min_step=self.lot_size,
            )
            if rate_limited_vol < self.lot_size:
                return False, next_level, 0, f"Hạn mức S_exec ({rate_limited_vol}) nhỏ hơn lô tối thiểu ({self.lot_size})."
            volume_to_buy = rate_limited_vol
        else:
            volume_to_buy = req_vol

        # 4. Ràng buộc giá: P_buy, i < P_buy, prev (với i > 1 khi mở cấp mới)
        if next_level > 1 and current_vol == 0:
            prev_acc = self.sub_accounts.get(next_level - 1)
            prev_price = prev_acc.entry_price if (prev_acc and prev_acc.volume > 0) else self.last_buy_price
            if prev_price is not None and price >= prev_price:
                return (
                    False,
                    next_level,
                    volume_to_buy,
                    f"Giá mua Cấp {next_level} ({price:,.0f}) phải thấp hơn giá lệnh trước ({prev_price:,.0f}).",
                )

        # 5. Ràng buộc trần vị thế danh mục V_max = 21 * V0
        total_after = self.total_holding_shares + volume_to_buy
        if total_after > self.max_position_limit:
            avail_cap = max(self.max_position_limit - self.total_holding_shares, 0)
            if avail_cap < self.lot_size:
                return False, next_level, volume_to_buy, "Tổng vị thế sau mua vượt quá giới hạn tối đa V_max."
            volume_to_buy = int(math.floor(avail_cap / self.lot_size) * self.lot_size)

        # 6. Kiểm tra số dư tiền mặt
        required_cost = volume_to_buy * price * (1.0 + self.buy_fee_rate)
        if self.cash < required_cost:
            return False, next_level, volume_to_buy, f"Không đủ tiền mặt (cần {required_cost:,.0f}, có {self.cash:,.0f})."

        # 7. Kiểm tra dự phòng tiền mặt (nếu kích hoạt strict)
        if self.strict_reserve_check and next_level == 1:
            has_reserve, req_res, _ = self.check_cash_reserve(price)
            if not has_reserve:
                return False, next_level, volume_to_buy, "Không đủ tiền mặt dự phòng 100% V_max."

        return True, next_level, volume_to_buy, "Thỏa mãn đầy đủ điều kiện MUA."

    def execute_buy(
        self,
        price: float,
        volume: int | None = None,
        change_rate: float | int | None = None,
        timestamp: Any = None,
        order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Thực thi lệnh MUA:
        - Trừ tiền mặt khả dụng.
        - Tạo mới Lô cổ phiếu (Lot_k) đưa vào Kho lưu ký chung (T0_MATCHED).
        - Phân bổ hạn mức và cập nhật VWAP cho tiểu khoản Li.
        """
        can_exec, level, vol_to_buy, reason = self.can_buy(price, volume=volume, change_rate=change_rate)
        if not can_exec or level is None or vol_to_buy < self.lot_size:
            res = ExecutionResult(
                success=False,
                action="REJECT",
                level=level,
                volume=vol_to_buy,
                price=price,
                cash_after=self.cash,
                shares_after=self.total_holding_shares,
                surplus_after=self.surplus,
                reason=reason,
                timestamp=timestamp,
            )
            self.trade_history.append(res)
            return res

        multiplier = self.FIBONACCI_MULTIPLIERS[level - 1]
        target_vol = self.get_target_volume_for_level(level)
        gross_cost = vol_to_buy * float(price)
        fee = gross_cost * self.buy_fee_rate
        total_cost = gross_cost + fee

        # 1. Khấu trừ tiền mặt
        self.cash -= total_cost

        # 2. Nạp Lô cổ phiếu mới vào Kho lưu ký chung (Tầng 2)
        self._lot_counter += 1
        new_lot_id = f"LOT-{self._lot_counter:04d}"
        initial_status = "SETTLED_AVAILABLE" if self.settlement_cycle_days <= 0 else "T0_MATCHED"
        avail_vol = vol_to_buy if self.settlement_cycle_days <= 0 else 0

        new_lot = Lot(
            lot_id=new_lot_id,
            volume=vol_to_buy,
            available_volume=avail_vol,
            entry_price=float(price),
            entry_time=timestamp,
            buy_fee=fee,
            settlement_status=initial_status,
            settlement_days=self.settlement_cycle_days if self.settlement_cycle_days <= 0 else 0,
            order_id=order_id,
        )
        self.lot_pool.append(new_lot)

        # 3. Phân bổ hạn mức cho tiểu khoản Li (Tầng 1)
        acc = self.sub_accounts[level]
        acc.add_fill(
            fill_volume=vol_to_buy,
            fill_price=float(price),
            fill_fee=fee,
            timestamp=timestamp,
            order_id=order_id,
        )

        # 4. Giảm hàng chờ mua
        if self.pending_buy_volume > 0:
            self.pending_buy_volume = max(self.pending_buy_volume - vol_to_buy, 0)

        self.total_buy_count += 1

        res = ExecutionResult(
            success=True,
            action="BUY",
            level=level,
            volume=vol_to_buy,
            price=float(price),
            pnl=0.0,
            fee_tax=fee,
            cash_after=self.cash,
            shares_after=self.total_holding_shares,
            surplus_after=self.surplus,
            reason=f"Khớp MUA Cấp {level} ({acc.status}: {acc.volume:,d}/{target_vol:,d} cp | M={multiplier} @ {price:,.0f})",
            timestamp=timestamp,
        )
        self.trade_history.append(res)
        return res

    # ==================================================================
    # Sell Execution Logic (Bốc Lô Tối Ưu Thanh Khoản)
    # ==================================================================

    def get_highest_sell_level(self) -> int | None:
        """Tìm cấp lệnh Li lớn nhất hiện đang có vị thế mở để ưu tiên thanh lý (L6 -> L1)."""
        active_lvls = self.open_levels
        return max(active_lvls) if active_lvls else None

    def get_eligible_lots_to_sell(self, price: float) -> list[Lot]:
        """
        Thuật toán bốc Lô từ Kho lưu ký chung (Liquidity-Maximizing Lot Selection):
        1. Bộ lọc thanh toán T+ (is_tradable == True).
        2. Bộ lọc PnL Barrier (PnL > 0 HOẶC |PnL| <= Surplus).
        3. Ưu tiên giá vốn cao nhất trước (Highest Entry Price First).
        """
        eligible: list[Lot] = []
        for lot in self.lot_pool:
            if not lot.is_tradable:
                continue
            # Kiểm tra PnL Barrier trên lượng khả dụng của lô
            pnl = lot.calc_pnl(price, volume=lot.available_volume, sell_fee_tax_rate=self.sell_fee_tax_rate, net=self.net_pnl)
            if pnl > 0.0 or abs(pnl) <= self.surplus:
                eligible.append(lot)

        # Sắp xếp theo giá vốn giảm dần (P_entry cao nhất giải phóng trước)
        eligible.sort(key=lambda x: x.entry_price, reverse=True)
        return eligible

    def can_sell(
        self,
        price: float,
        volume: int | None = None,
        change_rate: float | int | None = None,
    ) -> tuple[bool, int | None, int, float, str]:
        """Kiểm tra điều kiện BÁN theo thuật toán Bốc Lô & PnL Barrier."""
        price = float(price)
        highest_level = self.get_highest_sell_level()
        if highest_level is None:
            return False, None, 0, 0.0, "Không có vị thế nào đang mở để bán."

        # 1. Bộ lọc thanh toán T+
        if self.total_tradable_shares == 0:
            return False, highest_level, 0, 0.0, "Không có cổ phiếu khả dụng để bán (chưa hoàn tất thanh toán T+)."

        # 2. Bốc lô theo bộ lọc PnL Barrier & Ưu tiên giá vốn cao
        eligible_lots = self.get_eligible_lots_to_sell(price)
        if not eligible_lots:
            return False, highest_level, 0, 0.0, f"Lệnh bán bị chặn: Khoản lỗ vượt quá thặng dư tích lũy ({self.surplus:,.0f} VNĐ)."

        acc = self.sub_accounts[highest_level]
        total_eligible_vol = sum(lot.available_volume for lot in eligible_lots)
        avail_vol = min(acc.volume, total_eligible_vol)

        req_vol = avail_vol if volume is None else min(int(volume), avail_vol)
        if req_vol < self.lot_size:
            req_vol = min(avail_vol, self.lot_size)

        # 3. Áp dụng Execution Rate Limit
        if change_rate is not None:
            rate_limited_vol = self.calc_execution_rate_limit(
                pending_volume=req_vol,
                change_rate=change_rate,
                min_step=self.lot_size,
            )
            if rate_limited_vol < self.lot_size:
                return False, highest_level, 0, 0.0, f"Hạn mức S_exec ({rate_limited_vol}) nhỏ hơn lô tối thiểu ({self.lot_size})."
            vol_to_sell = rate_limited_vol
        else:
            vol_to_sell = req_vol

        # 4. Tính toán PnL dự phóng trên các lô được chọn
        projected_pnl = 0.0
        remaining_calc = vol_to_sell
        for lot in eligible_lots:
            chunk = min(remaining_calc, lot.available_volume)
            projected_pnl += lot.calc_pnl(price, volume=chunk, sell_fee_tax_rate=self.sell_fee_tax_rate, net=self.net_pnl)
            remaining_calc -= chunk
            if remaining_calc <= 0:
                break

        return True, highest_level, vol_to_sell, projected_pnl, f"Thỏa mãn bán Cấp {highest_level} ({vol_to_sell:,d} cp | PnL={projected_pnl:+,.0f})."

    def execute_sell(
        self,
        price: float,
        volume: int | None = None,
        change_rate: float | int | None = None,
        timestamp: Any = None,
    ) -> ExecutionResult:
        """
        Thực thi lệnh BÁN:
        - Bốc các lô khả dụng có giá vốn cao nhất thỏa mãn PnL Barrier.
        - Khấu trừ volume của các lô tương ứng. Xóa lô nếu volume về 0.
        - Ghi nhận PnL thực tế vào quỹ Thặng dư tích lũy (Surplus).
        - Khấu trừ hạn mức tiểu khoản Li cấp cao nhất đang rút lui.
        """
        can_exec, level, vol_to_sell, pnl, reason = self.can_sell(price, volume=volume, change_rate=change_rate)
        if not can_exec or level is None or vol_to_sell < self.lot_size:
            res = ExecutionResult(
                success=False,
                action="REJECT",
                level=level,
                volume=vol_to_sell,
                price=price,
                pnl=pnl,
                cash_after=self.cash,
                shares_after=self.total_holding_shares,
                surplus_after=self.surplus,
                reason=reason,
                timestamp=timestamp,
            )
            self.trade_history.append(res)
            return res

        eligible_lots = self.get_eligible_lots_to_sell(price)
        remaining_to_sell = vol_to_sell
        realized_pnl_total = 0.0
        total_sell_tax = 0.0
        gross_received_total = 0.0

        # Trừ volume lần lượt từ các lô đã chọn
        for lot in eligible_lots:
            chunk = min(remaining_to_sell, lot.available_volume)
            chunk_gross = chunk * float(price)
            chunk_tax = chunk_gross * self.sell_fee_tax_rate if self.net_pnl else 0.0
            chunk_pnl = lot.calc_pnl(price, volume=chunk, sell_fee_tax_rate=self.sell_fee_tax_rate, net=self.net_pnl)

            realized_pnl_total += chunk_pnl
            total_sell_tax += chunk_tax
            gross_received_total += chunk_gross

            # Giảm volume của lô
            lot.available_volume -= chunk
            lot.volume -= chunk
            remaining_to_sell -= chunk

            if remaining_to_sell <= 0:
                break

        # Loại bỏ các lô đã thanh lý hết hoàn toàn khỏi kho
        self.lot_pool = [l for l in self.lot_pool if l.volume > 0]

        # 1. Cập nhật số dư tiền mặt
        net_cash_received = gross_received_total - total_sell_tax
        self.cash += net_cash_received

        # 2. Cập nhật quỹ Thặng dư tích lũy (Surplus += PnL)
        self.surplus += realized_pnl_total
        self.realized_pnl += realized_pnl_total

        if realized_pnl_total >= 0:
            self.total_win_count += 1
        else:
            self.total_loss_count += 1
        self.total_sell_count += 1

        # 3. Khấu trừ hạn mức của tiểu khoản cấp Li đang rút lui
        acc = self.sub_accounts[level]
        acc.reduce_fill(vol_to_sell)

        # 4. Cập nhật hàng chờ bán
        if self.pending_sell_volume > 0:
            self.pending_sell_volume = max(self.pending_sell_volume - vol_to_sell, 0)

        res = ExecutionResult(
            success=True,
            action="SELL",
            level=level,
            volume=vol_to_sell,
            price=float(price),
            pnl=realized_pnl_total,
            fee_tax=total_sell_tax,
            cash_after=self.cash,
            shares_after=self.total_holding_shares,
            surplus_after=self.surplus,
            reason=f"Khớp BÁN Cấp {level} ({vol_to_sell:,d} cp @ {price:,.0f} | PnL={realized_pnl_total:+,.0f} VNĐ)",
            timestamp=timestamp,
        )
        self.trade_history.append(res)
        return res

    # ==================================================================
    # External Broker / Exchange Fill Handler
    # ==================================================================

    def apply_fill(
        self,
        level: int,
        action: str,
        filled_volume: int,
        fill_price: float,
        fill_fee: float = 0.0,
        timestamp: Any = None,
        order_id: str | None = None,
    ) -> ExecutionResult:
        """Tiếp nhận trực tiếp kết quả khớp lệnh từ sàn giao dịch (Nautilus Trader OMS)."""
        lvl = int(level)
        vol = int(filled_volume)
        px = float(fill_price)
        fee = float(fill_fee)
        act = action.upper()

        if act == "BUY":
            # Nạp Lô mới vào kho
            self._lot_counter += 1
            new_lot = Lot(
                lot_id=f"LOT-{self._lot_counter:04d}",
                volume=vol,
                available_volume=vol if self.settlement_cycle_days <= 0 else 0,
                entry_price=px,
                entry_time=timestamp,
                buy_fee=fee,
                settlement_status="SETTLED_AVAILABLE" if self.settlement_cycle_days <= 0 else "T0_MATCHED",
                settlement_days=self.settlement_cycle_days if self.settlement_cycle_days <= 0 else 0,
                order_id=order_id,
            )
            self.lot_pool.append(new_lot)

            # Phân bổ cho tiểu khoản
            acc = self.sub_accounts[lvl]
            acc.add_fill(vol, px, fee, timestamp=timestamp, order_id=order_id)
            self.cash -= (vol * px + fee)
            self.total_buy_count += 1

            res = ExecutionResult(
                success=True,
                action="BUY",
                level=lvl,
                volume=vol,
                price=px,
                fee_tax=fee,
                cash_after=self.cash,
                shares_after=self.total_holding_shares,
                surplus_after=self.surplus,
                reason=f"Broker Fill MUA Cấp {lvl}: {vol:,d} cp @ {px:,.0f}",
                timestamp=timestamp,
            )
            self.trade_history.append(res)
            return res

        elif act == "SELL":
            acc = self.sub_accounts[lvl]
            if acc.volume <= 0:
                return ExecutionResult(
                    success=False,
                    action="REJECT",
                    level=lvl,
                    volume=vol,
                    price=px,
                    reason=f"Tiểu khoản Cấp {lvl} không có vị thế để khớp Bán.",
                    timestamp=timestamp,
                )

            eligible_lots = self.get_eligible_lots_to_sell(px)
            if not eligible_lots:
                # Nếu không có lô vượt barrier, fallback trừ lô có sẵn
                eligible_lots = [l for l in self.lot_pool if l.is_tradable]
                eligible_lots.sort(key=lambda x: x.entry_price, reverse=True)

            rem_sell = vol
            realized_pnl = 0.0
            tax = 0.0
            gross = 0.0

            for lot in eligible_lots:
                chunk = min(rem_sell, lot.available_volume)
                chunk_gross = chunk * px
                chunk_tax = chunk_gross * self.sell_fee_tax_rate if self.net_pnl else 0.0
                chunk_pnl = lot.calc_pnl(px, volume=chunk, sell_fee_tax_rate=self.sell_fee_tax_rate, net=self.net_pnl)

                realized_pnl += chunk_pnl
                tax += chunk_tax
                gross += chunk_gross

                lot.available_volume -= chunk
                lot.volume -= chunk
                rem_sell -= chunk
                if rem_sell <= 0:
                    break
            if rem_sell > 0:
                for lot in self.lot_pool:
                    chunk = min(rem_sell, lot.volume)
                    lot.volume -= chunk
                    lot.available_volume = max(lot.available_volume - chunk, 0)
                    rem_sell -= chunk
                    if rem_sell <= 0:
                        break


            self.lot_pool = [l for l in self.lot_pool if l.volume > 0]
            self.cash += (gross - tax)
            self.surplus += realized_pnl
            self.realized_pnl += realized_pnl

            if realized_pnl >= 0:
                self.total_win_count += 1
            else:
                self.total_loss_count += 1
            self.total_sell_count += 1

            acc.reduce_fill(vol)

            res = ExecutionResult(
                success=True,
                action="SELL",
                level=lvl,
                volume=vol,
                price=px,
                pnl=realized_pnl,
                fee_tax=tax,
                cash_after=self.cash,
                shares_after=self.total_holding_shares,
                surplus_after=self.surplus,
                reason=f"Broker Fill BÁN Cấp {lvl}: {vol:,d} cp @ {px:,.0f} | PnL={realized_pnl:+,.0f}",
                timestamp=timestamp,
            )
            self.trade_history.append(res)
            return res

        raise ValueError(f"Hành động không hợp lệ: {action}")

    # ==================================================================
    # Signal Dispatcher (Hỗ trợ theo V_order)
    # ==================================================================

    def on_signal(
        self,
        signal: int,
        price: float,
        theses_count: int | None = None,
        volume: int | None = None,
        change_rate: float | int | None = None,
        timestamp: Any = None,
        order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Bộ điều phối xử lý theo V_order và Luận điểm K (System Spec v3.0):
        1. Đồng bộ số luận điểm K -> Chốt chặn K=0 hoặc Thoái lui cưỡng bức.
        2. Kích hoạt hàng chờ C (enqueue_buy / enqueue_sell).
        3. Tính toán V_order = min(S_exec, C).
        4. Thực thi theo V_order.
        """
        if theses_count is not None:
            self.update_theses_count(theses_count)

        if signal == 1 and self.pending_buy_volume == 0:
            self.enqueue_buy(volume)
        elif signal == -1 and self.pending_sell_volume == 0:
            self.enqueue_sell(volume)

        eff_cr = change_rate if change_rate is not None else 1
        action, level, v_order = self.calculate_v_order(change_rate=eff_cr)

        if action == "BUY" and v_order >= self.lot_size:
            return self.execute_buy(
                price=price,
                volume=v_order,
                timestamp=timestamp,
                order_id=order_id,
                metadata=metadata,
            )
        elif action == "SELL" and v_order >= self.lot_size:
            return self.execute_sell(
                price=price,
                volume=v_order,
                timestamp=timestamp,
            )
        else:
            return ExecutionResult(
                success=False,
                action="HOLD",
                level=level,
                volume=v_order,
                price=price,
                cash_after=self.cash,
                shares_after=self.total_holding_shares,
                surplus_after=self.surplus,
                reason=f"Không phát sinh lệnh phiên này (action={action}, V_order={v_order}, K={self.current_theses_count}).",
                timestamp=timestamp,
            )

    # ==================================================================
    # Portfolio Valuation & State
    # ==================================================================

    def unrealized_pnl(self, current_price: float) -> float:
        """Tổng PnL chưa thực hiện của toàn bộ các lô cổ phiếu đang nắm giữ trong kho."""
        return sum(
            lot.calc_pnl(current_price, sell_fee_tax_rate=self.sell_fee_tax_rate, net=self.net_pnl)
            for lot in self.lot_pool
        )

    def total_nav(self, current_price: float) -> float:
        """Tổng giá trị tài sản ròng (NAV = Tiền mặt + Giá trị thị trường toàn bộ Lô cổ phiếu)."""
        stock_value = self.total_holding_shares * float(current_price)
        return self.cash + stock_value

    def get_status_summary(self, current_price: float) -> dict[str, Any]:
        """Tóm tắt trạng thái quản lý vị thế, kho lưu ký và quỹ thặng dư tại mức giá hiện tại."""
        unrealized = self.unrealized_pnl(current_price)
        nav = self.total_nav(current_price)
        return {
            "v0": self._v0,
            "max_capacity": self.max_position_limit,
            "total_shares": self.total_holding_shares,
            "total_tradable": self.total_tradable_shares,
            "open_levels": self.open_levels,
            "current_theses": self.current_theses_count,
            "emergency_lock": self.emergency_defensive_lock,
            "cool_down": self.cool_down_bars,
            "lots_count": len(self.lot_pool),
            "cash": self.cash,
            "surplus": self.surplus,
            "unrealized_pnl": unrealized,
            "realized_pnl": self.realized_pnl,
            "nav": nav,
            "buy_count": self.total_buy_count,
            "sell_count": self.total_sell_count,
            "win_rate": (self.total_win_count / max(self.total_sell_count, 1)) * 100.0,
        }

    def reset(self) -> None:
        """Khôi phục toàn bộ trạng thái ban đầu của engine."""
        self.cash = self.initial_cash
        self.surplus = 0.0
        self.lot_pool.clear()
        self._lot_counter = 0
        for lvl, m in enumerate(self.FIBONACCI_MULTIPLIERS, start=1):
            acc = self.sub_accounts[lvl]
            acc.volume = 0
            acc.entry_price = 0.0
            acc.buy_fee = 0.0
            acc.status = "EMPTY"
        self.pending_buy_volume = 0
        self.pending_sell_volume = 0
        self.current_theses_count = 6
        self.previous_theses_count = 6
        self.emergency_defensive_lock = False
        self.cool_down_bars = 0
        self.last_session_date = None
        self.trade_history.clear()
        self.total_buy_count = 0
        self.total_sell_count = 0
        self.total_win_count = 0
        self.total_loss_count = 0
        self.realized_pnl = 0.0


# Alias thuận tiện theo thiết kế
ExecuteEngine = FibonacciExecuteEngine
