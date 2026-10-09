from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass, field
import math
from typing import Sequence

import numpy as np

from src.strategies.indicators.beta import MultivariateLinearRegression
from src.strategies.indicators.dmi import DirectionalMovementIndex
from src.strategies.indicators.linear import LinearRegressionChannel
from src.strategies.indicators.sma import RollingStatistics, sigmoid


@dataclass
class ValuationSnapshot:
    """Ảnh chụp dữ liệu định giá và chấm điểm tại một phiên giao dịch."""
    # Các thành phần kỳ vọng
    saving_rate: float
    pqr: float
    pqt: float
    pr: float
    pt: float
    dividend_yield: float
    expected_return: float  # E

    # Các chỉ số bổ trợ
    u_discount: float       # U: Chiết khấu từ ATH
    l_loser_ratio: float    # L: Tỷ lệ loser 3 năm

    # Sai số chuẩn RMSE
    rmse_sma: float
    rmse_linear: float

    # 5 Luận điểm (Scores trong khoảng 0 - 1)
    score_e: float
    score_u: float
    score_l: float
    score_bp_sma: float          # Luận điểm 4: bp từ SMA RollingStatistics._update_probability
    score_bp_linear: float       # Luận điểm 5: bp từ LinearRegressionChannel._update_probability
    theses_count: int            # Số luận điểm đạt (>= 0.5)

    @property
    def score_rmse_sma(self) -> float:
        return self.score_bp_sma

    @property
    def score_rmse_linear(self) -> float:
        return self.score_bp_linear
    # Vùng giá gợi ý và ATR
    atr: float
    p_suggest: float
    buy_threshold: float    # P_suggest + 1 ATR
    sell_threshold: float   # P_suggest - 1 ATR


