"""Trading strategies module."""

from moneymaker.strategies.base import Strategy, StrategyRegistry
from moneymaker.strategies.momentum import MomentumStrategy
from moneymaker.strategies.sentiment import SentimentStrategy
from moneymaker.strategies.contrarian import ContrarianStrategy
from moneymaker.strategies.claude_vibes import ClaudeVibesStrategy

__all__ = [
    "Strategy",
    "StrategyRegistry",
    "MomentumStrategy",
    "SentimentStrategy",
    "ContrarianStrategy",
    "ClaudeVibesStrategy",
]
