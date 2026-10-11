from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any, Sequence

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from src.strategies.indicators.candlestick import CandlestickPatternDetector, CandlestickSignal
from src.strategies.indicators.dmi import DirectionalMovementIndex
from src.strategies.indicators.linear import LinearRegressionChannel
from src.strategies.indicators.sma import RollingStatistics


@dataclass(frozen=True)
class TargetPoint:
    """Mức giá mục tiêu lượng hóa từ mô hình hồi quy hoặc thống kê."""
    model: str    # "LRC" | "SMA"
    p: float      # Hệ số mức chiến lược (ví dụ: -2.0, 0.0, 1.144, 2.0)
    value: float  # Mức giá cụ thể


@dataclass
class ReversalSnapshot:
    """Ảnh chụp chi tiết trạng thái tín hiệu tại một phiên giao dịch."""
    signal: int                         # -1: Đảo chiều giảm, 1: Đảo chiều tăng, 0: Không tín hiệu
    trend: int                          # -1: Downtrend, 1: Uptrend, 0: Chưa xác định
    price: float                        # Giá đóng cửa / giá kiểm tra
    atr: float                          # Giá trị ATR tại phiên
    is_in_support: bool                 # Giá đang nằm trong vùng hỗ trợ
    is_in_resistance: bool              # Giá đang nằm trong vùng kháng cự
    active_support: float | None        # Mức hỗ trợ cụ thể đang kích hoạt (St)
    active_resistance: float | None     # Mức kháng cự cụ thể đang kích hoạt (Rt)
    support_zone: tuple[float, float] | None        # Vùng [S, S + ATR/2]
    resistance_zone: tuple[float, float] | None     # Vùng [R - ATR/2, R]
    candlestick_pattern: str            # Tên mô hình nến nhận diện được
    candle_bullish: bool                # Nến đảo chiều tăng
    candle_bearish: bool                # Nến đảo chiều giảm
    dmi_bullish: bool                   # DMI đảo chiều tăng
    dmi_bearish: bool                   # DMI đảo chiều giảm
    reason: str                         # Giải thích chi tiết tín hiệu
    regime: str = ""                    # {model_St}{p_St}|{model_Rt}{p_Rt} ví dụ: SMA-2|LRC-2
    signal_dmi: int = 0                 # Tín hiệu phát sinh từ DMI (0 hoặc 1)
    trend_dmi: int = 0                  # Hướng xu hướng từ DMI (-1, 0, 1)
    change_rate_dmi: int = 0            # Tốc độ chuyển đổi từ DMI (0 hoặc 1)
    signal_sr: int = 0                  # Tín hiệu phát sinh từ Hỗ trợ/Kháng cự (0 hoặc 1)
    trend_sr: int = 0                   # Hướng xu hướng từ Hỗ trợ/Kháng cự (-1, 0, 1)
    change_rate_sr: int = 0             # Tốc độ chuyển đổi từ Hỗ trợ/Kháng cự (0 hoặc 1)
    change_rate: int = 0                # Tổng tốc độ chuyển đổi = change_rate_dmi + change_rate_sr