class ExpectedReturnEngine:
    """Mô hình dự phóng lợi nhuận (E), chỉ số bổ trợ (U, L) và chấm điểm 5 luận điểm

    Triển khai chính xác theo mục III của tài liệu Chiến lược Giao dịch Định lượng:
    - Bước 0: saving_rate = inflation + yield10y
    - Bước 1: 3 xu hướng cho DXY, EURUSD, USDVND gom cùng DXY, EURUSD, saving_rate thành cụm Q (6 chỉ số)
    - Bước 2: Mô hình BETA tương quan giữa Q và giá P
    - Bước 3: Qt từ LinearRegressionChannel cho từng chỉ số trong Q
    - Bước 4: Qr từ RollingStatistics cho từng chỉ số trong Q
    - Bước 5: Pqt = BETA.predict(*Qt)
    - Bước 6: Pqr = BETA.predict(*Qr)
    - Bước 7: Pt từ LinearRegressionChannel của cổ phiếu
    - Bước 8: Pr từ RollingStatistics của cổ phiếu
    - Bước 9: D = median(Div 5 năm gần nhất) / Market Cap
    - Bước 10: E = 0.42 * Pqr + 0.18 * Pqt + 0.28 * Pr + 0.12 * Pt + D
    - U: Chiết khấu từ ATH
    - L: Tỷ lệ loser trong 3 năm
    - 5 luận điểm: chuẩn hóa z-score và sigmoid về 0-1
    """

    def __init__(
        self,
        window: int = 30,
        linear_window: int | None = None,
        sma_window: int | None = None,
        beta_window: int | None = None,
        z_score_window: int = 120,
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
        self.linear_window = linear_window or window
        self.sma_window = sma_window or window
        self.beta_window = beta_window or window
        self.z_score_window = z_score_window
        self.three_year_window = three_year_window
        self.dmi_period = dmi_period
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.linear_k = float(linear_k)
        self.atr_multiplier = float(atr_multiplier)
        # -------------------------------------------------------------
        # 1. Các mô hình cho Cổ phiếu mục tiêu (P)
        # -------------------------------------------------------------
        self.stock_lrc = LinearRegressionChannel(
            window=None if self.expanding else self.linear_window,
            k=self.linear_k,
            expanding=self.expanding,
        )
        self.stock_sma = RollingStatistics(
            window=None if self.expanding else self.sma_window,
            expanding=self.expanding,
        )
        self.stock_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)
        # -------------------------------------------------------------
        # 2. Các mô hình xu hướng DMI cho DXY, EURUSD, USDVND
        # -------------------------------------------------------------
        self.dxy_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)
        self.eur_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)
        self.fx_dmi = DirectionalMovementIndex(period=self.dmi_period, adx_period=self.adx_period)

        # -------------------------------------------------------------
        # 3. Mô hình BETA tương quan giữa Q (6 biến) và Giá P
        # -------------------------------------------------------------
        self.q_dim = 6
        self.beta_model = MultivariateLinearRegression(
            n_features=self.q_dim,
            window=None if self.expanding else self.beta_window,
            expanding=self.expanding,
            learning_rate=0.02,
        )
        # -------------------------------------------------------------
        # 4. Mô hình Tuyến tính (LRC) và SMA cho từng chỉ số trong Q
        # -------------------------------------------------------------
        self.q_lrc_models = [
            LinearRegressionChannel(
                window=None if self.expanding else self.linear_window,
                k=self.linear_k,
                expanding=self.expanding,
            )
            for _ in range(self.q_dim)
        ]
        self.q_sma_models = [
            RollingStatistics(
                window=None if self.expanding else self.sma_window,
                expanding=self.expanding,
            )
            for _ in range(self.q_dim)
        ]

        # -------------------------------------------------------------
        # 5. Lưu trữ lịch sử giá để tính ATH, Loser ratio L, ATR, Z-scores
        self._price_history: list[float] = []
        self._sorted_prices: list[float] = []
        self._ath: float = 0.0
        z_maxlen = None if self.expanding else self.z_score_window
        self._e_history: deque[float] = deque(maxlen=z_maxlen)
        self._u_history: deque[float] = deque(maxlen=z_maxlen)
        self._l_history: deque[float] = deque(maxlen=z_maxlen)


        # ATR computation
        self._prev_close: float | None = None
        self._tr_history: deque[float] = deque(maxlen=self.atr_period)

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
    ) -> ValuationSnapshot:
        """Cập nhật dữ liệu phiên mới và trả về ValuationSnapshot."""
        # Cập nhật ATR (Wilder True Range)
        if self._prev_close is not None:
            tr = max(
                stock_high - stock_low,
                abs(stock_high - self._prev_close),
                abs(stock_low - self._prev_close),
            )
        else:
            tr = stock_high - stock_low
        self._prev_close = stock_close
        self._tr_history.append(tr)
        atr = float(np.mean(self._tr_history)) if self._tr_history else max(stock_high - stock_low, 1.0)

        self._price_history.append(stock_close)
        bisect.insort(self._sorted_prices, stock_close)
        if stock_high > self._ath:
            self._ath = stock_high

        # -------------------------------------------------------------
        # Bước 0: Tính lãi suất tiết kiệm
        # -------------------------------------------------------------
        # Chuẩn hóa nếu rate ở đơn vị % (ví dụ 3.5 -> 0.035)
        inf_val = inflation_rate if inflation_rate < 1.0 else inflation_rate / 100.0
        by_val = bond_yield_10y if bond_yield_10y < 1.0 else bond_yield_10y / 100.0
        saving_rate = inf_val + by_val

        # -------------------------------------------------------------
        # Bước 1: Tính xu hướng cho DXY, EURUSD, USDVND và lập cụm Q (6 chỉ số)
        # -------------------------------------------------------------
        self.dxy_dmi.update_raw(dxy_close * 1.001, dxy_close * 0.999, dxy_close)
        self.eur_dmi.update_raw(eurusd_close * 1.001, eurusd_close * 0.999, eurusd_close)
        self.fx_dmi.update_raw(usdvnd_close * 1.001, usdvnd_close * 0.999, usdvnd_close)

        trend_dxy = self.dxy_dmi.trend_score
        trend_eur = self.eur_dmi.trend_score
        trend_fx = self.fx_dmi.trend_score

        # Cụm chỉ số tương quan Q gồm 6 biến:
        # Cụm chỉ số tương quan Q gồm 6 biến (chuẩn hóa cơ số dương để tính %change an toàn):
        # [trend(DXY), trend(EURUSD), trend(USDVND), DXY, EURUSD, saving_rate]
        q_values = [
            100.0 + trend_dxy,
            100.0 + trend_eur,
            100.0 + trend_fx,
            dxy_close,
            eurusd_close,
            1.0 + saving_rate,
        ]
        # -------------------------------------------------------------
        # Bước 2: Cập nhật mô hình tương quan BETA giữa Q và P
        # -------------------------------------------------------------
        self.beta_model.update_raw(stock_close, *q_values)

        # -------------------------------------------------------------
        # Bước 3 & 4: Tính Qt (LRC) và Qr (SMA) cho từng chỉ số trong Q
        # -------------------------------------------------------------
        qt_list: list[float] = []
        qr_list: list[float] = []

        for i, val in enumerate(q_values):
            lrc_m = self.q_lrc_models[i]
            sma_m = self.q_sma_models[i]
            lrc_m.update_raw(val)
            sma_m.update_raw(val)
            qt_list.append(lrc_m.premium)
            qr_list.append(sma_m.premium)

        # -------------------------------------------------------------
        # Bước 5 & 6: Dùng BETA suy ra Pqt và Pqr
        # -------------------------------------------------------------
        pqt = self.beta_model.predict(*qt_list)
        pqr = self.beta_model.predict(*qr_list)

        # -------------------------------------------------------------
        # Bước 7 & 8: Lợi nhuận dự phóng Pt (LRC) và Pr (SMA) của cổ phiếu P
        # -------------------------------------------------------------
        self.stock_lrc.update_raw(stock_close)
        self.stock_sma.update_raw(stock_close)
        self.stock_dmi.update_raw(stock_high, stock_low, stock_close)

        pt = self.stock_lrc.premium
        pr = self.stock_sma.premium

        # -------------------------------------------------------------
        # Bước 9: Tính lợi suất cổ tức (D)
        # -------------------------------------------------------------
        market_cap = max(stock_close * max(shares_outstanding, 1.0), 1e6)
        clean_divs = [float(d) for d in dividend_5y_history if math.isfinite(float(d)) and float(d) >= 0]
        if clean_divs:
            med_div = float(np.median(clean_divs))
            # Nếu clean_divs là tổng tiền cổ tức hàng năm
            if med_div > 1e6:
                dividend_yield = med_div / market_cap
            else:
                # Nếu clean_divs là DPS (cổ tức trên 1 cổ phiếu)
                dividend_yield = med_div / max(stock_close, 1.0)
        else:
            dividend_yield = 0.0

        # -------------------------------------------------------------
        # Bước 10: Tổng hợp lợi nhuận kỳ vọng 1 năm (E)
        # E = 0.42 * Pqr + 0.18 * Pqt + 0.28 * Pr + 0.12 * Pt + D
        # -------------------------------------------------------------
        e_return = 0.42 * pqr + 0.18 * pqt + 0.28 * pr + 0.12 * pt + dividend_yield

        # -------------------------------------------------------------
        # II. Các chỉ số bổ trợ: U (ATH Discount) và L (Loser Ratio 3y)
        # -------------------------------------------------------------
        u_discount = max(0.0, (self._ath - stock_close) / self._ath) if self._ath > 0 else 0.0


        if self.expanding:
            idx_pos = bisect.bisect_left(self._sorted_prices, stock_close)
            loser_count = len(self._sorted_prices) - idx_pos
            l_loser_ratio = loser_count / len(self._sorted_prices)
        else:
            recent_prices = self._price_history[-self.three_year_window:]
            if recent_prices:
                loser_count = sum(1 for p in recent_prices if p >= stock_close)
                l_loser_ratio = loser_count / len(recent_prices)
            else:
                l_loser_ratio = 0.5

        # RMSE metrics
        rmse_sma = self.stock_sma.std
        rmse_linear = self.stock_lrc.rmse
        # -------------------------------------------------------------
        self._e_history.append(e_return)
        self._u_history.append(u_discount)
        self._l_history.append(l_loser_ratio)


        def _calc_z_score_sigmoid(history: deque[float], current_val: float, invert: bool = False) -> float:
            n_h = len(history)
            if n_h < 3:
                return 0.5
            h_slice = list(history)[-250:] if n_h > 250 else history
            mean_h = float(np.mean(h_slice))
            std_h = float(np.std(h_slice))
            if std_h <= 1e-12:
                return 0.5
            z = (current_val - mean_h) / std_h
            if invert:
                z = -z
            return sigmoid(z)
        score_e = _calc_z_score_sigmoid(self._e_history, e_return, invert=False)
        # 2. Luận điểm 2: U chiết khấu sâu từ ATH
        score_u = _calc_z_score_sigmoid(self._u_history, u_discount, invert=False)
        # 3. Luận điểm 3: L tỷ lệ loser cao (cạn kiệt cung bán cắt lỗ)
        score_l = _calc_z_score_sigmoid(self._l_history, l_loser_ratio, invert=False)
        # 4. Luận điểm 4: self.bp trong RollingStatistics._update_probability()
        score_bp_sma = float(self.stock_sma.bp)
        # 5. Luận điểm 5: self.bp trong LinearRegressionChannel._update_probability()
        score_bp_linear = float(self.stock_lrc.bp)

        theses_flags = [
            score_e >= 0.5,
            score_u >= 0.5,
            score_l >= 0.5,
            score_bp_sma >= 0.5,
            score_bp_linear >= 0.5,
        ]
        theses_count = sum(1 for flag in theses_flags if flag)

        # -------------------------------------------------------------
        # IV. Vùng giá gợi ý từ SMA và Mô hình Tuyến tính +/- 1 ATR
        # -------------------------------------------------------------
        p_suggest_sma = self.stock_sma.mean if self.stock_sma.initialized else stock_close
        p_suggest_linear = self.stock_lrc.baseline if self.stock_lrc.initialized else stock_close
        p_suggest = 0.5 * (p_suggest_sma + p_suggest_linear)

        buy_threshold = p_suggest + self.atr_multiplier * atr
        sell_threshold = p_suggest - self.atr_multiplier * atr

        return ValuationSnapshot(
            saving_rate=saving_rate,
            pqr=pqr,
            pqt=pqt,
            pr=pr,
            pt=pt,
            dividend_yield=dividend_yield,
            expected_return=e_return,
            u_discount=u_discount,
            l_loser_ratio=l_loser_ratio,
            rmse_sma=rmse_sma,
            rmse_linear=rmse_linear,
            score_e=score_e,
            score_u=score_u,
            score_l=score_l,
            score_bp_sma=score_bp_sma,
            score_bp_linear=score_bp_linear,
            theses_count=theses_count,
            atr=atr,
            p_suggest=p_suggest,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
        )
