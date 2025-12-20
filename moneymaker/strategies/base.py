"""Base strategy interface and registry."""

from abc import ABC, abstractmethod
from typing import ClassVar

from moneymaker.models import MarketData, SentimentData, Signal


class Strategy(ABC):
    """Base class for all trading strategies."""

    # Strategy metadata
    name: ClassVar[str] = "base"
    description: ClassVar[str] = "Base strategy"
    default_allocation: ClassVar[float] = 0.1  # Default 10% allocation

    def __init__(self, allocation: float | None = None):
        """Initialize strategy with optional custom allocation."""
        self.allocation = allocation if allocation is not None else self.default_allocation
        self.enabled = True

    @abstractmethod
    async def analyze(
        self,
        symbol: str,
        market_data: list[MarketData],
        sentiment_data: list[SentimentData] | None = None,
    ) -> Signal | None:
        """
        Analyze market data and produce a trading signal.

        Args:
            symbol: Trading pair symbol (e.g., "DOGE/USDT")
            market_data: Historical OHLCV data
            sentiment_data: Optional sentiment data from social sources

        Returns:
            Signal if the strategy has an opinion, None otherwise
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(allocation={self.allocation:.1%})"


class StrategyRegistry:
    """Registry for managing multiple strategies."""

    def __init__(self):
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        """Register a strategy."""
        self._strategies[strategy.name] = strategy

    def unregister(self, name: str) -> None:
        """Unregister a strategy by name."""
        if name in self._strategies:
            del self._strategies[name]

    def get(self, name: str) -> Strategy | None:
        """Get a strategy by name."""
        return self._strategies.get(name)

    def get_all(self) -> list[Strategy]:
        """Get all registered strategies."""
        return list(self._strategies.values())

    def get_enabled(self) -> list[Strategy]:
        """Get all enabled strategies."""
        return [s for s in self._strategies.values() if s.enabled]

    def set_allocation(self, name: str, allocation: float) -> None:
        """Update allocation for a strategy."""
        if name in self._strategies:
            self._strategies[name].allocation = allocation

    def normalize_allocations(self) -> None:
        """Normalize allocations so they sum to 1.0."""
        enabled = self.get_enabled()
        if not enabled:
            return

        total = sum(s.allocation for s in enabled)
        if total > 0:
            for s in enabled:
                s.allocation /= total

    def total_allocation(self) -> float:
        """Get total allocation across all enabled strategies."""
        return sum(s.allocation for s in self.get_enabled())

    def __len__(self) -> int:
        return len(self._strategies)

    def __iter__(self):
        return iter(self._strategies.values())