class SupportResistanceReversalIndicator(Indicator):
    """
    Chỉ báo kết hợp DMI, Linear Regression Channel (LRC) và SMA.
    Vai trò kiểm soát tín hiệu, hướng và tốc độ chuyển đổi (cổ phiếu sang tiền mặt, tiền mặt sang cổ phiếu).

    Nguyên lý cốt lõi:
    ------------------
    1. Hỗ trợ và Kháng cự từ Target Points:
       - LinearRegressionChannel cung cấp: target_linear(p) = baseline + p * RMSE
       - RollingStatistics (SMA) cung cấp: target_sma(p) = mean + p * STD
       - Mặc định:
         * Hỗ trợ (Support): các target points
         * Kháng cự (Resistance): các target points
         * Mức Hỗ trợ hiện hành (St): target point gần nhất và nhỏ hơn giá
         * Mức kháng cự hiện hành (Rt): target point gần nhất và lớn hơn giá
         * regime: {model_St}{p_St}|{model_Rt}{p_Rt} (ví dụ: SMA-2|LRC-2)
         * Tự động +/- 1 nếu giá vượt khỏi vùng strategic levels [-2, 2]

    2. Vùng Hỗ trợ & Kháng cự theo ATR:
       - Vùng hỗ trợ  = [hỗ trợ, hỗ trợ + ATR/2]
       - Vùng kháng cự = [kháng cự - ATR/2, kháng cự]

    3. Quy tắc phát sinh tín hiệu Đảo chiều:

       # --- DMI ------------------------------------------------------------
       - Khi có tín hiệu đảo chiều tăng -> giảm (DMI bearish):
         * signal_dmi = 1
         * trend_dmi  = -1 (hoặc bearish_trend_val)
         * change_rate_dmi = 1
       - Khi có tín hiệu đảo chiều giảm -> tăng (DMI bullish):
         * signal_dmi = 1
         * trend_dmi  = 1 (hoặc bullish_trend_val)
         * change_rate_dmi = 1
       - Nếu không có tín hiệu đảo chiều:
         * signal_dmi = 0
         * trend_dmi  = trend cũ (giữ nguyên giá trị trước đó)
         * change_rate_dmi = 0
       # ---------------------------------------------------------------------

       # --- Support/resistance ----------------------------------------------
       - Khi giá low | close trong vùng hỗ trợ:
         (trường hợp low ở kháng cự, close ở hỗ trợ -> ưu tiên close)
         (trường hợp close ở vùng ngoài, low ở hỗ trợ -> ưu tiên low)
         * signal_sr = 1
         * trend_sr  = 1 (hoặc bullish_trend_val)
         * change_rate_sr = 1
       - Khi giá high | close trong vùng kháng cự:
         (trường hợp high ở hỗ trợ, close ở kháng cự -> ưu tiên close)
         (trường hợp close ở vùng ngoài, high ở kháng cự -> ưu tiên high)
         * signal_sr = 1
         * trend_sr  = -1 (hoặc bearish_trend_val)
         * change_rate_sr = 1
       - Khi không thuộc vùng nào:
         * signal_sr = 0
         * trend_sr  = trend cũ (giữ nguyên giá trị trước đó)
         * change_rate_sr = 0
       # ---------------------------------------------------------------------

         * change_rate = change_rate_dmi + change_rate_sr
         * signal = max(signal_dmi, signal_sr) có gắn hướng (+1 hoặc -1)
         * trend = (trend_dmi + trend_sr) / abs(trend_dmi + trend_sr) (nếu đồng thuận; giữ trend cũ nếu xung đột)
    """

    def __init__(
        self,
        linear_window: int | None = None,
        linear_k: float = 5.0,
        sma_window: int | None = 1500,
        dmi_period: int = 14,
        adx_period: int = 14,
        adx_peak_threshold: float = 35.0,
        hl_base: float = 7.0,
        soft_c: float = 25.0,
        alpha_mode: str = "half_life",
        atr_period: int = 14,
        atr_multiplier: float = 1.0,
        strategic_levels: Sequence[float] = (
            2.0,
            1.144,
            0.472,
            0.0,
            -0.472,
            -1.144,
            -2.0,
        ),
        target_mode: str = "strategic",
        use_dmi_filter: bool = True,
        price_touch_mode: str = "close",
        bullish_trend_val: int = 1,
        bearish_trend_val: int = -1,
        expanding: bool = False,
        linear_expanding: bool | None = None,
        sma_expanding: bool | None = None,
    ):
        super().__init__([
            linear_window if (linear_window is not None and linear_window > 0) else 0,
            sma_window if (sma_window is not None and sma_window > 0) else 0,
            dmi_period,
            atr_period,
        ])

        eff_sma_window = min(int(sma_window), 1500) if sma_window is not None else 1500
        eff_linear_expanding = linear_expanding if linear_expanding is not None else (expanding or linear_window is None)
        eff_sma_expanding = sma_expanding if sma_expanding is not None else False

        self.linear_window = linear_window
        self.linear_k = float(linear_k)
        self.sma_window = eff_sma_window
        self.linear_expanding = eff_linear_expanding
        self.sma_expanding = eff_sma_expanding
        self.dmi_period = dmi_period
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.atr_multiplier = float(atr_multiplier)
        self.strategic_levels = tuple(strategic_levels)
        self.target_mode = target_mode
        self.use_dmi_filter = use_dmi_filter
        self.price_touch_mode = price_touch_mode
        self.bullish_trend_val = bullish_trend_val
        self.bearish_trend_val = bearish_trend_val
        self.expanding = expanding

        # -------------------------------------------------------------
        # Khởi tạo các sub-indicators
        # -------------------------------------------------------------
        self.linear = LinearRegressionChannel(
            window=linear_window if not eff_linear_expanding else None,
            strategic_levels=strategic_levels,
            k=linear_k,
            expanding=eff_linear_expanding,
        )
        self.sma = RollingStatistics(
            window=eff_sma_window,
            strategic_levels=strategic_levels,
            expanding=eff_sma_expanding,
        )
        self.dmi = DirectionalMovementIndex(
            period=dmi_period,
            adx_period=adx_period,
            adx_peak_threshold=adx_peak_threshold,
            hl_base=hl_base,
            soft_c=soft_c,
            alpha_mode=alpha_mode,
        )
        self.candlestick_detector = CandlestickPatternDetector()

        # -------------------------------------------------------------
        # Quản lý ATR nội bộ (Wilder True Range)
        # -------------------------------------------------------------
        self._prev_open: float | None = None
        self._prev_close: float | None = None
        self._smoothed_tr: float = 0.0
        self._tr_history: deque[float] = deque(maxlen=atr_period)
        self._atr: float = 0.0
        self._count: int = 0

        # -------------------------------------------------------------
        # Trạng thái tín hiệu và xu hướng
        # -------------------------------------------------------------
        self.signal: int = 0
        self.trend: int = 0
        self.prev_signal: int = 0
        self.prev_trend: int = 0
        self.prev_trend_dmi: int = 0
        self.prev_trend_sr: int = 0
        self.change_rate: int = 0
        self._last_snapshot: ReversalSnapshot | None = None

    # ==================================================================
    # Public properties
    # ==================================================================

    @property
    def value(self) -> float:
        """Giá trị indicator chính trả về xu hướng hiện tại."""
        return float(self.trend)

    @property
    def atr(self) -> float:
        """Giá trị ATR hiện tại."""
        return self._atr

    @property
    def count(self) -> int:
        """Số lượng bar đã nạp vào chỉ báo."""
        return self._count

    @property
    def is_bullish(self) -> bool:
        """Đang ở xu hướng tăng (trend == 1)."""
        return self.trend == self.bullish_trend_val

    @property
    def is_bearish(self) -> bool:
        """Đang ở xu hướng giảm (trend == -1)."""
        return self.trend == self.bearish_trend_val

    @property
    def is_buy_signal(self) -> bool:
        """Có tín hiệu Mua / Đảo chiều tăng tại phiên này."""
        return self.signal == 1

    @property
    def is_sell_signal(self) -> bool:
        """Có tín hiệu Bán / Đảo chiều giảm tại phiên này."""
        return self.signal == -1

    @property
    def snapshot(self) -> ReversalSnapshot | None:
        """Snapshot chi tiết của phiên gần nhất."""
        return self._last_snapshot
    def compute_target_points(self, price: float | None = None) -> list[TargetPoint]:
        """
        Tính toán toàn bộ target points từ các mô hình đã khởi tạo (LinearRegressionChannel và SMA).
        Nếu mô hình chưa initialized, dùng fallback scale theo biến động thực tế (ATR / 2% giá).
        """
        ref_price = price if (price is not None and math.isfinite(price)) else (self._prev_close or 100.0)
        tps: list[TargetPoint] = []

        if self.linear.initialized:
            base_lrc = self.linear.baseline
            rmse_lrc = max(self.linear.rmse, 1e-6)
            for p in self.strategic_levels:
                tps.append(TargetPoint(model="LRC", p=p, value=base_lrc + p * rmse_lrc))
            tps.append(TargetPoint(model="LRC", p=0.0, value=base_lrc))

        if self.sma.initialized:
            mean_sma = self.sma.mean
            std_sma = max(self.sma.std, 1e-6)
            for p in self.strategic_levels:
                tps.append(TargetPoint(model="SMA", p=p, value=mean_sma + p * std_sma))
            tps.append(TargetPoint(model="SMA", p=0.0, value=mean_sma))

        if not tps:
            fallback_scale = max(self.atr * self.atr_multiplier, ref_price * 0.02)
            for p in self.strategic_levels:
                tps.append(TargetPoint(model="REF", p=p, value=ref_price + p * fallback_scale))
            tps.append(TargetPoint(model="REF", p=0.0, value=ref_price))

        tps.sort(key=lambda x: x.value)
        return tps

    def get_closest_support_info(self, price: float) -> TargetPoint:
        """Target point gần giá nhất và nhỏ hơn giá là Support (St). Luôn bảo đảm St < price."""
        tps = self.compute_target_points(price)
        below = [tp for tp in tps if tp.value < price]
        if below:
            return below[-1]
        fallback_atr = max(self.atr * self.atr_multiplier, price * 0.02)
        return TargetPoint(model="FLOOR", p=-3.0, value=price - fallback_atr)

    def get_closest_resistance_info(self, price: float) -> TargetPoint:
        """Target point gần giá nhất và lớn hơn giá là Kháng cự (Rt). Luôn bảo đảm Rt > price."""
        tps = self.compute_target_points(price)
        above = [tp for tp in tps if tp.value > price]
        if above:
            return above[0]
        fallback_atr = max(self.atr * self.atr_multiplier, price * 0.02)
        return TargetPoint(model="CEIL", p=3.0, value=price + fallback_atr)

    def get_closest_support(self, price: float) -> float:
        """Mức giá Hỗ trợ hiện hành (St)."""
        return self.get_closest_support_info(price).value

    def get_closest_resistance(self, price: float) -> float:
        """Mức giá Kháng cự hiện hành (Rt)."""
        return self.get_closest_resistance_info(price).value

    def get_regime(self, price: float) -> str:
        """Chuỗi regime định danh dạng: {model_St}{p_St}|{model_Rt}{p_Rt} (ví dụ: SMA-2|LRC-2)."""
        st_info = self.get_closest_support_info(price)
        rt_info = self.get_closest_resistance_info(price)
        return f"{st_info.model}{st_info.p:g}|{rt_info.model}{rt_info.p:g}"

    def get_clean_zones(self, price: float) -> tuple[float, float, float, float]:
        """
        Tính toán 4 ngưỡng có thứ tự bất biến:
        S <= buy_threshold < price < sell_threshold <= R

        Returns:
            (support_s, buy_threshold, sell_threshold, resistance_r)
        """
        st_info = self.get_closest_support_info(price)
        rt_info = self.get_closest_resistance_info(price)
        s = st_info.value
        r = rt_info.value

        fallback_atr = max(self.atr * self.atr_multiplier, price * 0.02)
        if s >= price:
            s = price - fallback_atr
        if r <= price:
            r = price + fallback_atr

        gap = r - s
        dist_s = max(price - s, 1e-4)
        dist_r = max(r - price, 1e-4)
        atr_scaled = max(self.atr * self.atr_multiplier, 1e-4)

        delta_s = min(atr_scaled, dist_s * 0.5, gap * 0.25)
        delta_r = min(atr_scaled, dist_r * 0.5, gap * 0.25)

        s_upper = s + delta_s
        r_lower = r - delta_r

        return s, s_upper, r_lower, r

    @property
    def all_target_points(self) -> list[float]:
        """Tất cả các target points từ Linear Regression Channel và SMA."""
        tps = self.compute_target_points(self._prev_close or 100.0)
        return sorted({tp.value for tp in tps if math.isfinite(tp.value)})

    @property
    def support_levels(self) -> list[float]:
        """Danh sách các ngưỡng hỗ trợ từ Linear Regression và SMA."""
        if self.target_mode == "strategic":
            return sorted(set(tp.value for tp in self.compute_target_points() if tp.p <= 0.0 and math.isfinite(tp.value)))
        return self.all_target_points

    @property
    def resistance_levels(self) -> list[float]:
        """Danh sách các ngưỡng kháng cự từ Linear Regression và SMA."""
        if self.target_mode == "strategic":
            return sorted(set(tp.value for tp in self.compute_target_points() if tp.p >= 0.0 and math.isfinite(tp.value)))
        return self.all_target_points

    @property
    def support_zones(self) -> list[tuple[float, float]]:
        """Danh sách các vùng hỗ trợ: [hỗ trợ, hỗ trợ + ATR]."""
        eff_atr = self.atr * self.atr_multiplier
        return [(s, s + eff_atr) for s in self.support_levels]

    @property
    def resistance_zones(self) -> list[tuple[float, float]]:
        """Danh sách các vùng kháng cự: [kháng cự - ATR, kháng cự]."""
        eff_atr = self.atr * self.atr_multiplier
        return [(r - eff_atr, r) for r in self.resistance_levels]

    def get_active_support(
        self,
        price: float,
        low_p: float | None = None,
    ) -> tuple[float, float, float] | None:
        """
        Kiểm tra giá có nằm trong vùng hỗ trợ [S, S + ATR] hay không.
        Returns:
            (support_level, lower_bound, upper_bound) nếu chạm vùng, ngược lại None.
        """
        zone_atr = self.atr * self.atr_multiplier
        if zone_atr <= 0.0 or not math.isfinite(price):
            return None

        for s in self.support_levels:
            lower = s
            upper = s + zone_atr
            if lower <= price <= upper + 1e-9:
                return (s, lower, upper)
            if self.price_touch_mode == "range" and low_p is not None:
                if lower - 0.2 * zone_atr <= low_p <= upper + 1e-9:
                    return (s, lower, upper)

        return None

    def get_active_resistance(
        self,
        price: float,
        high_p: float | None = None,
    ) -> tuple[float, float, float] | None:
        """
        Kiểm tra giá có nằm trong vùng kháng cự [R - ATR, R] hay không.
        Returns:
            (resistance_level, lower_bound, upper_bound) nếu chạm vùng, ngược lại None.
        """
        zone_atr = self.atr * self.atr_multiplier
        if zone_atr <= 0.0 or not math.isfinite(price):
            return None

        for r in self.resistance_levels:
            lower = r - zone_atr
            upper = r
            if lower - 1e-9 <= price <= upper:
                return (r, lower, upper)
            if self.price_touch_mode == "range" and high_p is not None:
                if lower - 1e-9 <= high_p <= upper + 0.2 * zone_atr:
                    return (r, lower, upper)

        return None

    def is_in_support_zone(self, price: float, low_p: float | None = None) -> bool:
        """True nếu giá đang ở trong vùng hỗ trợ [S, S + ATR/2]."""
        return self.get_active_support(price, low_p=low_p) is not None

    def is_in_resistance_zone(self, price: float, high_p: float | None = None) -> bool:
        """True nếu giá đang ở trong vùng kháng cự [R - ATR/2, R]."""
        return self.get_active_resistance(price, high_p=high_p) is not None

    # ==================================================================
    # Data handling
    # ==================================================================

    def handle_bar(self, bar: Bar) -> None:
        zone_atr = max(self._atr * self.atr_multiplier, 1e-6)
        self.update_raw(
            open_p=bar.open.as_double(),
            high_p=bar.high.as_double(),
            low_p=bar.low.as_double(),
            close_p=bar.close.as_double(),
            volume=bar.volume.as_double() if hasattr(bar, "volume") else 0.0,
        )

    def handle_quote_tick(self, tick: Any) -> None:
        pass

    def handle_trade_tick(self, tick: Any) -> None:
        pass

    def update_raw(
        self,
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        volume: float = 0.0,
        atr: float | None = None,
    ) -> ReversalSnapshot:
        """
        Cập nhật dữ liệu nến mới và sinh tín hiệu đảo chiều theo quy tắc:
        1. Hỗ trợ & Kháng cự từ Target Points (St, Rt, regime).
        2. Vùng [St, St + ATR/2] và [Rt - ATR/2, Rt].
        3. Quy tắc ưu tiên Close / Low / High và tổng hợp DMI + SR.
        """
        open_p = float(open_p)
        high_p = float(high_p)
        low_p = float(low_p)
        close_p = float(close_p)
        self._count += 1

        # -------------------------------------------------------------
        # 1. Cập nhật ATR (Wilder True Range)
        # -------------------------------------------------------------
        if self._prev_close is not None:
            tr = max(
                high_p - low_p,
                abs(high_p - self._prev_close),
                abs(low_p - self._prev_close),
            )
        else:
            tr = high_p - low_p

        self._tr_history.append(tr)

        if self._count <= self.atr_period:
            self._smoothed_tr += tr
            self._atr = self._smoothed_tr / max(self._count, 1)
        else:
            self._smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self.atr_period) + tr
            self._atr = self._smoothed_tr / self.atr_period

        if atr is not None and math.isfinite(float(atr)):
            self._atr = float(atr)

        zone_atr = max(self._atr * self.atr_multiplier, 1e-6)
        # -------------------------------------------------------------
        # 2. Cập nhật DMI và phát hiện mô hình nến đảo chiều
        # -------------------------------------------------------------
        self.dmi.update_raw(high=high_p, low=low_p, close=close_p)

        candle_signal = self.candlestick_detector.analyze(
            open_p=open_p,
            high_p=high_p,
            low_p=low_p,
            close_p=close_p,
            prev_open=self._prev_open,
            prev_close=self._prev_close,
        )
        candle_bullish = candle_signal.is_bullish
        candle_bearish = candle_signal.is_bearish

        # -------------------------------------------------------------
        # 3. Xác định St, Rt, regime và vùng [St, St + zone_atr], [Rt - zone_atr, Rt]
        # -------------------------------------------------------------
        st_val, s_upper, r_lower, rt_val = self.get_clean_zones(close_p)
        support_zone = (st_val, s_upper)
        resistance_zone = (r_lower, rt_val)
        regime = self.get_regime(close_p)

        # -------------------------------------------------------------
        # 4. Kiểm tra vị trí giá so với Vùng Hỗ trợ / Kháng cự (Quy tắc ưu tiên)
        # -------------------------------------------------------------
        is_range_mode = (self.price_touch_mode == "range")
        close_in_sup = (st_val <= close_p <= s_upper + 1e-9)
        close_in_res = (r_lower - 1e-9 <= close_p <= rt_val)
        low_in_sup = is_range_mode and (st_val - 0.2 * (s_upper - st_val) <= low_p <= s_upper + 1e-9)
        high_in_res = is_range_mode and (r_lower - 1e-9 <= high_p <= rt_val + 0.2 * (rt_val - r_lower))

        is_in_support = close_in_sup or low_in_sup or self.is_in_support_zone(close_p, low_p=low_p if is_range_mode else None)
        is_in_resistance = close_in_res or high_in_res or self.is_in_resistance_zone(close_p, high_p=high_p if is_range_mode else None)

        # -------------------------------------------------------------
        # 4. Kiểm tra vị trí giá so với Vùng Hỗ trợ / Kháng cự (Quy tắc ưu tiên)
        # -------------------------------------------------------------
        is_range_mode = (self.price_touch_mode == "range")
        is_in_support = self.is_in_support_zone(close_p, low_p=low_p if is_range_mode else None)
        is_in_resistance = self.is_in_resistance_zone(close_p, high_p=high_p if is_range_mode else None)

        # Xử lý trường hợp chạm đồng thời cả hai vùng: ưu tiên theo nến hoặc khoảng cách
        if is_in_support and is_in_resistance:
            if candle_bullish and not candle_bearish:
                is_in_resistance = False
            elif candle_bearish and not candle_bullish:
                is_in_support = False
            else:
                dist_s = abs(close_p - st_val)
                dist_r = abs(rt_val - close_p)
                if dist_s <= dist_r:
                    is_in_resistance = False
                else:
                    is_in_support = False

        # -------------------------------------------------------------
        # 5. Logic nến đảo chiều & DMI
        # -------------------------------------------------------------
        if self.use_dmi_filter:
            dmi_bullish = self.dmi.check_buy_reversal_signal(candle_bullish)
            dmi_bearish = self.dmi.check_sell_reversal_signal(candle_bearish)
        else:
            dmi_bullish = self.dmi.is_raw_buy_reversal()
            dmi_bearish = self.dmi.is_raw_sell_reversal()

        # -------------------------------------------------------------
        # 6. Tổng hợp tín hiệu, hướng và tốc độ chuyển đổi (DMI + SR)
        # -------------------------------------------------------------
        signal_dmi = 0
        trend_dmi = self.trend
        change_rate_dmi = 0

        signal_sr = 0
        trend_sr = self.trend
        change_rate_sr = 0

        reversal_bullish = candle_bullish or dmi_bullish
        reversal_bearish = candle_bearish or dmi_bearish

        if reversal_bullish and is_in_support:
            final_signal = 1
            final_trend = self.bullish_trend_val  # 1
            signal_sr = 1
            trend_sr = 1
            change_rate_sr = 1
            if dmi_bullish:
                signal_dmi = 1
                trend_dmi = 1
                change_rate_dmi = 1
            trigger_src = []
            if candle_bullish:
                trigger_src.append(f"Candle: {candle_signal.pattern}")
            if dmi_bullish:
                trigger_src.append("DMI Bullish")
            reason = f"Đảo chiều TĂNG tại Vùng Hỗ trợ ({' + '.join(trigger_src)} | {regime})"
        elif reversal_bearish and is_in_resistance:
            final_signal = -1
            final_trend = self.bearish_trend_val  # -1
            signal_sr = 1
            trend_sr = -1
            change_rate_sr = 1
            if dmi_bearish:
                signal_dmi = 1
                trend_dmi = -1
                change_rate_dmi = 1
            trigger_src = []
            if candle_bearish:
                trigger_src.append(f"Candle: {candle_signal.pattern}")
            if dmi_bearish:
                trigger_src.append("DMI Bearish")
            reason = f"Đảo chiều GIẢM tại Vùng Kháng cự ({' + '.join(trigger_src)} | {regime})"
        else:
            final_signal = 0
            final_trend = self.trend
            if reversal_bullish and not is_in_support:
                reason = f"Có tín hiệu đảo chiều tăng nhưng không nằm trong vùng hỗ trợ ({regime})"
            elif reversal_bearish and not is_in_resistance:
                reason = f"Có tín hiệu đảo chiều giảm nhưng không nằm trong vùng kháng cự ({regime})"
            else:
                reason = f"Không có tín hiệu đảo chiều ({regime})"

        change_rate = change_rate_dmi + change_rate_sr

        # -------------------------------------------------------------
        # 7. Cập nhật Linear và SMA sau khi đã đánh giá phiên này
        # -------------------------------------------------------------
        self.linear.update_raw(close_p)
        self.sma.update_raw(close_p)
        self.prev_signal = self.signal
        self.prev_trend = self.trend
        self.signal = final_signal
        self.trend = final_trend
        self.prev_trend_dmi = trend_dmi
        self.prev_trend_sr = trend_sr
        self.change_rate = change_rate
        self._prev_open = open_p
        self._prev_close = close_p

        # Nautilus Trader lifecycle
        self._set_has_inputs(True)
        min_init_bars = max(
            self.linear_window or 2,
            self.sma_window or 2,
            self.dmi_period,
            self.atr_period,
        )
        if (self._count >= min_init_bars and self.linear.initialized and self.sma.initialized) or (
            self.linear.initialized and self.sma.initialized and self.dmi.initialized
        ):
            self._set_initialized(True)

        snapshot = ReversalSnapshot(
            signal=self.signal,
            trend=self.trend,
            price=close_p,
            atr=self._atr,
            is_in_support=is_in_support,
            is_in_resistance=is_in_resistance,
            active_support=st_val,
            active_resistance=rt_val,
            support_zone=support_zone,
            resistance_zone=resistance_zone,
            candlestick_pattern=candle_signal.pattern,
            candle_bullish=candle_bullish,
            candle_bearish=candle_bearish,
            dmi_bullish=dmi_bullish,
            dmi_bearish=dmi_bearish,
            reason=reason,
            regime=regime,
            signal_dmi=signal_dmi,
            trend_dmi=trend_dmi,
            change_rate_dmi=change_rate_dmi,
            signal_sr=signal_sr,
            trend_sr=trend_sr,
            change_rate_sr=change_rate_sr,
            change_rate=change_rate,
        )
        self._last_snapshot = snapshot
        return snapshot

    # ==================================================================
    # Reset
    # ==================================================================

    def _reset(self) -> None:
        """Khôi phục toàn bộ trạng thái chỉ báo."""
        self.linear._reset()
        self.sma._reset()
        self.dmi._reset()
        self._prev_open = None
        self._prev_close = None
        self._smoothed_tr = 0.0
        self._tr_history.clear()
        self._atr = 0.0
        self._count = 0
        self.signal = 0
        self.trend = 0
        self.prev_signal = 0
        self.prev_trend = 0
        self.prev_trend_dmi = 0
        self.prev_trend_sr = 0
        self.change_rate = 0
        self._last_snapshot = None


# Alias thuận tiện
ReversalIndicator = SupportResistanceReversalIndicator
