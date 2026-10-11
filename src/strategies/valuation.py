from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass
import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.strategies.indicators.beta import MultivariateLinearRegression
from src.strategies.indicators.dmi import DirectionalMovementIndex
from src.strategies.indicators.linear import LinearRegressionChannel
from src.strategies.indicators.reversal import SupportResistanceReversalIndicator, ReversalSnapshot
from src.strategies.indicators.sma import RollingStatistics, sigmoid


@dataclass
class ValuationSnapshot:
    """Ảnh chụp dữ liệu định giá và chấm điểm tại một phiên giao dịch."""
    # Các thành phần kỳ vọng
    saving_rate: float

    pr: float
    pt: float
    dividend_yield: float
    expected_return: float  # A = 0.5 * pt + 0.5 * pr + dividend_yield - saving_rate

    # Các chỉ số bổ trợ
    discount: float       # B: Chiết khấu từ ATH
    loser_ratio: float    # C: Tỷ lệ loser 3 năm
    usdvnd_signal: float  # D: Tín hiệu USDVND (-1 * trend_usdvnd)
    eurusd_signal: float  # E: Tín hiệu EURUSD / EURVND (trend_eur)
    dxy_signal: float     # F: Tín hiệu DXY (-1 * trend_dxy)
    price_signal: float  # G: Tín hiệu Price (trend_price)

    # 7 Luận điểm (Scores trong khoảng 0 - 1)
    # Luận điểm bắt buộc
    score_a: float        # Điểm lợi nhuận dự phóng
    score_b: float        # Điểm chiết khấu từ đỉnh lịch sử

    # Luận điểm kích hoạt
    score_c: float        # Điểm tỷ lệ loser 3 năm
    score_d: float        # Điểm tỉ giá USDVND
    score_e: float        # Điểm tỉ giá DXY
    score_f: float        # Điểm tỉ giá EURUSD
    score_g: float       # Điểm xu hướng giá Price (trend(Price))

    theses_count: int     # Số luận điểm đạt (>= 0.5)

    # Kháng cự/ hỗ trợ và ATR
    atr: float

    support: float
    resistance: float

    buy_threshold: float    # support + 1 ATR
    sell_threshold: float   # resistance - 1 ATR

    # Tín hiệu Reversal Indicator
    signal: int = 0         # -1: Đảo chiều giảm, 1: Đảo chiều tăng, 0: Không tín hiệu
    trend: int = 0          # -1: Downtrend, 1: Uptrend, 0: Chưa xác định
    p_suggest: float = 0.0  # Giá cơ sở gợi ý (0.5 * (SMA + LRC))
    active_support: float | None = None
    active_resistance: float | None = None
    plus_di: float = 0.0
    minus_di: float = 0.0
    adx: float = 0.0
    trend_score: float = 0.0

    # --- Backward compatibility aliases / properties ---
    @property
    def pqr(self) -> float:
        return self.pr

    @property
    def pqt(self) -> float:
        return self.pt

    @property
    def u_discount(self) -> float:
        return self.discount

    @property
    def l_loser_ratio(self) -> float:
        return self.loser_ratio

    @property
    def score_u(self) -> float:
        return self.score_b

    @property
    def score_l(self) -> float:
        return self.score_c

    @property
    def score_bp_sma(self) -> float:
        return self.score_d

    @property
    def score_bp_linear(self) -> float:
        return self.score_e

    @property
    def rmse_sma(self) -> float:
        return 0.0

    @property
    def rmse_linear(self) -> float:
        return 0.0


