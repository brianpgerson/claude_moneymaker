"""Portfolio management and tracking."""

from datetime import datetime
from pathlib import Path

import sqlite_utils

from moneymaker.config import Settings
from moneymaker.models import Order, OrderStatus, Position, PortfolioState


class PortfolioManager:
    """
    Manages portfolio state, positions, and trade history.

    Tracks:
    - Current cash balance
    - Open positions
    - Trade history
    - P&L over time
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.initial_capital = settings.initial_capital
        self._db: sqlite_utils.Database | None = None
        self._state = PortfolioState(
            cash_balance=settings.initial_capital,
        )

    @property
    def db(self) -> sqlite_utils.Database:
        """Get or create database connection."""
        if self._db is None:
            # Ensure data directory exists
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            self._db = sqlite_utils.Database(self.settings.db_path)
            self._init_tables()
        return self._db

    def _init_tables(self) -> None:
        """Initialize database tables."""
        # Orders table
        if "orders" not in self.db.table_names():
            self.db["orders"].create({
                "id": str,
                "symbol": str,
                "side": str,
                "order_type": str,
                "quantity": float,
                "price": float,
                "status": str,
                "filled_quantity": float,
                "filled_price": float,
                "created_at": str,
                "executed_at": str,
                "strategy_name": str,
                "reasoning": str,
            }, pk="id")

        # Positions table
        if "positions" not in self.db.table_names():
            self.db["positions"].create({
                "symbol": str,
                "quantity": float,
                "average_entry_price": float,
                "updated_at": str,
            }, pk="symbol")

        # Portfolio snapshots
        if "portfolio_snapshots" not in self.db.table_names():
            self.db["portfolio_snapshots"].create({
                "id": int,
                "timestamp": str,
                "cash_balance": float,
                "positions_value": float,
                "total_value": float,
                "total_pnl": float,
                "total_pnl_pct": float,
            }, pk="id")

        # Strategy P&L tracking
        if "strategy_pnl" not in self.db.table_names():
            self.db["strategy_pnl"].create({
                "id": int,
                "strategy_name": str,
                "timestamp": str,
                "trade_pnl": float,
                "trade_pnl_pct": float,
                "cumulative_pnl": float,
            }, pk="id")

    def get_state(self) -> PortfolioState:
        """Get current portfolio state."""
        self._state.calculate_totals(self.initial_capital)
        return self._state

    def get_cash_balance(self) -> float:
        """Get current cash balance."""
        return self._state.cash_balance

    def get_position(self, symbol: str) -> Position | None:
        """Get current position for a symbol."""
        return self._state.positions.get(symbol)

    def get_all_positions(self) -> dict[str, Position]:
        """Get all current positions."""
        return dict(self._state.positions)

    def update_position(
        self,
        symbol: str,
        quantity_delta: float,
        price: float,
    ) -> Position:
        """
        Update a position after a trade.

        Args:
            symbol: Trading pair
            quantity_delta: Change in quantity (positive for buy, negative for sell)
            price: Execution price

        Returns:
            Updated position
        """
        if symbol in self._state.positions:
            pos = self._state.positions[symbol]

            if quantity_delta > 0:  # Buying
                # Update average entry price
                total_cost = (pos.quantity * pos.average_entry_price) + (quantity_delta * price)
                new_quantity = pos.quantity + quantity_delta
                pos.average_entry_price = total_cost / new_quantity if new_quantity > 0 else 0
                pos.quantity = new_quantity
            else:  # Selling
                pos.quantity += quantity_delta  # quantity_delta is negative

            pos.current_price = price
            pos.update_price(price)

            # Remove position if fully closed
            if pos.quantity <= 0:
                del self._state.positions[symbol]
                return pos
        else:
            # New position
            pos = Position(
                symbol=symbol,
                quantity=quantity_delta,
                average_entry_price=price,
                current_price=price,
            )
            self._state.positions[symbol] = pos

        # Save to database
        self.db["positions"].upsert({
            "symbol": symbol,
            "quantity": pos.quantity,
            "average_entry_price": pos.average_entry_price,
            "updated_at": datetime.utcnow().isoformat(),
        }, pk="symbol")

        return pos

    def update_cash(self, delta: float) -> float:
        """Update cash balance. Returns new balance."""
        self._state.cash_balance += delta
        return self._state.cash_balance

    def record_order(self, order: Order) -> None:
        """Save an order to the database."""
        self.db["orders"].insert({
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "quantity": order.quantity,
            "price": order.price,
            "status": order.status.value,
            "filled_quantity": order.filled_quantity,
            "filled_price": order.filled_price,
            "created_at": order.created_at.isoformat(),
            "executed_at": order.executed_at.isoformat() if order.executed_at else None,
            "strategy_name": order.strategy_name,
            "reasoning": order.reasoning,
        })

    def record_strategy_pnl(
        self,
        strategy_name: str,
        trade_pnl: float,
        trade_pnl_pct: float,
    ) -> None:
        """Record P&L for a strategy."""
        # Get cumulative P&L
        existing = list(self.db["strategy_pnl"].rows_where(
            "strategy_name = ?",
            [strategy_name],
            order_by="-id",
            limit=1,
        ))
        cumulative = existing[0]["cumulative_pnl"] if existing else 0

        self.db["strategy_pnl"].insert({
            "strategy_name": strategy_name,
            "timestamp": datetime.utcnow().isoformat(),
            "trade_pnl": trade_pnl,
            "trade_pnl_pct": trade_pnl_pct,
            "cumulative_pnl": cumulative + trade_pnl,
        })

    def take_snapshot(self) -> None:
        """Record current portfolio state."""
        state = self.get_state()

        positions_value = sum(
            p.quantity * p.current_price
            for p in state.positions.values()
        )

        self.db["portfolio_snapshots"].insert({
            "timestamp": datetime.utcnow().isoformat(),
            "cash_balance": state.cash_balance,
            "positions_value": positions_value,
            "total_value": state.total_value,
            "total_pnl": state.total_pnl,
            "total_pnl_pct": state.total_pnl_pct,
        })

    def get_trade_history(
        self,
        strategy_name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get trade history, optionally filtered by strategy."""
        if strategy_name:
            return list(self.db["orders"].rows_where(
                "strategy_name = ?",
                [strategy_name],
                order_by="-created_at",
                limit=limit,
            ))
        return list(self.db["orders"].rows_where(
            order_by="-created_at",
            limit=limit,
        ))

    def load_state(self) -> None:
        """Load state from database on startup."""
        # Load positions
        for row in self.db["positions"].rows:
            self._state.positions[row["symbol"]] = Position(
                symbol=row["symbol"],
                quantity=row["quantity"],
                average_entry_price=row["average_entry_price"],
                current_price=row["average_entry_price"],  # Will be updated
            )

        # Load last snapshot for cash balance
        snapshots = list(self.db["portfolio_snapshots"].rows_where(
            order_by="-id",
            limit=1,
        ))
        if snapshots:
            self._state.cash_balance = snapshots[0]["cash_balance"]
