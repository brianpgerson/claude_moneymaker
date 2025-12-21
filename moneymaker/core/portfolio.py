"""Portfolio management and tracking."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

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
    - Claude's decisions
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

        # Claude's decisions (for analysis)
        if "decisions" not in self.db.table_names():
            self.db["decisions"].create({
                "id": int,
                "timestamp": str,
                "portfolio_before": str,  # JSON
                "market_summary": str,    # JSON
                "target_allocation": str, # JSON
                "conviction": str,
                "reasoning": str,
                "trades_executed": str,   # JSON
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

    def get_holdings_summary(self) -> list[dict]:
        """
        Get a summary of current holdings for the engine.

        Returns list of dicts with symbol, quantity, value, percent, pnl_pct.
        Always includes USDT (cash).
        """
        state = self.get_state()
        holdings = []

        # Add cash
        if state.cash_balance > 0:
            holdings.append({
                "symbol": "USDT",
                "quantity": state.cash_balance,
                "value": state.cash_balance,
                "percent": (state.cash_balance / state.total_value * 100)
                           if state.total_value > 0 else 100,
                "pnl_pct": 0,
            })

        # Add positions
        for symbol, pos in state.positions.items():
            value = pos.quantity * pos.current_price
            holdings.append({
                "symbol": symbol.replace("/USDT", ""),  # Store without pair suffix
                "quantity": pos.quantity,
                "value": value,
                "percent": (value / state.total_value * 100)
                           if state.total_value > 0 else 0,
                "pnl_pct": pos.unrealized_pnl_pct,
                "entry_price": pos.average_entry_price,
            })

        return holdings

    def sync_from_exchange(self, exchange_balances: dict[str, float]) -> None:
        """
        Sync portfolio state from exchange balances.

        Called in live mode to ensure we have ground truth.
        """
        base = self.settings.base_currency  # USDT

        # Update cash
        self._state.cash_balance = exchange_balances.get(base, 0)

        # Update positions - need to fetch current prices
        # For now, just update quantities
        new_positions = {}
        for symbol, quantity in exchange_balances.items():
            if symbol == base or quantity <= 0:
                continue

            full_symbol = f"{symbol}/{base}"

            if full_symbol in self._state.positions:
                # Keep existing position data, update quantity
                pos = self._state.positions[full_symbol]
                pos.quantity = quantity
                new_positions[full_symbol] = pos
            else:
                # New position - we don't know entry price, use 0
                new_positions[full_symbol] = Position(
                    symbol=full_symbol,
                    quantity=quantity,
                    average_entry_price=0,  # Unknown
                    current_price=0,
                )

        self._state.positions = new_positions

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

    def record_decision(
        self,
        portfolio_before: list[dict],
        market_summary: dict[str, Any],
        target_allocation: list[dict],
        conviction: str | None,
        reasoning: str | None,
        trades_executed: list[dict],
    ) -> None:
        """Record Claude's decision for later analysis."""
        self.db["decisions"].insert({
            "timestamp": datetime.utcnow().isoformat(),
            "portfolio_before": json.dumps(portfolio_before),
            "market_summary": json.dumps(market_summary),
            "target_allocation": json.dumps(target_allocation),
            "conviction": conviction,
            "reasoning": reasoning,
            "trades_executed": json.dumps(trades_executed),
        })

    def get_recent_decisions(self, limit: int = 10) -> list[dict]:
        """Get recent decisions for analysis."""
        decisions = list(self.db["decisions"].rows_where(
            order_by="-id",
            limit=limit,
        ))

        # Parse JSON fields
        for d in decisions:
            d["portfolio_before"] = json.loads(d["portfolio_before"])
            d["market_summary"] = json.loads(d["market_summary"])
            d["target_allocation"] = json.loads(d["target_allocation"])
            d["trades_executed"] = json.loads(d["trades_executed"])

        return decisions

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
