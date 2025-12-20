"""The Claude Vibes Strategy - Let Claude analyze everything and vibe check the market."""

from datetime import datetime
from typing import ClassVar

from moneymaker.models import MarketData, SentimentData, Signal, SignalDirection
from moneymaker.strategies.base import Strategy


class ClaudeVibesStrategy(Strategy):
    """
    The main event: Claude analyzes all available data and makes a judgment call.

    This is the "meta" strategy where Claude:
    1. Looks at price action
    2. Reads the sentiment tea leaves
    3. Considers what other strategies are saying
    4. Makes a vibe-based decision

    Think of it as the "gut feeling" layer on top of the quantitative signals.
    """

    name: ClassVar[str] = "claude_vibes"
    description: ClassVar[str] = "Claude's holistic vibe check on the market"
    default_allocation: ClassVar[float] = 0.25  # 25% allocation - trust the vibes

    def __init__(
        self,
        allocation: float | None = None,
        anthropic_client=None,  # Will be injected
        model: str = "claude-sonnet-4-20250514",
    ):
        super().__init__(allocation)
        self.anthropic_client = anthropic_client
        self.model = model

    def _format_market_summary(self, market_data: list[MarketData]) -> str:
        """Create a human-readable market summary for Claude."""
        if not market_data:
            return "No market data available."

        latest = market_data[-1]
        oldest = market_data[0]

        price_change = (latest.close - oldest.close) / oldest.close
        high = max(d.high for d in market_data)
        low = min(d.low for d in market_data)
        avg_volume = sum(d.volume for d in market_data) / len(market_data)

        # Recent trend
        if len(market_data) >= 6:
            recent = market_data[-6:]
            recent_change = (recent[-1].close - recent[0].close) / recent[0].close
        else:
            recent_change = price_change

        return f"""
MARKET DATA SUMMARY ({len(market_data)} candles):
- Current price: ${latest.close:.6f}
- Period change: {price_change:+.2%}
- Recent trend (last 6 candles): {recent_change:+.2%}
- Period high: ${high:.6f}
- Period low: ${low:.6f}
- Price range: {((high - low) / low):.2%}
- Average volume: {avg_volume:,.0f}
"""

    def _format_sentiment_summary(self, sentiment_data: list[SentimentData]) -> str:
        """Create a human-readable sentiment summary for Claude."""
        if not sentiment_data:
            return "No sentiment data available."

        # Group by source
        by_source: dict[str, list[SentimentData]] = {}
        for s in sentiment_data:
            if s.source not in by_source:
                by_source[s.source] = []
            by_source[s.source].append(s)

        summary_parts = [f"SENTIMENT SUMMARY ({len(sentiment_data)} data points):"]

        for source, data in by_source.items():
            avg_score = sum(d.score for d in data) / len(data)
            total_mentions = sum(d.volume for d in data)

            # Get some sample texts if available
            samples = []
            for d in data[-3:]:  # Last 3 entries
                samples.extend(d.sample_texts[:2])

            sentiment_word = (
                "very bullish" if avg_score > 0.5 else
                "bullish" if avg_score > 0.2 else
                "very bearish" if avg_score < -0.5 else
                "bearish" if avg_score < -0.2 else
                "neutral"
            )

            summary_parts.append(f"\n{source.upper()}:")
            summary_parts.append(f"  - Sentiment: {sentiment_word} ({avg_score:.2f})")
            summary_parts.append(f"  - Total mentions: {total_mentions}")
            if samples:
                summary_parts.append(f"  - Sample takes: {samples[:3]}")

        return "\n".join(summary_parts)

    async def analyze(
        self,
        symbol: str,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData] | None = None,
    ) -> Signal | None:
        """Have Claude analyze everything and produce a vibe-based signal."""
        if not self.anthropic_client:
            # Fallback to simple heuristic if no Claude available
            return await self._fallback_analyze(symbol, market_data, sentiment_data)

        market_summary = self._format_market_summary(market_data)
        sentiment_summary = self._format_sentiment_summary(sentiment_data or [])

        prompt = f"""You are a crypto trading analyst. Analyze the following data for {symbol} and provide a trading recommendation.

{market_summary}

{sentiment_summary}

Based on this data, what's your trading recommendation? Consider:
1. Is the current price action sustainable?
2. Does sentiment support or contradict price movement?
3. Are there any red flags or opportunities?
4. What's the risk/reward here?

Respond with EXACTLY this format:
DIRECTION: [STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL]
CONFIDENCE: [0.0-1.0]
REASONING: [Your 1-2 sentence explanation]
"""

        try:
            response = await self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            return self._parse_claude_response(symbol, response.content[0].text)
        except Exception as e:
            # Log error and fall back
            print(f"Claude API error: {e}")
            return await self._fallback_analyze(symbol, market_data, sentiment_data)

    def _parse_claude_response(self, symbol: str, response: str) -> Signal | None:
        """Parse Claude's response into a Signal."""
        lines = response.strip().split("\n")

        direction = SignalDirection.HOLD
        confidence = 0.5
        reasoning = "Claude vibes"

        for line in lines:
            line = line.strip()
            if line.startswith("DIRECTION:"):
                dir_str = line.split(":", 1)[1].strip().upper()
                direction_map = {
                    "STRONG_BUY": SignalDirection.STRONG_BUY,
                    "BUY": SignalDirection.BUY,
                    "HOLD": SignalDirection.HOLD,
                    "SELL": SignalDirection.SELL,
                    "STRONG_SELL": SignalDirection.STRONG_SELL,
                }
                direction = direction_map.get(dir_str, SignalDirection.HOLD)
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    confidence = 0.5
            elif line.startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        return Signal(
            strategy_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            reasoning=f"Claude says: {reasoning}",
            timestamp=datetime.utcnow(),
            metadata={"source": "claude_api", "raw_response": response}
        )

    async def _fallback_analyze(
        self,
        symbol: str,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData] | None = None,
    ) -> Signal | None:
        """Simple fallback when Claude API isn't available."""
        if not market_data:
            return None

        # Simple momentum check
        if len(market_data) >= 10:
            recent_change = (market_data[-1].close - market_data[-10].close) / market_data[-10].close

            if recent_change > 0.05:
                direction = SignalDirection.BUY
                reasoning = f"Fallback: Price up {recent_change:.1%} recently"
            elif recent_change < -0.05:
                direction = SignalDirection.SELL
                reasoning = f"Fallback: Price down {recent_change:.1%} recently"
            else:
                direction = SignalDirection.HOLD
                reasoning = f"Fallback: Price stable ({recent_change:.1%})"

            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=direction,
                confidence=0.4,  # Low confidence for fallback
                reasoning=reasoning,
                timestamp=datetime.utcnow(),
                metadata={"source": "fallback"}
            )

        return None
