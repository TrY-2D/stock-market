from __future__ import annotations

import pytest
from src.strategies.execution import (
    ExecuteEngine,
    ExecutionResult,
    FibonacciExecuteEngine,
    PositionLevel,
)


def test_fibonacci_execute_engine_initialization():
    engine = FibonacciExecuteEngine(v0=100, initial_cash=1_000_000_000.0)
    assert engine.v0 == 100
    assert engine.max_position_limit == 2100  # 21 * 100
    assert engine.total_holding_shares == 0
    assert engine.open_levels == []
    assert engine.cash == 1_000_000_000.0
    assert engine.surplus == 0.0


def test_v0_constraints_and_dynamic_modification():
    engine = FibonacciExecuteEngine(v0=100)

    # 1. Ràng buộc tối thiểu V0 >= 100 và bội số của 100
    with pytest.raises(ValueError, match=">= 100"):
        FibonacciExecuteEngine(v0=50)

    with pytest.raises(ValueError, match="bội số"):
        FibonacciExecuteEngine(v0=150)

    # 2. Thay đổi V0 khi vị thế = 0 -> Thành công
    assert engine.set_v0(200)
    assert engine.v0 == 200
    assert engine.max_position_limit == 4200  # 21 * 200

    # 3. Mở vị thế rồi cố gắng đổi V0 -> Bị từ chối
    engine.execute_buy(price=50000.0)
    assert engine.total_holding_shares == 200  # Cấp 1: 1 * 200
    with pytest.raises(ValueError, match="Không thể thay đổi V0 khi đang có vị thế mở"):
        engine.set_v0(300)


def test_buy_execution_levels_and_fibonacci_multipliers():
    # V0 = 100, Multipliers = [1, 1, 2, 3, 5, 8] -> Volumes = [100, 100, 200, 300, 500, 800]
    engine = FibonacciExecuteEngine(v0=100, initial_cash=500_000_000.0)

    # Cấp 1 (L1): Khớp theo giá thị trường (50,000)
    r1 = engine.execute_buy(price=50000.0)
    assert r1.success
    assert r1.level == 1
    assert r1.volume == 100
    assert engine.open_levels == [1]

    # Cấp 2 (L2): Thử mua giá cao hơn hoặc bằng -> BỊ CHẶN (P_new < P_prev)
    r2_fail = engine.execute_buy(price=50500.0)
    assert not r2_fail.success
    assert r2_fail.action == "REJECT"
    assert "phải thấp hơn giá lệnh trước" in r2_fail.reason
    assert engine.open_levels == [1]

    # Cấp 2 (L2): Mua giá thấp hơn (49,000) -> Thành công
    r2 = engine.execute_buy(price=49000.0)
    assert r2.success
    assert r2.level == 2
    assert r2.volume == 100
    assert engine.open_levels == [1, 2]

    # Cấp 3 (L3): Mua giá thấp hơn tiếp (48,000) -> Khối lượng = 2 * 100 = 200
    r3 = engine.execute_buy(price=48000.0)
    assert r3.success
    assert r3.level == 3
    assert r3.volume == 200
    assert engine.open_levels == [1, 2, 3]

    # Cấp 4 (L4): Mua giá 47,000 -> Khối lượng = 3 * 100 = 300
    r4 = engine.execute_buy(price=47000.0)
    assert r4.success
    assert r4.level == 4
    assert r4.volume == 300
    assert engine.open_levels == [1, 2, 3, 4]

    # Cấp 5 (L5): Mua giá 46,000 -> Khối lượng = 5 * 100 = 500
    r5 = engine.execute_buy(price=46000.0)
    assert r5.success
    assert r5.level == 5
    assert r5.volume == 500
    assert engine.open_levels == [1, 2, 3, 4, 5]

    # Cấp 6 (L6): Mua giá 45,000 -> Khối lượng = 8 * 100 = 800
    r6 = engine.execute_buy(price=45000.0)
    assert r6.success
    assert r6.level == 6
    assert r6.volume == 800
    assert engine.open_levels == [1, 2, 3, 4, 5, 6]

    # Tổng khối lượng lúc này = (1 + 1 + 2 + 3 + 5 + 8) * V0 = 20 * V0 = 2,000 cp
    # Sức chứa tối đa theo đặc tả V_max = 21 * V0 = 2,100 cp (2000 <= 2100)
    assert engine.total_holding_shares == 2000
    assert engine.total_holding_shares <= engine.max_position_limit
    # Thử mua tiếp khi đã đầy 6 cấp -> Bị từ chối
    r7_fail = engine.execute_buy(price=44000.0)
    assert not r7_fail.success
    assert "Tất cả 6 cấp lệnh" in r7_fail.reason


