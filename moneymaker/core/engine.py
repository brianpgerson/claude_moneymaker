"""The main trading engine - orchestrates everything."""

import asyncio
from datetime import datetime
from typing import Any

from anthropic import AsyncAnthropic
from rich.console import Console
from rich.table import Table

from moneymaker.config import Settings
from moneymaker.core.allocator import CapitalAllocator
from moneymaker.core.executor import TradeExecutor
from moneymaker.core.portfolio import PortfolioManager
from moneymaker.data.market import MarketDataFetcher
from moneymaker.data.sentiment import SentimentFetcher
from moneymaker.models import Order, OrderSide, OrderType, Signal, SignalDirection
from moneymaker.strategies import (
    ClaudeVibesStrategy,
    ContrarianStrategy,
    MomentumStrategy,
    SentimentStrategy,
    Strategy,
    StrategyRegistry,
)
from moneymaker.web import StatusServer


class TradingEngine:
    """
    The main event loop that ties everything together.

    Every cycle:
    1. Fetch market data
    2. Fetch sentiment data
    3. Run all strategies
    4. Aggregate signals with capital-weighted averaging
    5. Make trade decisions
    6. Execute trades
    7. Update performance tracking
    8. Possibly rebalance allocations
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.console = Console()

        # Initialize components
        self.market_data = MarketDataFetcher(settings)
        self.sentiment = SentimentFetcher(settings)
        self.executor = TradeExecutor(settings)
        self.portfolio = PortfolioManager(settings)
        self.allocator = CapitalAllocator()

        # Initialize strategy registry
        self.strategies = StrategyRegistry()
        self._init_strategies()

        # Web status server
        self.status_server = StatusServer(self.portfolio)

        # Trading state
        self.symbols: list[str] = ["DOGE/USDT"]  # Start with DOGE
        self.running = False
        self._cycle_count = 0

    def _init_strategies(self) -> None:
        """Initialize and register default strategies."""
        # Create Anthropic client if we have an API key
        anthropic_client = None
        if self.settings.anthropic_api_key:
            anthropic_client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

        # Register strategies
        strategies = [
            MomentumStrategy(allocation=0.30),
            SentimentStrategy(allocation=0.15),
            ContrarianStrategy(allocation=0.15),
            ClaudeVibesStrategy(allocation=0.25, anthropic_client=anthropic_client),
        ]

        for strategy in strategies:
            self.strategies.register(strategy)
            self.allocator.register_strategy(strategy.name, strategy.allocation)

        # Leave 15% as cash reserve
        self.strategies.normalize_allocations()

    async def run_cycle(self) -> dict[str, Any]:
        """
        Run one complete trading cycle.

        Returns summary of what happened.
        """
        self._cycle_count += 1
        cycle_start = datetime.utcnow()
        summary: dict[str, Any] = {
            "cycle": self._cycle_count,
            "timestamp": cycle_start.isoformat(),
            "signals": [],
            "trades": [],
            "portfolio": None,
        }

        self.console.print(f"\n[bold cyan]═══ Cycle {self._cycle_count} @ {cycle_start.strftime('%H:%M:%S')} ═══[/]")

        for symbol in self.symbols:
            self.console.print(f"\n[yellow]Analyzing {symbol}...[/]")

            # 1. Fetch data
            market_data = await self.market_data.fetch_ohlcv(symbol, timeframe="1h", limit=100)
            sentiment_data = await self.sentiment.fetch_all_sentiment(symbol.split("/")[0])

            if not market_data:
                self.console.print(f"[red]No market data for {symbol}, skipping[/]")
                continue

            self.console.print(f"  Got {len(market_data)} candles, {len(sentiment_data)} sentiment points")

            # 2. Run all strategies
            signals: list[Signal] = []
            for strategy in self.strategies.get_enabled():
                try:
                    signal = await strategy.analyze(symbol, market_data, sentiment_data)
                    if signal:
                        signals.append(signal)
                        self.console.print(
                            f"  [{'green' if signal.strength() > 0 else 'red'}]"
                            f"{strategy.name}: {signal.direction.value} "
                            f"(conf: {signal.confidence:.0%})[/]"
                        )
                except Exception as e:
                    self.console.print(f"  [red]{strategy.name} error: {e}[/]")

            summary["signals"].extend([s.model_dump() for s in signals])

            if not signals:
                self.console.print(f"  [dim]No signals for {symbol}[/]")
                continue

            # 3. Aggregate signals with capital weighting
            final_signal = self._aggregate_signals(signals)
            self.console.print(
                f"\n  [bold]Aggregated: {final_signal['direction']} "
                f"(strength: {final_signal['strength']:.2f})[/]"
            )

            # 4. Make trade decision
            trade = await self._decide_trade(symbol, final_signal, market_data[-1].close)
            if trade:
                summary["trades"].append(trade.model_dump())

        # 5. Check if we should rebalance allocations
        if self.allocator.should_rebalance():
            self.console.print("\n[magenta]Rebalancing strategy allocations...[/]")
            new_allocations = self.allocator.rebalance()
            for name, alloc in new_allocations.items():
                strategy = self.strategies.get(name)
                if strategy:
                    strategy.allocation = alloc
            self.console.print(self.allocator.get_rebalance_reasoning())

        # 6. Take portfolio snapshot
        self.portfolio.take_snapshot()
        state = self.portfolio.get_state()
        summary["portfolio"] = {
            "cash": state.cash_balance,
            "total_value": state.total_value,
            "pnl": state.total_pnl,
            "pnl_pct": state.total_pnl_pct,
        }

        # Print summary
        self._print_portfolio_summary()

        # Update status server
        self.status_server.update_cycle(self._cycle_count)

        return summary

    def _aggregate_signals(self, signals: list[Signal]) -> dict[str, Any]:
        """
        Aggregate multiple signals into a final decision.

        Uses capital-weighted averaging based on strategy allocations.
        """
        if not signals:
            return {"direction": "hold", "strength": 0.0, "confidence": 0.0}

        total_weight = 0.0
        weighted_strength = 0.0

        for signal in signals:
            allocation = self.allocator.get_allocation(signal.strategy_name)
            weight = allocation * signal.confidence
            weighted_strength += signal.strength() * weight
            total_weight += weight

        if total_weight == 0:
            return {"direction": "hold", "strength": 0.0, "confidence": 0.0}

        final_strength = weighted_strength / total_weight

        # Determine direction from strength
        if final_strength > 0.4:
            direction = "strong_buy"
        elif final_strength > 0.15:
            direction = "buy"
        elif final_strength < -0.4:
            direction = "strong_sell"
        elif final_strength < -0.15:
            direction = "sell"
        else:
            direction = "hold"

        return {
            "direction": direction,
            "strength": final_strength,
            "confidence": total_weight / len(signals),
            "contributing_strategies": [s.strategy_name for s in signals],
        }

    async def _decide_trade(
        self,
        symbol: str,
        signal: dict[str, Any],
        current_price: float,
    ) -> Order | None:
        """
        Decide whether to trade based on the aggregated signal.

        Considers:
        - Signal strength and direction
        - Current position
        - Available capital
        - Risk limits
        """
        direction = signal["direction"]
        strength = abs(signal["strength"])

        # Skip weak signals
        if direction == "hold" or strength < 0.1:
            self.console.print("  [dim]Signal too weak, holding[/]")
            return None

        state = self.portfolio.get_state()
        position = self.portfolio.get_position(symbol)

        # Calculate position size based on signal strength and available capital
        # Stronger signal = larger position, up to max_position_pct
        capital_to_use = state.cash_balance * self.settings.max_position_pct * strength

        if capital_to_use < self.settings.min_trade_size_usd:
            self.console.print(f"  [dim]Trade size ${capital_to_use:.2f} below minimum[/]")
            return None

        quantity = capital_to_use / current_price

        if direction in ("buy", "strong_buy"):
            order = Order(
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=quantity,
                strategy_name=", ".join(signal.get("contributing_strategies", [])),
                reasoning=f"Aggregated signal: {direction} (strength: {strength:.2f})",
            )
        elif direction in ("sell", "strong_sell"):
            # Can only sell if we have a position
            if not position or position.quantity <= 0:
                self.console.print("  [dim]No position to sell[/]")
                return None

            # Sell proportional to signal strength
            sell_quantity = position.quantity * strength
            order = Order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=sell_quantity,
                strategy_name=", ".join(signal.get("contributing_strategies", [])),
                reasoning=f"Aggregated signal: {direction} (strength: {strength:.2f})",
            )
        else:
            return None

        # Execute the trade
        self.console.print(f"\n  [bold yellow]Executing {order.side.value} {order.quantity:.4f} {symbol}...[/]")
        executed = await self.executor.execute_order(order)

        if executed.status.value == "filled":
            # Update portfolio
            if executed.side == OrderSide.BUY:
                self.portfolio.update_cash(-executed.filled_quantity * executed.filled_price)
                self.portfolio.update_position(symbol, executed.filled_quantity, executed.filled_price)
            else:
                self.portfolio.update_cash(executed.filled_quantity * executed.filled_price)
                self.portfolio.update_position(symbol, -executed.filled_quantity, executed.filled_price)

            # Record order
            self.portfolio.record_order(executed)

            self.console.print(
                f"  [green]✓ Filled @ ${executed.filled_price:.6f}[/]"
            )
        else:
            self.console.print(f"  [red]✗ Order failed: {executed.status.value}[/]")

        return executed

    def _print_portfolio_summary(self) -> None:
        """Print a nice portfolio summary."""
        state = self.portfolio.get_state()

        table = Table(title="Portfolio Status")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        pnl_style = "green" if state.total_pnl >= 0 else "red"

        table.add_row("Cash", f"${state.cash_balance:.2f}")
        table.add_row("Positions Value", f"${state.total_value - state.cash_balance:.2f}")
        table.add_row("Total Value", f"${state.total_value:.2f}")
        table.add_row(
            "P&L",
            f"[{pnl_style}]${state.total_pnl:+.2f} ({state.total_pnl_pct:+.1%})[/]"
        )

        # Add positions
        for symbol, pos in state.positions.items():
            pos_pnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
            table.add_row(
                f"  {symbol}",
                f"{pos.quantity:.4f} @ ${pos.average_entry_price:.6f} "
                f"[{pos_pnl_style}]({pos.unrealized_pnl_pct:+.1%})[/]"
            )

        self.console.print(table)

    async def run(self, cycles: int | None = None) -> None:
        """
        Run the trading loop.

        Args:
            cycles: Number of cycles to run. None = run forever.
        """
        self.running = True
        self.console.print("[bold green]Starting MoneyMaker...[/]")
        self.console.print(f"Mode: {self.settings.trading_mode.value}")
        self.console.print(f"Initial capital: ${self.settings.initial_capital:.2f}")
        self.console.print(f"Symbols: {', '.join(self.symbols)}")
        self.console.print(f"Loop interval: {self.settings.loop_interval_minutes} minutes")

        # Load existing state
        self.portfolio.load_state()

        # Start web status server
        await self.status_server.start()

        cycle_count = 0
        while self.running:
            try:
                await self.run_cycle()
                cycle_count += 1

                if cycles and cycle_count >= cycles:
                    self.console.print(f"\n[yellow]Completed {cycles} cycles, stopping.[/]")
                    break

                # Wait for next cycle
                self.console.print(
                    f"\n[dim]Next cycle in {self.settings.loop_interval_minutes} minutes... "
                    f"(Ctrl+C to stop)[/]"
                )
                await asyncio.sleep(self.settings.loop_interval_minutes * 60)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Stopping...[/]")
                break
            except Exception as e:
                self.console.print(f"[red]Cycle error: {e}[/]")
                await asyncio.sleep(60)  # Wait a minute before retrying

        await self.shutdown()

    async def shutdown(self) -> None:
        """Clean shutdown."""
        self.running = False
        await self.status_server.stop()
        await self.market_data.close()
        await self.executor.close()
        self.portfolio.take_snapshot()
        self.console.print("[green]MoneyMaker stopped. Final portfolio snapshot saved.[/]")
