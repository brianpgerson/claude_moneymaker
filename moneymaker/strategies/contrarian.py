"""Contrarian strategy - do the opposite of the crowd."""

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np

from moneymaker.models import MarketData, SentimentData, Signal, SignalDirection
from moneymaker.strategies.base import Strategy


class ContrarianStrategy(Strategy):
    """
    The Contrarian: When everyone zigs, we zag.

    The theory: Markets overreact. When crypto Twitter is euphoric,
    it might be time to take profits. When everyone is panicking,
    it might be time to buy.

    This is the "inverse WSB" strategy.
    """

    name: ClassVar[str] = "contrarian"
    description: ClassVar[str] = "Inverse the crowd when sentiment is extreme"
    default_allocation: ClassVar[float] = 0.15  # 15% allocation

    def __init__(
        self,
        allocation: float | None = None,
        euphoria_threshold: float = 0.6,  # Above this = too bullish
        panic_threshold: float = -0.6,    # Below this = too bearish
        volume_multiplier_threshold: float = 2.0,  # Volume spike threshold
    ):
        super().__init__(allocation)
        self.euphoria_threshold = euphoria_threshold
        self.panic_threshold = panic_threshold
        self.volume_multiplier_threshold = volume_multiplier_threshold

    def _detect_extreme_sentiment(
        self, sentiment_data: list[SentimentData]
    ) -> tuple[float, str]:
        """
        Detect if sentiment has reached extreme levels.
        Returns inverse signal strength and explanation.
        """
        if len(sentiment_data) < 5:
            return 0.0, "Insufficient sentiment data"

        # Recent sentiment average
        recent = sentiment_data[-10:] if len(sentiment_data) >= 10 else sentiment_data
        avg_sentiment = np.mean([s.score for s in recent])

        # Check for extremes - we INVERSE the signal
        if avg_sentiment > self.euphoria_threshold:
            # Everyone bullish = we're bearish
            inverse_signal = -(avg_sentiment - self.euphoria_threshold) * 2
            explanation = f"EUPHORIA DETECTED ({avg_sentiment:.2f}) - crowd is too bullish, fading"
        elif avg_sentiment < self.panic_threshold:
            # Everyone bearish = we're bullish
            inverse_signal = -(avg_sentiment - self.panic_threshold) * 2
            explanation = f"PANIC DETECTED ({avg_sentiment:.2f}) - crowd is capitulating, buying"
        else:
            # Not extreme enough to trigger
            return 0.0, f"Sentiment not extreme enough ({avg_sentiment:.2f})"

        return np.clip(inverse_signal, -1, 1), explanation

    def _detect_volume_spike(
        self, sentiment_data: list[SentimentData]
    ) -> tuple[float, str]:
        """
        Detect unusual volume in social mentions.
        High volume + extreme sentiment = stronger contrarian signal.
        """
        if len(sentiment_data) < 10:
            return 0.0, "Insufficient data for volume analysis"

        # Compare recent volume to historical
        recent_volume = np.mean([s.volume for s in sentiment_data[-5:]])
        historical_volume = np.mean([s.volume for s in sentiment_data[:-5]])

        if historical_volume == 0:
            return 0.0, "No historical volume"

        volume_ratio = recent_volume / historical_volume

        if volume_ratio > self.volume_multiplier_threshold:
            # High volume confirms contrarian signal
            multiplier = min((volume_ratio - 1) * 0.5, 1.0)
            explanation = f"Volume spike detected ({volume_ratio:.1f}x normal) - crowd is loud"
            return multiplier, explanation

        return 0.0, f"Normal volume levels ({volume_ratio:.1f}x)"

    def _detect_price_extreme(
        self, market_data: list[MarketData]
    ) -> tuple[float, str]:
        """
        Detect if price has moved too far too fast.
        Extreme price moves often revert.
        """
        if len(market_data) < 24:  # Need at least 24 candles
            return 0.0, "Insufficient price data"

        prices = [d.close for d in market_data]

        # Calculate z-score of recent price vs historical
        historical_prices = prices[:-6]
        recent_price = prices[-1]

        mean_price = np.mean(historical_prices)
        std_price = np.std(historical_prices)

        if std_price == 0:
            return 0.0, "No price variance"

        z_score = (recent_price - mean_price) / std_price

        # Inverse the signal - extreme high = bearish, extreme low = bullish
        if z_score > 2.5:
            inverse_signal = -min((z_score - 2) * 0.4, 1.0)
            explanation = f"Price extended high (z={z_score:.1f}) - mean reversion expected"
        elif z_score < -2.5:
            inverse_signal = min((-z_score - 2) * 0.4, 1.0)
            explanation = f"Price extended low (z={z_score:.1f}) - bounce expected"
        else:
            return 0.0, f"Price within normal range (z={z_score:.1f})"

        return inverse_signal, explanation

    async def analyze(
        self,
        symbol: str,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData] | None = None,
    ) -> Signal | None:
        """Generate contrarian signal based on extreme conditions."""

        signals = []
        explanations = []

        # Check sentiment extremes
        if sentiment_data:
            sentiment_signal, sentiment_exp = self._detect_extreme_sentiment(sentiment_data)
            if sentiment_signal != 0:
                signals.append(sentiment_signal)
                explanations.append(sentiment_exp)

            # Volume confirmation
            volume_mult, volume_exp = self._detect_volume_spike(sentiment_data)
            if volume_mult > 0 and signals:
                signals[-1] *= (1 + volume_mult)  # Amplify signal
                explanations.append(volume_exp)

        # Check price extremes
        if market_data:
            price_signal, price_exp = self._detect_price_extreme(market_data)
            if price_signal != 0:
                signals.append(price_signal)
                explanations.append(price_exp)

        # If no extreme conditions detected, no signal
        if not signals:
            return None

        # Combine signals
        composite = np.mean(signals)

        # Contrarian signals should have decent confidence when triggered
        confidence = min(abs(composite) * 1.2, 0.85)  # Cap at 85% - we're being contrarian after all

        if composite > 0.4:
            direction = SignalDirection.STRONG_BUY
        elif composite > 0.15:
            direction = SignalDirection.BUY
        elif composite < -0.4:
            direction = SignalDirection.STRONG_SELL
        elif composite < -0.15:
            direction = SignalDirection.SELL
        else:
            direction = SignalDirection.HOLD

        return Signal(
            strategy_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            reasoning=" | ".join(explanations),
            timestamp=datetime.utcnow(),
            metadata={
                "composite_score": composite,
                "num_signals": len(signals),
                "is_contrarian": True,
            }
        )