def test_independent_order_tracking_no_aggregation():
    engine = FibonacciExecuteEngine(v0=100)
    engine.execute_buy(price=50000.0)
    engine.execute_buy(price=48000.0)

    # Đảm bảo mỗi vị thế lưu đúng giá và khối lượng riêng biệt
    pos1 = engine.positions[1]
    pos2 = engine.positions[2]
    assert pos1.entry_price == 50000.0
    assert pos1.volume == 100
    assert pos2.entry_price == 48000.0
    assert pos2.volume == 100


def test_sell_execution_priority_highest_level_first():
    engine = FibonacciExecuteEngine(v0=100)
    engine.execute_buy(price=50000.0)  # L1: 100 cp @ 50,000
    engine.execute_buy(price=48000.0)  # L2: 100 cp @ 48,000
    engine.execute_buy(price=46000.0)  # L3: 200 cp @ 46,000

    # Bán tại giá 52,000 (Cả 3 cấp đều có lãi)
    # Ưu tiên bán cấp cao nhất hiện có: L3 (200 cp @ 46,000)
    r_sell = engine.execute_sell(price=52000.0)
    assert r_sell.success
    assert r_sell.level == 3
    assert r_sell.volume == 200
    assert r_sell.pnl > 0
    assert engine.open_levels == [1, 2]

    # Lần bán tiếp theo sẽ bán L2 (100 cp @ 48,000)
    r_sell2 = engine.execute_sell(price=52000.0)
    assert r_sell2.success
    assert r_sell2.level == 2
    assert r_sell2.volume == 100
    assert engine.open_levels == [1]


def test_sell_risk_management_pnl_barrier_and_surplus_protection():
    # Ban đầu thặng dư tích lũy Surplus = 0
    engine = FibonacciExecuteEngine(v0=100, initial_cash=100_000_000.0, net_pnl=False)

    # 1. Mở vị thế L1 @ 50,000 và L2 @ 45,000
    engine.execute_buy(price=50000.0)
    engine.execute_buy(price=45000.0)

    # Giá hiện tại rơi về 44,000:
    # L2 vào giá 45,000 -> Bán tại 44,000 bị lỗ: PnL = 100 * (44,000 - 45,000) = -100,000 VNĐ
    # Do Surplus = 0, |PnL| = 100,000 > Surplus -> Lệnh BÁN BỊ CHẶN
    r_sell_blocked = engine.execute_sell(price=44000.0)
    assert not r_sell_blocked.success
    assert r_sell_blocked.action == "REJECT"
    assert "vượt quá thặng dư tích lũy" in r_sell_blocked.reason
    assert engine.open_levels == [1, 2]

    # 2. Giá hồi lên 47,000:
    # L2 vào giá 45,000 -> Bán tại 47,000 có lãi: PnL = 100 * (47,000 - 45,000) = +200,000 VNĐ
    # Thỏa mãn Trường hợp 1 (Có lãi PnL > 0)
    r_sell_profit = engine.execute_sell(price=47000.0)
    assert r_sell_profit.success
    assert r_sell_profit.level == 2
    assert r_sell_profit.pnl == 200000.0
    assert engine.surplus == 200000.0  # Thặng dư tích lũy tăng lên 200,000 VNĐ
    assert engine.open_levels == [1]

    # 3. Bây giờ chỉ còn lại L1 (vào giá 50,000). Giá hiện tại là 48,500:
    # Lỗ của L1: PnL = 100 * (48,500 - 50,000) = -150,000 VNĐ
    # Kiểm tra bảo vệ thặng dư: |-150,000| <= Surplus (200,000) -> ĐƯỢC PHÉP CẮT LỖ
    r_sell_cutloss = engine.execute_sell(price=48500.0)
    assert r_sell_cutloss.success
    assert r_sell_cutloss.level == 1
    assert r_sell_cutloss.pnl == -150000.0
    # Thặng dư mới: 200,000 + (-150,000) = 50,000 VNĐ
    assert engine.surplus == 50000.0
    assert engine.open_levels == []
    assert engine.total_holding_shares == 0


