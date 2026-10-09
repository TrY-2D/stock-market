from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CandlestickSignal:
    """Tín hiệu đảo chiều nến đơn và nến đôi."""
    is_bullish: bool
    is_bearish: bool
    pattern: str


class CandlestickPatternDetector:
    """Bộ nhận diện mô hình nến đảo chiều cho cổ phiếu và thị trường.

    Bao gồm các mô hình nến đơn đảo chiều:
    - Bullish: Hammer (Búa), Inverted Hammer (Búa ngược), Dragonfly Doji / Pinbar, Bullish Engulfing.
    - Bearish: Shooting Star (Sao băng), Hanging Man (Người treo cổ), Gravestone Doji / Pinbar, Bearish Engulfing.
    """

    @staticmethod
    def analyze(
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        prev_open: float | None = None,
        prev_close: float | None = None,
    ) -> CandlestickSignal:
        total_range = high_p - low_p
        if total_range <= 1e-12:
            return CandlestickSignal(is_bullish=False, is_bearish=False, pattern="None")

        body = abs(close_p - open_p)
        upper_shadow = high_p - max(open_p, close_p)
        lower_shadow = min(open_p, close_p) - low_p
        body_ratio = body / total_range

        # -------------------------------------------------------------
        # 1. Bullish Single & Double Patterns
        # -------------------------------------------------------------
        # Hammer: Thân nhỏ ở trên, bóng dưới dài tối thiểu 2 lần thân
        if (
            body_ratio <= 0.35
            and lower_shadow >= 2.0 * max(body, 1e-8)
            and upper_shadow <= 0.15 * total_range
        ):
            return CandlestickSignal(is_bullish=True, is_bearish=False, pattern="Hammer")

        # Inverted Hammer: Thân nhỏ ở dưới, bóng trên dài tối thiểu 2 lần thân, nến tăng (Close >= Open)
        if (
            body_ratio <= 0.35
            and upper_shadow >= 2.0 * max(body, 1e-8)
            and lower_shadow <= 0.15 * total_range
            and close_p >= open_p
        ):
            return CandlestickSignal(is_bullish=True, is_bearish=False, pattern="Inverted Hammer")

        # Dragonfly Doji / Bullish Pinbar: Thân cực nhỏ, bóng dưới dài chiếm ưu thế
        if (
            body_ratio <= 0.10
            and lower_shadow >= 0.65 * total_range
            and upper_shadow <= 0.10 * total_range
        ):
            return CandlestickSignal(is_bullish=True, is_bearish=False, pattern="Dragonfly Doji")

        # Bullish Engulfing: Nến trước giảm, nến này tăng bao trùm thân trước
        if (
            prev_open is not None
            and prev_close is not None
            and prev_close < prev_open
            and close_p > open_p
            and open_p <= prev_close
            and close_p >= prev_open
        ):
            return CandlestickSignal(is_bullish=True, is_bearish=False, pattern="Bullish Engulfing")

        # -------------------------------------------------------------
        # 2. Bearish Single & Double Patterns
        # -------------------------------------------------------------
        # Shooting Star: Thân nhỏ ở dưới, bóng trên dài tối thiểu 2 lần thân
        if (
            body_ratio <= 0.35
            and upper_shadow >= 2.0 * max(body, 1e-8)
            and lower_shadow <= 0.15 * total_range
            and close_p < open_p
        ):
            return CandlestickSignal(is_bullish=False, is_bearish=True, pattern="Shooting Star")

        # Hanging Man: Thân nhỏ ở trên, bóng dưới dài tối thiểu 2 lần thân
        if (
            body_ratio <= 0.35
            and lower_shadow >= 2.0 * max(body, 1e-8)
            and upper_shadow <= 0.15 * total_range
            and close_p < open_p
        ):
            return CandlestickSignal(is_bullish=False, is_bearish=True, pattern="Hanging Man")

        # Gravestone Doji / Bearish Pinbar: Thân cực nhỏ, bóng trên dài chiếm ưu thế
        if (
            body_ratio <= 0.10
            and upper_shadow >= 0.65 * total_range
            and lower_shadow <= 0.10 * total_range
        ):
            return CandlestickSignal(is_bullish=False, is_bearish=True, pattern="Gravestone Doji")

        # Bearish Engulfing: Nến trước tăng, nến này giảm bao trùm thân trước
        if (
            prev_open is not None
            and prev_close is not None
            and prev_close > prev_open
            and close_p < open_p
            and open_p >= prev_close
            and close_p <= prev_open
        ):
            return CandlestickSignal(is_bullish=False, is_bearish=True, pattern="Bearish Engulfing")

        return CandlestickSignal(is_bullish=False, is_bearish=False, pattern="None")
