"""Sentiment-based trading strategy using social media signals."""

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np

from moneymaker.models import MarketData, SentimentData, Signal, SignalDirection
from moneymaker.strategies.base import Strategy


class SentimentStrategy(Strategy):
    """
    Sentiment arbitrage strategy.

    The idea: If everyone on crypto Twitter is suddenly bullish,
    maybe we should ride the wave (or inverse it if we're feeling contrarian).

    This strategy:
    - Tracks sentiment momentum (is sentiment getting more positive?)
    - Looks for sentiment/price divergence (sentiment up but price flat = potential)
    - Weighs recency heavily (what are people saying NOW)
    """

    name: ClassVar[str] = "sentiment"
    description: ClassVar[str] = "Trade based on social media sentiment shifts"
    default_allocation: ClassVar[float] = 0.15  # 15% allocation

    def __init__(
        self,
        allocation: float | None = None,
        lookback_hours: int = 24,
        momentum_weight: float = 0.4,
        divergence_weight: float = 0.3,
        absolute_weight: float = 0.3,
    ):
        super().__init__(allocation)
        self.lookback_hours = lookback_hours
        self.momentum_weight = momentum_weight
        self.divergence_weight = divergence_weight
        self.absolute_weight = absolute_weight

    def _calculate_sentiment_momentum(
        self, sentiment_data: list[SentimentData]
    ) -> tuple[float, str]:
        """
        Calculate if sentiment is improving or deteriorating.
        Returns momentum (-1 to 1) and explanation.
        """
        if len(sentiment_data) < 2:
            return 0.0, "Insufficient data for momentum"

        # Split into older and newer
        midpoint = len(sentiment_data) // 2
        older = sentiment_data[:midpoint]
        newer = sentiment_data[midpoint:]

        older_avg = np.mean([s.score for s in older]) if older else 0
        newer_avg = np.mean([s.score for s in newer]) if newer else 0

        momentum = newer_avg - older_avg

        if momentum > 0.2:
            explanation = f"Sentiment improving rapidly ({older_avg:.2f} -> {newer_avg:.2f})"
        elif momentum > 0:
            explanation = f"Sentiment slightly improving ({older_avg:.2f} -> {newer_avg:.2f})"
        elif momentum < -0.2:
            explanation = f"Sentiment deteriorating rapidly ({older_avg:.2f} -> {newer_avg:.2f})"
        elif momentum < 0:
            explanation = f"Sentiment slightly worsening ({older_avg:.2f} -> {newer_avg:.2f})"
        else:
            explanation = f"Sentiment stable ({newer_avg:.2f})"

        return np.clip(momentum * 2, -1, 1), explanation

    def _calculate_price_sentiment_divergence(
        self,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData],
    ) -> tuple[float, str]:
        """
        Look for divergence between price action and sentiment.
        If sentiment is bullish but price is flat, that's potentially interesting.
        """
        if len(market_data) < 2 or len(sentiment_data) < 1:
            return 0.0, "Insufficient data for divergence"

        # Price change
        price_change = (market_data[-1].close - market_data[0].close) / market_data[0].close

        # Current sentiment
        recent_sentiment = np.mean([s.score for s in sentiment_data[-5:]])

        # Divergence: positive sentiment + negative/flat price = opportunity
        # negative sentiment + positive price = warning
        divergence = recent_sentiment - (price_change * 2)

        if divergence > 0.3 and recent_sentiment > 0.2:
            explanation = f"Bullish sentiment ({recent_sentiment:.2f}) but price lagging ({price_change:+.1%})"
        elif divergence < -0.3 and recent_sentiment < -0.2:
            explanation = f"Bearish sentiment ({recent_sentiment:.2f}) but price resilient ({price_change:+.1%})"
        elif abs(divergence) < 0.1:
            explanation = f"Price and sentiment aligned"
        else:
            explanation = f"Minor divergence detected"

        return np.clip(divergence, -1, 1), explanation

    def _calculate_volume_weighted_sentiment(
        self, sentiment_data: list[SentimentData]
    ) -> tuple[float, str]:
        """
        Weight sentiment by volume of mentions.
        More mentions = more conviction in the signal.
        """
        if not sentiment_data:
            return 0.0, "No sentiment data"

        total_volume = sum(s.volume for s in sentiment_data)
        if total_volume == 0:
            return 0.0, "No mention volume"

        weighted_sentiment = sum(
            s.score * s.volume for s in sentiment_data
        ) / total_volume

        avg_volume = total_volume / len(sentiment_data)

        if weighted_sentiment > 0.5:
            explanation = f"Strong bullish consensus ({weighted_sentiment:.2f}, {int(avg_volume)} avg mentions)"
        elif weighted_sentiment > 0.2:
            explanation = f"Mild bullish sentiment ({weighted_sentiment:.2f}, {int(avg_volume)} avg mentions)"
        elif weighted_sentiment < -0.5:
            explanation = f"Strong bearish consensus ({weighted_sentiment:.2f}, {int(avg_volume)} avg mentions)"
        elif weighted_sentiment < -0.2:
            explanation = f"Mild bearish sentiment ({weighted_sentiment:.2f}, {int(avg_volume)} avg mentions)"
        else:
            explanation = f"Neutral sentiment ({weighted_sentiment:.2f}, {int(avg_volume)} avg mentions)"

        return weighted_sentiment, explanation

    async def analyze(
        self,
        symbol: str,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData] | None = None,
    ) -> Signal | None:
        """Analyze sentiment data to generate trading signal."""
        if not sentiment_data:
            return None

        # Filter to recent sentiment
        cutoff = datetime.utcnow() - timedelta(hours=self.lookback_hours)
        recent_sentiment = [s for s in sentiment_data if s.timestamp > cutoff]

        if len(recent_sentiment) < 3:
            return None

        # Calculate components
        momentum, momentum_exp = self._calculate_sentiment_momentum(recent_sentiment)
        divergence, divergence_exp = self._calculate_price_sentiment_divergence(
            market_data, recent_sentiment
        )
        absolute, absolute_exp = self._calculate_volume_weighted_sentiment(recent_sentiment)

        # Weighted combination
        composite = (
            momentum * self.momentum_weight +
            divergence * self.divergence_weight +
            absolute * self.absolute_weight
        )

        # Confidence based on data quality
        data_quality = min(len(recent_sentiment) / 20, 1.0)  # More data = more confidence
        confidence = abs(composite) * data_quality

        # Determine direction
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

        reasoning = f"{momentum_exp}. {divergence_exp}. {absolute_exp}"

        return Signal(
            strategy_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=min(confidence, 1.0),
            reasoning=reasoning,
            timestamp=datetime.utcnow(),
            metadata={
                "momentum_score": momentum,
                "divergence_score": divergence,
                "absolute_score": absolute,
                "composite_score": composite,
                "data_points": len(recent_sentiment),
            }
        )
