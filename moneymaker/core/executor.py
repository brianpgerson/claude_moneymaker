"""Trade execution - both paper and live."""

import uuid
from datetime import datetime

import ccxt.async_support as ccxt

from moneymaker.config import Exchange, Settings, TradingMode
from moneymaker.models import Order, OrderSide, OrderStatus, OrderType


class TradeExecutor:
    """
    Executes trades on exchanges.

    Supports:
    - Paper trading (simulated)
    - Live trading (real money)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._exchange: ccxt.Exchange | None = None

    async def _get_exchange(self) -> ccxt.Exchange:
        """Get or create exchange instance."""
        if self._exchange is not None:
            return self._exchange

        api_key, api_secret = self.settings.get_exchange_credentials(
            self.settings.preferred_exchange
        )

        exchange_classes = {
            Exchange.COINBASE: ccxt.coinbase,
            Exchange.BINANCE: ccxt.binance,
            Exchange.KRAKEN: ccxt.kraken,
        }

        exchange_class = exchange_classes[self.settings.preferred_exchange]

        # For paper trading, we don't actually need real credentials
        self._exchange = exchange_class({
            "apiKey": api_key or "paper_trading",
            "secret": api_secret or "paper_trading",
            "sandbox": self.settings.trading_mode == TradingMode.PAPER,
            "enableRateLimit": True,
        })

        return self._exchange

    async def execute_order(self, order: Order) -> Order:
        """
        Execute an order.

        For paper trading, simulates execution at current market price.
        For live trading, actually places the order on the exchange.
        """
        if self.settings.trading_mode == TradingMode.PAPER:
            return await self._execute_paper(order)
        else:
            return await self._execute_live(order)

    async def _execute_paper(self, order: Order) -> Order:
        """Simulate order execution for paper trading."""
        exchange = await self._get_exchange()

        try:
            # Get current price
            ticker = await exchange.fetch_ticker(order.symbol)
            current_price = ticker["last"]

            # Simulate fill
            order.id = f"paper_{uuid.uuid4().hex[:12]}"
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.filled_price = current_price
            order.executed_at = datetime.utcnow()

            return order

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.reasoning = f"Paper trade failed: {e}"
            return order

    async def _execute_live(self, order: Order) -> Order:
        """Execute a real order on the exchange."""
        exchange = await self._get_exchange()

        try:
            if order.order_type == OrderType.MARKET:
                if order.side == OrderSide.BUY:
                    result = await exchange.create_market_buy_order(
                        order.symbol,
                        order.quantity,
                    )
                else:
                    result = await exchange.create_market_sell_order(
                        order.symbol,
                        order.quantity,
                    )
            else:  # LIMIT
                result = await exchange.create_limit_order(
                    order.symbol,
                    order.side.value,
                    order.quantity,
                    order.price,
                )

            order.id = result["id"]
            order.filled_quantity = result.get("filled", order.quantity)
            order.filled_price = result.get("average", result.get("price"))
            order.executed_at = datetime.utcnow()

            # Determine status
            if result.get("status") == "closed":
                order.status = OrderStatus.FILLED
            elif result.get("status") == "canceled":
                order.status = OrderStatus.CANCELLED
            elif order.filled_quantity > 0:
                order.status = OrderStatus.PARTIALLY_FILLED
            else:
                order.status = OrderStatus.PENDING

            return order

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.reasoning = f"Order failed: {e}"
            return order

    async def get_balance(self, currency: str = "USDT") -> float:
        """Get current balance for a currency."""
        if self.settings.trading_mode == TradingMode.PAPER:
            # For paper trading, we track balance internally
            return 0.0  # Portfolio manager handles this

        exchange = await self._get_exchange()
        try:
            balance = await exchange.fetch_balance()
            return balance.get(currency, {}).get("free", 0.0)
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0.0

    async def get_current_price(self, symbol: str) -> float | None:
        """Get current price for a symbol."""
        exchange = await self._get_exchange()
        try:
            ticker = await exchange.fetch_ticker(symbol)
            return ticker["last"]
        except Exception as e:
            print(f"Error fetching price for {symbol}: {e}")
            return None

    async def close(self):
        """Close the exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