def test_on_signal_dispatcher():
    engine = FibonacciExecuteEngine(v0=100)

    # Tín hiệu Mua (signal = 1)
    res_buy = engine.on_signal(signal=1, price=50000.0)
    assert res_buy.success
    assert res_buy.action == "BUY"
    assert res_buy.level == 1

    # Tín hiệu Bỏ qua (signal = 0)
    res_hold = engine.on_signal(signal=0, price=51000.0)
    assert not res_hold.success
    assert res_hold.action == "HOLD"

    # Tín hiệu Bán (signal = -1)
    res_sell = engine.on_signal(signal=-1, price=52000.0)
    assert res_sell.success
    assert res_sell.action == "SELL"
    assert res_sell.level == 1
    assert engine.total_holding_shares == 0


def test_cash_reserve_requirement_check():
    # V0 = 100 -> V_max = 2100. Với giá 50,000, 100% V_max cần khoảng 2100 * 50,000 = 105 triệu.
    engine_small_cash = FibonacciExecuteEngine(v0=100, initial_cash=50_000_000.0, strict_reserve_check=True)
    is_suff, req, avail = engine_small_cash.check_cash_reserve(50000.0)
    assert not is_suff
    assert avail == 50_000_000.0
    assert req > 100_000_000.0

    # Lệnh mua đầu tiên bị từ chối do không đủ dự phòng 100% V_max khi bật strict_reserve_check
    r_fail = engine_small_cash.execute_buy(price=50000.0)
    assert not r_fail.success
    assert "dự phòng 100% V_max" in r_fail.reason


def test_execution_rate_limit_calculation():
    engine = FibonacciExecuteEngine(v0=100)
    # C = 100, F = 1, D = 100 -> S = 1 * (0.2 * 100 + 100) = 120 -> S_exec = 100 -> min(100, 100) = 100
    v1 = engine.calc_execution_rate_limit(pending_volume=100, change_rate=1)
    assert v1 == 100

    # C = 500, F = 1, D = 100 -> S = 1 * (0.2 * 500 + 100) = 200 -> S_exec = 200 -> min(200, 500) = 200
    v2 = engine.calc_execution_rate_limit(pending_volume=500, change_rate=1)
    assert v2 == 200

    # C = 500, F = 2, D = 100 -> S = 2 * (0.2 * 500 + 100) = 400 -> S_exec = 400 -> min(400, 500) = 400
    v3 = engine.calc_execution_rate_limit(pending_volume=500, change_rate=2)
    assert v3 == 400

    # C = 0 -> 0
    v0 = engine.calc_execution_rate_limit(pending_volume=0, change_rate=1)
    assert v0 == 0


