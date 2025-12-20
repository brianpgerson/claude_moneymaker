"""Momentum-based trading strategy using technical indicators."""

from datetime import datetime
from typing import ClassVar

import numpy as np

from moneymaker.models import MarketData, SentimentData, Signal, SignalDirection
from moneymaker.strategies.base import Strategy


class MomentumStrategy(Strategy):
    """
    Classic momentum strategy using RSI, MACD, and moving averages.

    This is our "sensible" baseline strategy. It looks at:
    - RSI: Overbought/oversold conditions
    - MACD: Trend direction and momentum
    - Moving averages: Short vs long-term trend
    """

    name: ClassVar[str] = "momentum"
    description: ClassVar[str] = "Technical momentum using RSI, MACD, and moving averages"
    default_allocation: ClassVar[float] = 0.30  # 30% allocation

    def __init__(
        self,
        allocation: float | None = None,
        rsi_period: int = 14,
        short_ma: int = 12,
        long_ma: int = 26,
        signal_ma: int = 9,
    ):
        super().__init__(allocation)
        self.rsi_period = rsi_period
        self.short_ma = short_ma
        self.long_ma = long_ma
        self.signal_ma = signal_ma

    def _calculate_rsi(self, prices: list[float]) -> float | None:
        """Calculate RSI indicator."""
        if len(prices) < self.rsi_period + 1:
            return None

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-self.rsi_period:])
        avg_loss = np.mean(losses[-self.rsi_period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_macd(self, prices: list[float]) -> tuple[float, float, float] | None:
        """Calculate MACD, signal line, and histogram."""
        if len(prices) < self.long_ma + self.signal_ma:
            return None

        prices_arr = np.array(prices)

        # EMA calculation
        def ema(data: np.ndarray, period: int) -> np.ndarray:
            alpha = 2 / (period + 1)
            result = np.zeros_like(data)
            result[0] = data[0]
            for i in range(1, len(data)):
                result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
            return result

        short_ema = ema(prices_arr, self.short_ma)
        long_ema = ema(prices_arr, self.long_ma)
        macd_line = short_ema - long_ema
        signal_line = ema(macd_line, self.signal_ma)
        histogram = macd_line - signal_line

        return macd_line[-1], signal_line[-1], histogram[-1]

    def _calculate_ma_trend(self, prices: list[float]) -> float | None:
        """Calculate trend based on MA crossover. Returns -1 to 1."""
        if len(prices) < self.long_ma:
            return None

        short_ma = np.mean(prices[-self.short_ma:])
        long_ma = np.mean(prices[-self.long_ma:])
        current_price = prices[-1]

        # Normalize the difference
        ma_diff = (short_ma - long_ma) / long_ma
        price_vs_ma = (current_price - short_ma) / short_ma

        # Combine signals (-1 to 1)
        return np.clip(ma_diff * 10 + price_vs_ma * 5, -1, 1)

    async def analyze(
        self,
        symbol: str,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData] | None = None,
    ) -> Signal | None:
        """Analyze using technical momentum indicators."""
        if len(market_data) < self.long_ma + self.signal_ma:
            return None

        prices = [d.close for d in market_data]

        # Calculate indicators
        rsi = self._calculate_rsi(prices)
        macd_result = self._calculate_macd(prices)
        ma_trend = self._calculate_ma_trend(prices)

        if rsi is None or macd_result is None or ma_trend is None:
            return None

        macd_line, signal_line, histogram = macd_result

        # Score the signals
        scores = []
        reasoning_parts = []

        # RSI signal
        if rsi < 30:
            scores.append(0.7)
            reasoning_parts.append(f"RSI oversold ({rsi:.1f})")
        elif rsi < 40:
            scores.append(0.3)
            reasoning_parts.append(f"RSI approaching oversold ({rsi:.1f})")
        elif rsi > 70:
            scores.append(-0.7)
            reasoning_parts.append(f"RSI overbought ({rsi:.1f})")
        elif rsi > 60:
            scores.append(-0.3)
            reasoning_parts.append(f"RSI approaching overbought ({rsi:.1f})")
        else:
            scores.append(0)
            reasoning_parts.append(f"RSI neutral ({rsi:.1f})")

        # MACD signal
        if histogram > 0 and macd_line > signal_line:
            macd_score = min(histogram * 100, 0.8)
            scores.append(macd_score)
            reasoning_parts.append(f"MACD bullish crossover")
        elif histogram < 0 and macd_line < signal_line:
            macd_score = max(histogram * 100, -0.8)
            scores.append(macd_score)
            reasoning_parts.append(f"MACD bearish crossover")
        else:
            scores.append(0)
            reasoning_parts.append("MACD neutral")

        # MA trend signal
        scores.append(ma_trend * 0.6)
        if ma_trend > 0.3:
            reasoning_parts.append("Strong uptrend on MAs")
        elif ma_trend > 0:
            reasoning_parts.append("Mild uptrend on MAs")
        elif ma_trend < -0.3:
            reasoning_parts.append("Strong downtrend on MAs")
        elif ma_trend < 0:
            reasoning_parts.append("Mild downtrend on MAs")
        else:
            reasoning_parts.append("Flat trend on MAs")

        # Combine scores
        avg_score = np.mean(scores)
        confidence = min(abs(avg_score) * 1.5, 1.0)

        # Determine direction
        if avg_score > 0.5:
            direction = SignalDirection.STRONG_BUY
        elif avg_score > 0.2:
            direction = SignalDirection.BUY
        elif avg_score < -0.5:
            direction = SignalDirection.STRONG_SELL
        elif avg_score < -0.2:
            direction = SignalDirection.SELL
        else:
            direction = SignalDirection.HOLD

        return Signal(
            strategy_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            reasoning="; ".join(reasoning_parts),
            timestamp=datetime.utcnow(),
            metadata={
                "rsi": rsi,
                "macd": macd_line,
                "macd_signal": signal_line,
                "macd_histogram": histogram,
                "ma_trend": ma_trend,
                "composite_score": avg_score,
            }
        )
