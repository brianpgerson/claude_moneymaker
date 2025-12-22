"""The brain - Opus 4.5 makes portfolio allocation decisions."""

import json
from datetime import datetime
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel


class Allocation(BaseModel):
    """A single position allocation."""
    symbol: str
    percent: float
    reasoning: str


class PortfolioDecision(BaseModel):
    """Opus's portfolio allocation decision."""
    allocations: list[Allocation]
    usdt_percent: float
    market_outlook: str | None = None
    conviction: str | None = None
    raw_response: dict | None = None


SYSTEM_PROMPT = """You are an aggressive crypto trader managing a small degen portfolio (~$250).
Your goal is to maximize returns. You are NOT here to preserve capital.

TIMING:
- You make decisions every 2 HOURS. After each decision, you cannot react until the next cycle.
- Give trades time to work. If you just entered a position 2-4 hours ago, your thesis probably needs more time to play out.
- Don't churn the portfolio every cycle. Rotating constantly eats fees and kills returns.
- Only exit a position if: (1) your thesis is clearly broken, or (2) you have a significantly better opportunity.

INTERPRETING SIGNALS:
- Volume spikes are NOT automatically bullish. In a downtrending market, high volume often means SELLING pressure (distribution), not buying (accumulation).
- Look at price direction WITH volume: volume spike + price UP = potential accumulation. Volume spike + price DOWN = likely distribution.
- In extreme fear markets, be skeptical of "dip buying" setups - fear can persist longer than expected.
- RSI oversold in a downtrend can stay oversold. Don't catch falling knives just because RSI is low.

REVIEWING YOUR POSITIONS:
- You'll see your thesis for each position (what you said when you entered). Evaluate honestly: is it still valid?
- If a position is down but thesis intact, consider holding or adding. Cutting too early locks in losses.
- If thesis is broken (the setup didn't play out, fundamentals changed), cut it regardless of P&L.

PHILOSOPHY:
- This is gambling money. Act like it.
- Concentration > diversification. Bet big on your best ideas.
- Momentum is everything. Ride winners hard, dump losers fast.
- If you're not uncomfortable, you're not aggressive enough.
- Would rather blow up trying to 10x than slowly bleed out.
- Admit when you're wrong. But also give yourself time to be right.

CONSTRAINTS:
- Minimum position: $10 (Binance minimum) - don't allocate less than 5% to any coin
- Maximum single position: 80% of portfolio
- Cash reserve: 5% minimum (just enough to not get stuck)
- All trades go through USDT pairs
- You can only allocate to coins in the provided universe
- Dust positions (< $1) are automatically filtered out - don't worry about them

OUTPUT:
You must call the set_portfolio_allocation tool with your target allocation.
Include brief reasoning for significant moves.
Allocations + usdt_percent must sum to 100."""


ALLOCATION_TOOL = {
    "name": "set_portfolio_allocation",
    "description": "Set target portfolio allocation. Allocations + usdt_percent must sum to 100%.",
    "input_schema": {
        "type": "object",
        "properties": {
            "allocations": {
                "type": "array",
                "description": "List of coin allocations",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Coin symbol (e.g., DOGE, SHIB, PEPE)"
                        },
                        "percent": {
                            "type": "number",
                            "description": "Percentage of portfolio (0-80)"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief reason for this allocation"
                        }
                    },
                    "required": ["symbol", "percent", "reasoning"]
                }
            },
            "usdt_percent": {
                "type": "number",
                "description": "Percentage to hold in USDT/cash (minimum 5)"
            },
            "market_outlook": {
                "type": "string",
                "enum": ["bullish", "neutral", "bearish"],
                "description": "Overall market sentiment"
            },
            "conviction": {
                "type": "string",
                "enum": ["low", "medium", "high", "maximum"],
                "description": "How confident are you in this allocation?"
            }
        },
        "required": ["allocations", "usdt_percent"]
    }
}


