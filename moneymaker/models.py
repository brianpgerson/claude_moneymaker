"""Core data models for the trading system."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    """Trading signal direction."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MarketData(BaseModel):
    """OHLCV market data for a trading pair."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def price(self) -> float:
        return self.close


class SentimentData(BaseModel):
    """Sentiment analysis results."""
    symbol: str
    timestamp: datetime
    source: str  # reddit, twitter, news
    score: float  # -1.0 (bearish) to 1.0 (bullish)
    volume: int  # Number of mentions
    sample_texts: list[str] = Field(default_factory=list)


class Signal(BaseModel):
    """A trading signal from a strategy."""
    strategy_name: str
    symbol: str
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0)  # 0-1 confidence
    reasoning: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def strength(self) -> float:
        """Convert direction + confidence to a numeric strength (-1 to 1)."""
        direction_weights = {
            SignalDirection.STRONG_BUY: 1.0,
            SignalDirection.BUY: 0.5,
            SignalDirection.HOLD: 0.0,
            SignalDirection.SELL: -0.5,
            SignalDirection.STRONG_SELL: -1.0,
        }
        return direction_weights[self.direction] * self.confidence


class Order(BaseModel):
    """A trade order."""
    id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None  # None for market orders
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: datetime | None = None
    strategy_name: str | None = None
    reasoning: str | None = None


class Position(BaseModel):
    """Current position in an asset."""
    symbol: str
    quantity: float
    average_entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    def update_price(self, new_price: float) -> None:
        """Update current price and recalculate PnL."""
        self.current_price = new_price
        self.unrealized_pnl = (new_price - self.average_entry_price) * self.quantity
        if self.average_entry_price > 0:
            self.unrealized_pnl_pct = (new_price - self.average_entry_price) / self.average_entry_price


class StrategyPerformance(BaseModel):
    """Performance metrics for a strategy."""
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    sharpe_ratio: float | None = None
    max_drawdown: float = 0.0
    current_allocation: float = 0.0  # Current % of capital allocated

    def update_metrics(self, trade_pnl: float, is_winner: bool) -> None:
        """Update metrics after a trade."""
        self.total_trades += 1
        self.total_pnl += trade_pnl

        if is_winner:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades


class PortfolioState(BaseModel):
    """Current state of the portfolio."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    cash_balance: float
    positions: dict[str, Position] = Field(default_factory=dict)
    total_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0

    def calculate_totals(self, initial_capital: float) -> None:
        """Recalculate total portfolio value and PnL."""
        positions_value = sum(
            p.quantity * p.current_price
            for p in self.positions.values()
        )
        self.total_value = self.cash_balance + positions_value
        self.total_pnl = self.total_value - initial_capital
        if initial_capital > 0:
            self.total_pnl_pct = self.total_pnl / initial_capital