class ExpectedReturnEngine:
    """
    Mô hình tính và chấm điểm 6 luận điểm kết hợp Reversal Indicator.

    Quy trình tính toán:
    -------------------
    - Bước 0: saving_rate = inflation + yield10y
    - Bước 1: Pt từ LinearRegressionChannel của cổ phiếu
    - Bước 2: Pr từ RollingStatistics của cổ phiếu
    - Bước 3: dividend_yield = median(Div 5 năm gần nhất) / Market Cap
    - A = 0.5 * Pt + 0.5 * Pr + dividend_yield - saving_rate
    - B: Chiết khấu từ ATH
    - C: Tỷ lệ loser trong 3 năm
    - D: usdvnd_signal = trend(USDVND) * -1
    - E: eurusd_signal = trend(EURUSD)
    - F: dxy_signal = trend(DXY) * -1
    - G: price_signal = trend(Price)
    - 7 luận điểm: chuẩn hóa z-score và sigmoid về 0 - 1

    Kích thước window:
    - Mô hình tuyến tính: sử dụng toàn bộ dữ liệu (expanding window / không giới hạn deque)
    - Mô hình SMA: khoảng 1500 phiên
    - Z-Score: áp dụng trên chuỗi dừng với cửa sổ dài bao phủ chu kỳ kinh tế
    """

    def __init__(
        self,
        window: int = 30,
        linear_window: int | None = None,
        sma_window: int | None = None,
        beta_window: int | None = None,
        z_score_window: int = 750,
        three_year_window: int = 750,
        dmi_period: int = 14,
        adx_period: int = 14,
        atr_period: int = 14,
        linear_k: float = 5.0,
        atr_multiplier: float = 1.0,
        expanding: bool = False,
    ):
        self.window = window
        self.expanding = bool(expanding)
        self.linear_window = linear_window
        self.sma_window = min(int(sma_window), 1500) if sma_window is not None else 1500
        self.beta_window = beta_window or window
        self.z_score_window = z_score_window
        self.three_year_window = three_year_window
        self.dmi_period = dmi_period
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.linear_k = float(linear_k)
        self.atr_multiplier = float(atr_multiplier)

        # -------------------------------------------------------------
        # 1. Khởi tạo SupportResistanceReversalIndicator cho cổ phiếu P
        # -------------------------------------------------------------
        self.reversal_indicator = SupportResistanceReversalIndicator(
            linear_window=self.linear_window,
            linear_k=self.linear_k,
            sma_window=self.sma_window,
            dmi_period=self.dmi_period,
            adx_period=self.adx_period,
            atr_period=self.atr_period,
            atr_multiplier=self.atr_multiplier,
            linear_expanding=True,  # Chỉ mô hình tuyến tính expand dữ liệu liên tục
            sma_expanding=False,    # SMA cap ở 1500
            expanding=self.expanding,
        )

        self.stock_lrc = self.reversal_indicator.linear
        self.stock_sma = self.reversal_indicator.sma
        self.stock_dmi = self.reversal_indicator.dmi

        # -------------------------------------------------------------
        # 2. Các mô hình xu hướng DMI cho DXY, EURUSD, USDVND
        # -------------------------------------------------------------
        self.dxy_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)
        self.eur_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)
        self.fx_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)

        # -------------------------------------------------------------
        # 3. Beta model (tương thích ngược)
        # -------------------------------------------------------------
        self.beta_model = MultivariateLinearRegression(
            n_features=2,
            window=None if self.expanding else self.beta_window,
            expanding=self.expanding,
            learning_rate=0.02,
        )

        # -------------------------------------------------------------
        # 4. Lưu trữ lịch sử giá để tính ATH, Loser ratio, Z-scores
        # -------------------------------------------------------------
        self._price_history: list[float] = []
        self._sorted_prices: list[float] = []
        self._ath: float = 0.0

        # Z-Score thì tùy chọn theo cấu hình người dùng (hoặc None để expand)
        z_maxlen = int(self.z_score_window) if (self.z_score_window is not None and self.z_score_window > 0) else None
        self._a_history: deque[float] = deque(maxlen=z_maxlen)
        self._b_history: deque[float] = deque(maxlen=z_maxlen)
        self._c_history: deque[float] = deque(maxlen=z_maxlen)
        self._d_history: deque[float] = deque(maxlen=z_maxlen)
        self._e_history: deque[float] = deque(maxlen=z_maxlen)
        self._f_history: deque[float] = deque(maxlen=z_maxlen)
        self._g_history: deque[float] = deque(maxlen=z_maxlen)
        # Theo dõi chu kỳ tiền tệ theo tuần (Weekly Currency Data)
        self._last_fx_week: tuple[int, int] | None = None
        self._last_fx_values: tuple[float, float, float] | None = None

    def update(
        self,
        stock_open: float,
        stock_high: float,
        stock_low: float,
        stock_close: float,
        stock_volume: float,
        shares_outstanding: float,
        dividend_5y_history: Sequence[float],
        eurusd_close: float,
        dxy_close: float,
        usdvnd_close: float,
        inflation_rate: float,
        bond_yield_10y: float,
        date: Any = None,
    ) -> ValuationSnapshot:
        """Cập nhật dữ liệu phiên mới và trả về ValuationSnapshot."""
        stock_open = float(stock_open)
        stock_high = float(stock_high)
        stock_low = float(stock_low)
        stock_close = float(stock_close)

        # -------------------------------------------------------------
        # Bước 0: Tính lãi suất tiết kiệm
        # -------------------------------------------------------------
        inf_val = inflation_rate if inflation_rate < 1.0 else inflation_rate / 100.0
        by_val = bond_yield_10y if bond_yield_10y < 1.0 else bond_yield_10y / 100.0
        saving_rate = inf_val + by_val

        # -------------------------------------------------------------
        # Bước 1 & 2: Cập nhật ReversalIndicator, Pt (LRC) và Pr (SMA)
        # -------------------------------------------------------------
        rev_snap = self.reversal_indicator.update_raw(
            open_p=stock_open,
            high_p=stock_high,
            low_p=stock_low,
            close_p=stock_close,
            volume=stock_volume,
        )
        atr = rev_snap.atr
        pt = self.stock_lrc.premium
        pr = self.stock_sma.premium

        # Cập nhật beta model phụ (cho tương thích ngược)
        self.beta_model.update_raw(stock_close, dxy_close, usdvnd_close)

        # -------------------------------------------------------------
        # Bước 3: Tính lợi suất cổ tức (dividend_yield)
        # -------------------------------------------------------------
        market_cap = max(stock_close * max(shares_outstanding, 1.0), 1e6)
        clean_divs = [float(d) for d in dividend_5y_history if math.isfinite(float(d)) and float(d) >= 0]
        if clean_divs:
            med_div = float(np.median(clean_divs))
            if med_div > 1e6:
                dividend_yield = med_div / market_cap
            else:
                dividend_yield = med_div / max(stock_close, 1.0)
        else:
            dividend_yield = 0.0

        # -------------------------------------------------------------
        # Bước 4: Lợi nhuận kỳ vọng (A)
        # A = 0.5 * Pt + 0.5 * Pr + dividend_yield - saving_rate
        # -------------------------------------------------------------
        expected_return = 0.5 * pt + 0.5 * pr + dividend_yield - saving_rate

        # -------------------------------------------------------------
        # Bước 5: Chiết khấu từ ATH (B)
        # -------------------------------------------------------------
        self._price_history.append(stock_close)
        bisect.insort(self._sorted_prices, stock_close)
        if stock_high > self._ath:
            self._ath = stock_high

        discount = max(0.0, (self._ath - stock_close) / self._ath) if self._ath > 0 else 0.0

        # -------------------------------------------------------------
        # Bước 6: Tỷ lệ loser 3 năm (C)
        # -------------------------------------------------------------
        if self.expanding:
            idx_pos = bisect.bisect_left(self._sorted_prices, stock_close)
            loser_count = len(self._sorted_prices) - idx_pos
            loser_ratio = loser_count / len(self._sorted_prices)
        else:
            recent_prices = self._price_history[-self.three_year_window:]
            if recent_prices:
                loser_count = sum(1 for p in recent_prices if p >= stock_close)
                loser_ratio = loser_count / len(recent_prices)
            else:
                loser_ratio = 0.5

        # -------------------------------------------------------------
        # Bước 7: Tín hiệu vĩ mô / tỷ giá từ DMI (D, E, F)
        # Cập nhật DMI tiền tệ theo chu kỳ tuần (chỉ cập nhật khi bước sang tuần mới hoặc giá tỷ giá thay đổi)
        is_new_currency_bar = False
        if date is not None:
            try:
                dt_val = pd.to_datetime(date)
                w_key = (dt_val.year, int(dt_val.isocalendar()[1]))
                if self._last_fx_week != w_key:
                    is_new_currency_bar = True
                    self._last_fx_week = w_key
            except Exception:
                pass

        curr_fx_vals = (round(float(usdvnd_close), 4), round(float(eurusd_close), 4), round(float(dxy_close), 4))
        if not is_new_currency_bar:
            if self._last_fx_values is None or curr_fx_vals != self._last_fx_values:
                is_new_currency_bar = True

        if is_new_currency_bar:
            self._last_fx_values = curr_fx_vals
            self.dxy_dmi.update_raw(dxy_close * 1.001, dxy_close * 0.999, dxy_close)
            self.eur_dmi.update_raw(eurusd_close * 1.001, eurusd_close * 0.999, eurusd_close)
            self.fx_dmi.update_raw(usdvnd_close * 1.001, usdvnd_close * 0.999, usdvnd_close)

        trend_dxy = self.dxy_dmi.trend_score
        trend_eur = self.eur_dmi.trend_score
        trend_fx = self.fx_dmi.trend_score
        trend_price = self.stock_dmi.trend_score

        usdvnd_signal = -trend_fx
        eurusd_signal = trend_eur
        dxy_signal = -trend_dxy
        price_signal = trend_price

        # -------------------------------------------------------------
        # Bước 8: Chấm điểm 7 Luận điểm qua sigmoid z-score
        # -------------------------------------------------------------
        self._a_history.append(expected_return)
        self._b_history.append(discount)
        self._c_history.append(loser_ratio)
        self._d_history.append(usdvnd_signal)
        self._e_history.append(dxy_signal)
        self._f_history.append(eurusd_signal)
        self._g_history.append(price_signal)
        def _calc_z_score_sigmoid(history: deque[float], current_val: float, invert: bool = False) -> float:
            n_h = len(history)
            if n_h < 3:
                return 0.5
            mean_h = float(np.mean(history))
            std_h = float(np.std(history))
            if std_h <= 1e-12:
                return 0.5
            z = (current_val - mean_h) / std_h
            if invert:
                z = -z
            return sigmoid(z)

        score_a = _calc_z_score_sigmoid(self._a_history, expected_return)
        score_b = _calc_z_score_sigmoid(self._b_history, discount)
        score_c = _calc_z_score_sigmoid(self._c_history, loser_ratio)
        score_d = _calc_z_score_sigmoid(self._d_history, usdvnd_signal)
        score_e = _calc_z_score_sigmoid(self._e_history, dxy_signal)
        score_f = _calc_z_score_sigmoid(self._f_history, eurusd_signal)
        score_g = _calc_z_score_sigmoid(self._g_history, price_signal)

        theses_flags = [
            score_a >= 0.5,
            score_b >= 0.5,
            score_c >= 0.5,
            score_d >= 0.5,
            score_e >= 0.5,
            score_f >= 0.5,
            score_g >= 0.5,
        ]
        theses_count = sum(1 for flag in theses_flags if flag)

        # -------------------------------------------------------------
        # Bước 9: Giá gợi ý, Hỗ trợ, Kháng cự & Ngưỡng mua/bán +/- ATR
        # -------------------------------------------------------------
        p_suggest_sma = self.stock_sma.mean if self.stock_sma.initialized else stock_close
        p_suggest_linear = self.stock_lrc.baseline if self.stock_lrc.initialized else stock_close
        p_suggest = 0.5 * (p_suggest_sma + p_suggest_linear)

        # Tính toán các ngưỡng hỗ trợ, kháng cự và vùng hành động không bao giờ bị đảo ngược
        # Bất biến: support <= buy_threshold < stock_close < sell_threshold <= resistance
        support, buy_threshold, sell_threshold, resistance = self.reversal_indicator.get_clean_zones(stock_close)

        return ValuationSnapshot(
            saving_rate=saving_rate,
            pr=pr,
            pt=pt,
            dividend_yield=dividend_yield,
            expected_return=expected_return,
            discount=discount,
            loser_ratio=loser_ratio,
            usdvnd_signal=usdvnd_signal,
            eurusd_signal=eurusd_signal,
            dxy_signal=dxy_signal,
            price_signal=price_signal,
            score_a=score_a,
            score_b=score_b,
            score_c=score_c,
            score_d=score_d,
            score_e=score_e,
            score_f=score_f,
            score_g=score_g,
            theses_count=theses_count,
            atr=atr,
            support=support,
            resistance=resistance,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            signal=rev_snap.signal,
            trend=rev_snap.trend,
            p_suggest=p_suggest,
            active_support=rev_snap.active_support,
            active_resistance=rev_snap.active_resistance,
            plus_di=self.stock_dmi.plus_di,
            minus_di=self.stock_dmi.minus_di,
            adx=self.stock_dmi.adx,
            trend_score=self.stock_dmi.trend_score,
        )