class TradingBrain:
    """Opus 4.5 - the decision maker."""

    def __init__(self, settings=None, api_key: str | None = None, model: str = "claude-opus-4-5-20251101"):
        """Initialize the brain with settings or explicit API key."""
        if settings:
            api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError("Anthropic API key is required")
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def get_allocation_decision(self, market_context: str) -> dict | None:
        """
        Get allocation decision from Opus given market context.

        This is the main entry point used by the engine.
        Returns the raw decision dict or None if no decision.
        """
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[ALLOCATION_TOOL],
            tool_choice={"type": "tool", "name": "set_portfolio_allocation"},
            messages=[{"role": "user", "content": market_context}]
        )

        # Extract tool call
        for block in response.content:
            if block.type == "tool_use" and block.name == "set_portfolio_allocation":
                return block.input

        return None

    def _format_portfolio(self, holdings: dict[str, dict]) -> str:
        """Format current holdings for the prompt."""
        if not holdings:
            return "No current holdings (100% USDT)"

        lines = []
        for symbol, data in holdings.items():
            if symbol == "USDT":
                continue
            lines.append(
                f"- {symbol}: {data['quantity']:.4f} (${data['value']:.2f}, "
                f"{data['percent']:.1f}%, P&L: {data.get('pnl_pct', 0):+.1f}%)"
            )
        return "\n".join(lines) if lines else "No crypto holdings (100% USDT)"

    def _format_market_data(self, coins: list[dict]) -> str:
        """Format market data table for the prompt."""
        lines = ["| Symbol | Price | 24h % | RSI | MACD | Volume |"]
        lines.append("|--------|-------|-------|-----|------|--------|")

        for coin in coins[:50]:  # Top 50
            symbol = coin.get("symbol", "???").replace("/USDT", "")
            price = coin.get("price", 0)
            change_24h = coin.get("change_24h", 0)
            rsi = coin.get("rsi", 50)
            macd = coin.get("macd_signal", "neutral")
            volume = coin.get("volume_24h", 0)

            # Format price smartly
            if price < 0.0001:
                price_str = f"${price:.8f}"
            elif price < 1:
                price_str = f"${price:.6f}"
            else:
                price_str = f"${price:.2f}"

            # Format volume
            if volume > 1_000_000_000:
                vol_str = f"${volume/1_000_000_000:.1f}B"
            elif volume > 1_000_000:
                vol_str = f"${volume/1_000_000:.1f}M"
            else:
                vol_str = f"${volume/1_000:.0f}K"

            lines.append(
                f"| {symbol:6} | {price_str:>10} | {change_24h:>+6.1f}% | "
                f"{rsi:>3.0f} | {macd:>6} | {vol_str:>7} |"
            )

        return "\n".join(lines)

    def _format_notable_setups(self, coins: list[dict]) -> str:
        """Identify and format notable trading setups."""
        setups = []

        for coin in coins[:50]:
            symbol = coin.get("symbol", "???").replace("/USDT", "")
            rsi = coin.get("rsi", 50)
            change_24h = coin.get("change_24h", 0)
            macd = coin.get("macd_signal", "neutral")

            reasons = []

            if rsi < 30:
                reasons.append(f"RSI oversold ({rsi:.0f})")
            elif rsi > 70:
                reasons.append(f"RSI overbought ({rsi:.0f})")

            if change_24h > 15:
                reasons.append(f"pumping +{change_24h:.1f}%")
            elif change_24h < -15:
                reasons.append(f"dumping {change_24h:.1f}%")

            if macd == "bullish_cross":
                reasons.append("MACD bullish crossover")
            elif macd == "bearish_cross":
                reasons.append("MACD bearish crossover")

            if reasons:
                setups.append(f"- {symbol}: {', '.join(reasons)}")

        return "\n".join(setups) if setups else "No notable setups detected"

    async def decide(
        self,
        total_value: float,
        holdings: dict[str, dict],
        market_data: list[dict],
        fear_greed: dict | None = None,
    ) -> PortfolioDecision:
        """
        Ask Opus to decide portfolio allocation.

        Args:
            total_value: Total portfolio value in USD
            holdings: Current holdings {symbol: {quantity, value, percent, pnl_pct}}
            market_data: List of coin data with technicals
            fear_greed: Fear & Greed index data

        Returns:
            PortfolioDecision with target allocations
        """
        # Build the prompt
        fg_score = fear_greed.get("value", 50) if fear_greed else 50
        fg_label = fear_greed.get("label", "Neutral") if fear_greed else "Unknown"

        # Find BTC in market data for context
        btc_change = 0
        for coin in market_data:
            if coin.get("symbol") == "BTC/USDT":
                btc_change = coin.get("change_24h", 0)
                break

        prompt = f"""CURRENT PORTFOLIO:
Total value: ${total_value:.2f}
Holdings:
{self._format_portfolio(holdings)}

MARKET CONTEXT:
- Fear & Greed Index: {fg_score} ({fg_label})
- BTC 24h: {btc_change:+.1f}%

TOP 50 COINS BY VOLUME (your universe):
{self._format_market_data(market_data)}

NOTABLE SETUPS:
{self._format_notable_setups(market_data)}

---

Set your target portfolio allocation."""

        # Call Opus with tool use
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[ALLOCATION_TOOL],
            tool_choice={"type": "tool", "name": "set_portfolio_allocation"},
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract tool call
        for block in response.content:
            if block.type == "tool_use" and block.name == "set_portfolio_allocation":
                args = block.input

                allocations = [
                    Allocation(
                        symbol=a["symbol"],
                        percent=a["percent"],
                        reasoning=a["reasoning"]
                    )
                    for a in args.get("allocations", [])
                ]

                return PortfolioDecision(
                    allocations=allocations,
                    usdt_percent=args.get("usdt_percent", 5),
                    market_outlook=args.get("market_outlook"),
                    conviction=args.get("conviction"),
                    raw_response=args
                )

        # Fallback if no tool call (shouldn't happen with tool_choice)
        return PortfolioDecision(
            allocations=[],
            usdt_percent=100,
            market_outlook="neutral",
            conviction="low",
            raw_response={"error": "No tool call in response"}
        )