def test_partial_fill_and_level_status_lifecycle():
    # V0 = 200 -> V1^target = 200, V2^target = 200
    engine = FibonacciExecuteEngine(v0=200, lot_size=100)

    # 1. Khớp một phần Cấp 1 (100 cp / 200 cp)
    r1 = engine.execute_buy(price=50000.0, volume=100)
    assert r1.success
    assert r1.level == 1
    assert r1.volume == 100
    pos1 = engine.positions[1]
    assert pos1.status == "PARTIALLY_FILLED"
    assert pos1.volume == 100

    # 2. Ở nhịp tiếp theo, hệ thống tiếp tục ưu tiên lấp đầy phần thiếu của Cấp 1 thay vì nhảy sang Cấp 2
    assert engine.get_next_buy_level() == 1
    r2 = engine.execute_buy(price=49000.0, volume=100)
    assert r2.success
    assert r2.level == 1
    assert r2.volume == 100
    # VWAP = (100 * 50000 + 100 * 49000) / 200 = 49,500
    assert pos1.entry_price == 49500.0
    assert pos1.volume == 200
    assert pos1.status == "ACTIVE"

    # 3. Sau khi Cấp 1 đã ACTIVE, cấp tiếp theo được mở khóa là Cấp 2
    assert engine.get_next_buy_level() == 2


def test_partial_sell_and_closing_partial_lifecycle():
    engine = FibonacciExecuteEngine(v0=200, lot_size=100)
    engine.execute_buy(price=50000.0)  # L1: 200 cp @ 50,000
    engine.execute_buy(price=48000.0)  # L2: 200 cp @ 48,000

    # Bán chốt lời một phần L2 (100 cp / 200 cp @ 52,000)
    r_sell_part = engine.execute_sell(price=52000.0, volume=100)
    assert r_sell_part.success
    assert r_sell_part.level == 2
    assert r_sell_part.volume == 100
    pos2 = engine.positions[2]
    assert pos2.status == "CLOSING_PARTIAL"
    assert pos2.volume == 100
    # Giá vốn P_VWAP giữ nguyên
    assert pos2.entry_price == 48000.0

    # Tiếp tục bán phần còn lại của L2
    assert engine.get_highest_sell_level() == 2
    r_sell_full = engine.execute_sell(price=52000.0, volume=100)
    assert r_sell_full.success
    assert r_sell_full.level == 2
    assert 2 not in engine.positions

    # Lần bán tiếp theo sẽ ưu tiên sang L1
    assert engine.get_highest_sell_level() == 1


def test_apply_fill_broker_direct_integration():
    engine = FibonacciExecuteEngine(v0=100)
    # Broker fill Buy 100 cp L1 @ 50,000
    res_fill = engine.apply_fill(level=1, action="BUY", filled_volume=100, fill_price=50000.0, fill_fee=75.0)
    assert res_fill.success
    assert engine.total_holding_shares == 100
    assert engine.positions[1].volume == 100
    assert engine.positions[1].status == "ACTIVE"

    # Broker fill Sell 100 cp L1 @ 53,000
    res_sell = engine.apply_fill(level=1, action="SELL", filled_volume=100, fill_price=53000.0)
    assert res_sell.success
    assert engine.total_holding_shares == 0
    assert 1 not in engine.positions
    assert engine.surplus > 0


def test_k_argument_gate_and_zero_argument_hard_lock():
    engine = FibonacciExecuteEngine(v0=100)
    # 1. K = 3: Cho phép mở tối đa 3 cấp L1, L2, L3
    engine.update_theses_count(3)
    assert engine.execute_buy(price=50000.0).success  # L1 (100)
    assert engine.execute_buy(price=48000.0).success  # L2 (100)
    assert engine.execute_buy(price=46000.0).success  # L3 (200)

    # Thử mua cấp 4 khi K = 3 -> Bị chặn
    r4_blocked = engine.execute_buy(price=44000.0)
    assert not r4_blocked.success
    assert "Đã mở tối đa 3 cấp lệnh cho phép theo K=3" in r4_blocked.reason

    # 2. Số luận điểm suy giảm: K sụt từ 3 xuống 1
    # Hệ thống tự động chuyển L3, L2 sang PENDING_EXIT và nạp C_sell = 300
    engine.update_theses_count(1)
    assert engine.sub_accounts[3].status == "PENDING_EXIT"
    assert engine.sub_accounts[2].status == "PENDING_EXIT"
    assert engine.pending_sell_volume == 300

    # 3. Chốt chặn số 0 (Zero-Argument Hard Lock): K = 0
    engine.update_theses_count(0)
    assert engine.current_theses_count == 0
    assert engine.pending_buy_volume == 0
    r_buy_k0 = engine.execute_buy(price=40000.0)
    assert not r_buy_k0.success
    assert "Chốt chặn số 0" in r_buy_k0.reason


