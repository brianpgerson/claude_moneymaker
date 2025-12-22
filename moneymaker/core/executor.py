"""Trade execution - both paper and live."""

import uuid
from datetime import datetime
from typing import Any

import ccxt.async_support as ccxt
from rich.console import Console

from moneymaker.config import Exchange, Settings, TradingMode
from moneymaker.models import Order, OrderSide, OrderStatus, OrderType

console = Console()


class TradeExecutor:
    """
    Executes trades on exchanges.

    Supports:
    - Paper trading (simulated with real market data)
    - Live trading (real money)

    Key responsibilities:
    - Sync balances from exchange
    - Cancel all pending orders
    - Execute target allocations (sells first, then buys)
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
            Exchange.BINANCEUS: ccxt.binanceus,
            Exchange.KRAKEN: ccxt.kraken,
        }

        exchange_class = exchange_classes[self.settings.preferred_exchange]

        # For paper trading, don't pass API credentials - just use public endpoints
        # For live trading, credentials are required
        config = {
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
            },
        }

        if self.settings.trading_mode == TradingMode.LIVE and api_key and api_secret:
            config["apiKey"] = api_key
            config["secret"] = api_secret
            config["options"]["warnOnFetchOpenOrdersWithoutSymbol"] = False
            console.print(f"[green]LIVE MODE: Using Binance API credentials (key: {api_key[:8]}...)[/]")
        elif self.settings.trading_mode == TradingMode.LIVE:
            console.print(f"[red]LIVE MODE WARNING: No API credentials found! api_key={bool(api_key)}, api_secret={bool(api_secret)}[/]")
        else:
            console.print(f"[yellow]PAPER MODE: Using public endpoints (no credentials)[/]")

        self._exchange = exchange_class(config)

        return self._exchange

    async def sync_balances(self) -> dict[str, float] | None:
        """
        Sync balances from the exchange.

        Returns dict of {symbol: quantity} for all non-zero balances.
        Returns None on API failure (caller should not sync to empty state).
        For paper trading, returns empty dict (portfolio manager tracks internally).
        """
        if self.settings.trading_mode == TradingMode.PAPER:
            return {}

        exchange = await self._get_exchange()

        try:
            balance = await exchange.fetch_balance()

            # Extract non-zero balances
            holdings = {}
            for currency, amounts in balance.items():
                if isinstance(amounts, dict) and amounts.get("total", 0) > 0:
                    holdings[currency] = amounts["total"]

            return holdings

        except Exception as e:
            console.print(f"[red]Error syncing balances: {e}[/]")
            return None  # Return None to indicate failure, not empty state

    async def cancel_all_orders(self) -> list[str]:
        """
        Cancel all open orders on the exchange.

        Called at the start of each cycle to ensure clean state.
        Returns list of cancelled order IDs.
        """
        if self.settings.trading_mode == TradingMode.PAPER:
            return []  # No orders to cancel in paper mode

        exchange = await self._get_exchange()
        cancelled = []

        try:
            # Fetch all open orders
            open_orders = await exchange.fetch_open_orders()

            for order in open_orders:
                try:
                    await exchange.cancel_order(order["id"], order.get("symbol"))
                    cancelled.append(order["id"])
                except Exception as e:
                    print(f"Failed to cancel order {order['id']}: {e}")

            if cancelled:
                print(f"Cancelled {len(cancelled)} open orders")

            return cancelled

        except Exception as e:
            print(f"Error fetching/cancelling orders: {e}")
            return cancelled

    async def execute_target_allocation(
        self,
        current_holdings: dict[str, float],
        target_allocation: list[dict],
        total_value: float,
        prices: dict[str, float],
    ) -> list[Order]:
        """
        Execute trades to move from current holdings to target allocation.

        Args:
            current_holdings: Dict of {symbol: quantity} we currently own
            target_allocation: List of {symbol, percent, reasoning} from Claude
            total_value: Total portfolio value in USDT
            prices: Current prices for all symbols

        Returns:
            List of executed orders

        Strategy:
        1. Calculate what we need to sell (positions not in target or reducing)
        2. Calculate what we need to buy
        3. Execute sells first to free up USDT
        4. Execute buys with available USDT
        """
        base = self.settings.base_currency  # USDT
        orders = []

        # Build target allocation map
        target_map = {a["symbol"]: a["percent"] / 100.0 for a in target_allocation}

        # Calculate target values
        target_values = {sym: pct * total_value for sym, pct in target_map.items()}

        # Calculate current values (excluding base currency and dust < $1)
        current_values = {}
        for sym, qty in current_holdings.items():
            if sym != base and qty > 0:
                price = prices.get(f"{sym}/{base}")
                if price is not None and price > 0:
                    value = qty * price
                    if value < 1.0:  # Skip dust positions
                        continue
                    current_values[sym] = value
                else:
                    console.print(f"[yellow]  Warning: No valid price for {sym}, skipping[/]")

        # Determine sells (reduce or exit positions)
        sells = []
        for sym, current_val in current_values.items():
            target_val = target_values.get(sym, 0)
            diff = current_val - target_val

            if diff > self.settings.min_trade_size_usd:
                # Need to sell some
                price = prices.get(f"{sym}/{base}")
                if price is not None and price > 0:
                    qty_to_sell = diff / price
                    sells.append({
                        "symbol": f"{sym}/{base}",
                        "quantity": qty_to_sell,
                        "value": diff,
                    })
                else:
                    console.print(f"[red]  Cannot sell {sym}: no valid price[/]")

        # Determine buys (new or increasing positions)
        buys = []
        for sym, target_val in target_values.items():
            current_val = current_values.get(sym, 0)
            diff = target_val - current_val

            if diff > self.settings.min_trade_size_usd:
                # Need to buy some
                price = prices.get(f"{sym}/{base}")
                if price is not None and price > 0:
                    qty_to_buy = diff / price
                    buys.append({
                        "symbol": f"{sym}/{base}",
                        "quantity": qty_to_buy,
                        "value": diff,
                    })
                else:
                    console.print(f"[red]  Cannot buy {sym}: no valid price[/]")

        # Execute sells first
        for sell in sells:
            order = Order(
                symbol=sell["symbol"],
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=sell["quantity"],
                strategy_name="brain",
                reasoning=f"Rebalancing: reducing position by ${sell['value']:.2f}",
            )
            executed = await self.execute_order(order)
            orders.append(executed)

        # Execute buys
        for buy in buys:
            order = Order(
                symbol=buy["symbol"],
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=buy["quantity"],
                strategy_name="brain",
                reasoning=f"Rebalancing: adding ${buy['value']:.2f} to position",
            )
            executed = await self.execute_order(order)
            orders.append(executed)

        return orders

    async def execute_order(self, order: Order) -> Order:
        """
        Execute an order.

        For paper trading, simulates execution at current market price.
        For live trading, actually places the order on the exchange.
        """
        if self.settings.trading_mode == TradingMode.PAPER:
            console.print(f"[yellow]PAPER: Simulating {order.side.value} {order.quantity:.4f} {order.symbol}[/]")
            return await self._execute_paper(order)
        else:
            console.print(f"[bold green]LIVE: Executing {order.side.value} {order.quantity:.4f} {order.symbol}[/]")
            return await self._execute_live(order)

    async def _execute_paper(self, order: Order) -> Order:
        """Simulate order execution for paper trading."""
        exchange = await self._get_exchange()

        try:
            # Get current price from real market data
            ticker = await exchange.fetch_ticker(order.symbol)
            current_price = ticker["last"]

            # Simulate fill with small slippage
            slippage = 0.001  # 0.1% slippage
            if order.side == OrderSide.BUY:
                fill_price = current_price * (1 + slippage)
            else:
                fill_price = current_price * (1 - slippage)

            order.id = f"paper_{uuid.uuid4().hex[:12]}"
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.filled_price = fill_price
            order.executed_at = datetime.utcnow()

            return order

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.reasoning = f"Paper trade failed: {e}"
            return order

    async def _execute_live(self, order: Order) -> Order:
        """Execute a real order on the exchange."""
        console.print(f"[cyan]LIVE ORDER: {order.side.value.upper()} {order.quantity} {order.symbol}[/]")
        exchange = await self._get_exchange()

        try:
            if order.order_type == OrderType.MARKET:
                if order.side == OrderSide.BUY:
                    console.print(f"[cyan]  Sending market buy to Binance...[/]")
                    result = await exchange.create_market_buy_order(
                        order.symbol,
                        order.quantity,
                    )
                else:
                    console.print(f"[cyan]  Sending market sell to Binance...[/]")
                    result = await exchange.create_market_sell_order(
                        order.symbol,
                        order.quantity,
                    )
            else:  # LIMIT
                console.print(f"[cyan]  Sending limit order to Binance...[/]")
                result = await exchange.create_limit_order(
                    order.symbol,
                    order.side.value,
                    order.quantity,
                    order.price,
                )

            console.print(f"[green]  Binance response: id={result.get('id')}, status={result.get('status')}, filled={result.get('filled')}[/]")

            order.id = result["id"]
            order.filled_quantity = result.get("filled") or result.get("amount") or order.quantity
            # Get filled price with multiple fallbacks
            filled_price = result.get("average") or result.get("price") or result.get("cost")
            if filled_price is None and result.get("cost") and order.filled_quantity:
                # Calculate from cost / quantity if available
                filled_price = result.get("cost") / order.filled_quantity
            order.filled_price = filled_price or 0
            order.executed_at = datetime.utcnow()

            if order.filled_price == 0:
                console.print(f"[red]  Warning: Could not determine fill price from response[/]")

            # Determine status
            if result.get("status") == "closed":
                order.status = OrderStatus.FILLED
                console.print(f"[green]  Order FILLED @ ${order.filled_price:.6f}[/]")
            elif result.get("status") == "canceled":
                order.status = OrderStatus.CANCELLED
                console.print(f"[yellow]  Order CANCELLED[/]")
            elif order.filled_quantity > 0:
                order.status = OrderStatus.PARTIALLY_FILLED
                console.print(f"[yellow]  Order PARTIALLY FILLED[/]")
            else:
                order.status = OrderStatus.PENDING
                console.print(f"[yellow]  Order PENDING[/]")

            return order

        except Exception as e:
            console.print(f"[red]  LIVE ORDER FAILED: {e}[/]")
            order.status = OrderStatus.FAILED
            order.reasoning = f"Order failed: {e}"
            return order

    async def get_balance(self, currency: str = "USDT") -> float:
        """Get current balance for a currency."""
        if self.settings.trading_mode == TradingMode.PAPER:
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

    async def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """Get current prices for multiple symbols."""
        exchange = await self._get_exchange()
        prices = {}

        try:
            # Fetch all tickers at once if possible
            tickers = await exchange.fetch_tickers(symbols)
            for symbol, ticker in tickers.items():
                if ticker and ticker.get("last"):
                    prices[symbol] = ticker["last"]
        except Exception as e:
            # Fallback to individual fetches
            console.print(f"[yellow]Bulk ticker fetch failed, falling back: {e}[/]")
            for symbol in symbols:
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    prices[symbol] = ticker["last"]
                except Exception as e2:
                    console.print(f"[red]  Failed to fetch price for {symbol}: {e2}[/]")

        # Report any missing prices
        missing = set(symbols) - set(prices.keys())
        if missing:
            console.print(f"[yellow]  Missing prices for: {', '.join(missing)}[/]")

        return prices

    async def close(self):
        """Close the exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