def test_liquidity_maximizing_lot_selection_highest_entry_price_first():
    # Kiểm tra thuật toán bốc Lô: Ưu tiên bán lô có giá vốn cao nhất trước
    engine = FibonacciExecuteEngine(v0=100)
    engine.execute_buy(price=48000.0)  # L1: 100 cp @ 48,000
    engine.execute_buy(price=46000.0)  # L2: 100 cp @ 46,000

    # Giá thị trường tăng lên 50,000 (cả 2 lô đều có lãi)
    # Hệ thống bốc lô có giá vốn cao nhất (48,000) bán trước, giữ lại lô an toàn (46,000)
    eligible = engine.get_eligible_lots_to_sell(price=50000.0)
    assert len(eligible) == 2
    assert eligible[0].entry_price == 48000.0
    assert eligible[1].entry_price == 46000.0

    r_sell = engine.execute_sell(price=50000.0, volume=100)
    assert r_sell.success
    # Lô 48,000 đã được bán hết, trong kho chỉ còn lại lô 46,000
    assert len(engine.lot_pool) == 1
    assert engine.lot_pool[0].entry_price == 46000.0


def test_t_plus_settlement_and_emergency_defensive_lock():
    # Chu kỳ thanh toán bù trừ T+2
    engine = FibonacciExecuteEngine(v0=100, settlement_cycle_days=2)

    # Day 0: Khớp mua 100 cp -> Lô ở trạng thái T0_MATCHED (chưa khả dụng)
    engine.execute_buy(price=50000.0)
    assert engine.total_holding_shares == 100
    assert engine.total_tradable_shares == 0
    assert engine.lot_pool[0].settlement_status == "T0_MATCHED"

    # Thử bán ngay trong ngày T+0 -> Bị chặn vì hàng chưa về
    r_sell_t0 = engine.execute_sell(price=52000.0)
    assert not r_sell_t0.success
    assert "chưa hoàn tất thanh toán T+" in r_sell_t0.reason

    # K rơi về 0 khi hàng chưa về (V_tradable = 0) -> Kích hoạt EMERGENCY_DEFENSIVE_LOCK
    engine.update_theses_count(0)
    assert engine.emergency_defensive_lock
    assert engine.sub_accounts[1].status == "PENDING_EXIT"

    # Chuyển sang Day 1 (T+1): Vẫn chưa khả dụng
    engine.advance_settlement("2023-01-02")
    assert engine.total_tradable_shares == 0
    assert engine.lot_pool[0].settlement_status == "T1_PENDING"
    assert engine.emergency_defensive_lock

    # Chuyển sang Day 2 (T+2): Hàng về (SETTLED_AVAILABLE) -> Tự động mở khóa phòng vệ
    engine.advance_settlement("2023-01-03")
    assert engine.total_tradable_shares == 100
    assert engine.lot_pool[0].settlement_status == "SETTLED_AVAILABLE"
    assert not engine.emergency_defensive_lock
    assert engine.pending_sell_volume >= 100

    # Thực hiện thanh lý thành công ở T+2
    r_sell_t2 = engine.execute_sell(price=52000.0)
    assert r_sell_t2.success
    assert engine.total_holding_shares == 0
