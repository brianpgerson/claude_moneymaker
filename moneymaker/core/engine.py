"""The main trading engine - orchestrates everything."""

import asyncio
import json
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.table import Table

from moneymaker.config import Settings, TradingMode
from moneymaker.core.brain import TradingBrain
from moneymaker.core.executor import TradeExecutor
from moneymaker.core.portfolio import PortfolioManager
from moneymaker.data.market import MarketDataFetcher
from moneymaker.data.sentiment import SentimentFetcher
from moneymaker.web import StatusServer


class TradingEngine:
    """
    The main event loop that ties everything together.

    Every 2-hour cycle:
    1. Sync balances from exchange (ground truth)
    2. Cancel any pending orders (clean slate)
    3. Fetch top 50 coins by volume (trading universe)
    4. Get OHLCV + technicals for each
    5. Get Fear & Greed Index
    6. Build market brief for Claude
    7. Call Opus 4.5 for portfolio allocation decision
    8. Execute trades (sells first, then buys)
    9. Record decision and snapshot
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.console = Console()

        # Initialize components
        self.market_data = MarketDataFetcher(settings)
        self.sentiment = SentimentFetcher(settings)
        self.executor = TradeExecutor(settings)
        self.portfolio = PortfolioManager(settings)
        self.brain = TradingBrain(settings)

        # Web status server
        self.status_server = StatusServer(self.portfolio)

        # Trading state
        self.running = False
        self._cycle_count = 0

    async def run_cycle(self) -> dict[str, Any]:
        """
        Run one complete trading cycle.

        Returns summary of what happened.
        """
        self._cycle_count += 1
        cycle_start = datetime.utcnow()

        self.console.print(
            f"\n[bold cyan]═══ Cycle {self._cycle_count} @ "
            f"{cycle_start.strftime('%Y-%m-%d %H:%M:%S')} ═══[/]"
        )

        summary: dict[str, Any] = {
            "cycle": self._cycle_count,
            "timestamp": cycle_start.isoformat(),
            "trades": [],
            "decision": None,
            "portfolio": None,
        }

        # Step 1: Cancel pending orders
        self.console.print("\n[yellow]Cancelling pending orders...[/]")
        cancelled = await self.executor.cancel_all_orders()
        if cancelled:
            self.console.print(f"  Cancelled {len(cancelled)} orders")

        # Step 2: Sync balances from exchange
        self.console.print("[yellow]Syncing balances...[/]")
        if self.settings.trading_mode == TradingMode.LIVE:
            exchange_balances = await self.executor.sync_balances()

            if exchange_balances is None:
                self.console.print("[red]  Failed to sync balances from exchange! Using cached state.[/]")
                # Don't sync - keep existing portfolio state
            else:
                self.portfolio.sync_from_exchange(exchange_balances)

                # Fetch current prices for all positions
                base = self.settings.base_currency
                symbols = [f"{sym}/{base}" for sym in exchange_balances.keys() if sym != base and exchange_balances[sym] > 0]
                if symbols:
                    prices = await self.executor.get_prices(symbols)
                    state = self.portfolio.get_state()
                    for symbol, price in prices.items():
                        if symbol in state.positions:
                            pos = state.positions[symbol]
                            # If no entry price, use current as entry (first sync)
                            if pos.average_entry_price == 0:
                                pos.average_entry_price = price
                            # Update price and recalculate P&L
                            pos.update_price(price)

                self.console.print(f"  Synced {len(exchange_balances)} holdings")
        else:
            self.console.print("  [dim]Paper mode - using internal tracking[/]")

        # Get current portfolio state
        state = self.portfolio.get_state()
        holdings = self.portfolio.get_holdings_summary()

        self.console.print(f"\n[bold]Current Portfolio: ${state.total_value:.2f}[/]")
        for h in holdings:
            pnl_style = "green" if h.get("pnl_pct", 0) >= 0 else "red"
            self.console.print(
                f"  {h['symbol']}: {h['quantity']:.4f} "
                f"(${h['value']:.2f}, [{pnl_style}]{h.get('pnl_pct', 0):+.1%}[/])"
            )

        # Step 3: Fetch trading universe (top 50 by volume)
        self.console.print("\n[yellow]Fetching trading universe...[/]")
        universe = await self.market_data.get_universe(
            limit=self.settings.universe_size
        )
        self.console.print(f"  Got {len(universe)} tradeable coins")

        if not universe:
            self.console.print("[red]No market data available, skipping cycle[/]")
            return summary

        # Step 4: Fetch sentiment
        self.console.print("[yellow]Fetching market sentiment...[/]")
        fear_greed = await self.sentiment.get_fear_greed_index()
        self.console.print(
            f"  Fear & Greed: {fear_greed.get('value', 'N/A')} "
            f"({fear_greed.get('classification', 'Unknown')})"
        )

        # Get recent trades for context
        recent_trades = self.portfolio.get_trade_history(limit=10)

        # Get position theses and last decision for context
        position_theses = self.portfolio.get_position_theses()
        last_decision = self.portfolio.get_last_decision()

        # Step 5: Build market context for Claude
        market_context = self._build_market_context(
            holdings=holdings,
            universe=universe,
            recent_trades=recent_trades,
            position_theses=position_theses,
            last_decision=last_decision,
            fear_greed=fear_greed,
            total_value=state.total_value,
        )

        # Step 6: Call Opus for decision
        self.console.print("\n[bold magenta]Consulting Opus 4.5...[/]")
        decision = await self.brain.get_allocation_decision(market_context)

        if not decision:
            self.console.print("[red]No decision from Claude, skipping cycle[/]")
            return summary

        summary["decision"] = decision

        # Display decision
        self.console.print(f"\n[bold]Decision: {decision.get('market_outlook', 'N/A')} "
                          f"(conviction: {decision.get('conviction', 'N/A')})[/]")

        for alloc in decision.get("allocations", []):
            self.console.print(
                f"  {alloc['symbol']}: {alloc['percent']}% - {alloc['reasoning']}"
            )
        self.console.print(f"  USDT: {decision.get('usdt_percent', 0)}%")

        # Store theses for each position
        self.portfolio.update_position_theses(decision.get("allocations", []))

        # Step 7: Execute trades
        self.console.print("\n[yellow]Executing trades...[/]")

        # Get current prices for all symbols we might trade
        all_symbols = set()
        for alloc in decision.get("allocations", []):
            sym = alloc["symbol"]
            if not sym.endswith("/USDT"):
                sym = f"{sym}/USDT"
            all_symbols.add(sym)
        for h in holdings:
            if h["symbol"] != "USDT":
                all_symbols.add(f"{h['symbol']}/USDT")

        prices = await self.executor.get_prices(list(all_symbols))

        # Build current holdings dict
        current_holdings = {h["symbol"]: h["quantity"] for h in holdings}

        # Execute target allocation
        orders = await self.executor.execute_target_allocation(
            current_holdings=current_holdings,
            target_allocation=decision.get("allocations", []),
            total_value=state.total_value,
            prices=prices,
        )

        for order in orders:
            status_color = "green" if order.status.value == "filled" else "red"
            self.console.print(
                f"  [{status_color}]{order.side.value.upper()} {order.quantity:.4f} "
                f"{order.symbol} @ ${order.filled_price or 0:.6f}[/]"
            )

            # Update portfolio for paper trading
            if self.settings.trading_mode == TradingMode.PAPER:
                if order.status.value == "filled":
                    self._update_paper_portfolio(order)

            # Record order
            self.portfolio.record_order(order)

        summary["trades"] = [o.model_dump() for o in orders]

        # Re-sync balances after live trades
        if self.settings.trading_mode == TradingMode.LIVE and orders:
            self.console.print("[yellow]Re-syncing balances after trades...[/]")
            exchange_balances = await self.executor.sync_balances()

            if exchange_balances is not None:
                self.portfolio.sync_from_exchange(exchange_balances)

                # Fetch current prices for all positions and update P&L
                base = self.settings.base_currency
                symbols = [f"{sym}/{base}" for sym in exchange_balances.keys() if sym != base and exchange_balances[sym] > 0]
                if symbols:
                    prices = await self.executor.get_prices(symbols)
                    state = self.portfolio.get_state()
                    for symbol, price in prices.items():
                        if symbol in state.positions:
                            pos = state.positions[symbol]
                            # If no entry price, use current as entry
                            if pos.average_entry_price == 0:
                                pos.average_entry_price = price
                            pos.update_price(price)

                self.console.print(f"  Synced {len(exchange_balances)} holdings from exchange")
            else:
                self.console.print("[red]  Failed to re-sync balances after trades[/]")

        # Step 8: Record decision
        self.portfolio.record_decision(
            portfolio_before=holdings,
            market_summary={
                "fear_greed": fear_greed,
                "universe_size": len(universe),
                "top_movers": universe[:5],
            },
            target_allocation=decision.get("allocations", []),
            conviction=decision.get("conviction"),
            reasoning=decision.get("market_outlook"),
            trades_executed=summary["trades"],
        )

        # Step 9: Take snapshot with BTC price for benchmarking
        btc_price = None
        for coin in universe:
            if coin.get("symbol") == "BTC/USDT":
                btc_price = coin.get("price")
                break
        self.portfolio.take_snapshot(btc_price=btc_price)
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

    def _build_market_context(
        self,
        holdings: list[dict],
        universe: list[dict],
        recent_trades: list[dict],
        position_theses: dict[str, dict],
        last_decision: dict | None,
        fear_greed: dict,
        total_value: float,
    ) -> str:
        """Build the market context string for Claude."""
        lines = []

        # Last decision feedback
        if last_decision:
            lines.append("YOUR LAST DECISION:")
            lines.append(f"  Outlook: {last_decision.get('reasoning', 'N/A')}")
            lines.append(f"  Conviction: {last_decision.get('conviction', 'N/A')}")
            lines.append(f"  Time: {last_decision.get('timestamp', 'unknown')[:16]}")
            allocs = last_decision.get('target_allocation', [])
            if isinstance(allocs, list):
                for a in allocs:
                    lines.append(f"    {a.get('symbol', '?')}: {a.get('percent', 0)}% - {a.get('reasoning', '')[:60]}")
            lines.append("")

        # Portfolio section with drawdown info
        initial_capital = self.settings.initial_capital
        drawdown = ((total_value - initial_capital) / initial_capital) * 100
        lines.append("CURRENT PORTFOLIO:")
        lines.append(f"Total value: ${total_value:.2f} (Started: ${initial_capital:.2f}, {drawdown:+.1f}%)")
        lines.append("Holdings:")

        for h in holdings:
            symbol = h['symbol']
            if symbol == "USDT":
                lines.append(f"  USDT (cash): ${h['value']:.2f} ({h.get('percent', 0):.1f}% of portfolio)")
            else:
                entry_price = h.get('entry_price', 0)
                pnl_pct = h.get('pnl_pct', 0)
                pnl_str = f"{pnl_pct:+.1%}" if pnl_pct else "N/A"
                entry_str = f"entry ${entry_price:.4f}" if entry_price else "entry unknown"
                # Get thesis and time-in-position
                full_symbol = f"{symbol}/USDT" if not symbol.endswith("/USDT") else symbol
                thesis_data = position_theses.get(full_symbol, {})
                thesis = thesis_data.get("thesis", "") if isinstance(thesis_data, dict) else ""
                entry_cycle = thesis_data.get("entry_cycle", "") if isinstance(thesis_data, dict) else ""

                # Calculate hours in position
                time_str = ""
                if entry_cycle:
                    try:
                        from datetime import datetime
                        entry_time = datetime.fromisoformat(entry_cycle.replace('Z', '+00:00'))
                        hours_held = (datetime.utcnow() - entry_time.replace(tzinfo=None)).total_seconds() / 3600
                        time_str = f", held {hours_held:.1f}h"
                    except:
                        pass

                thesis_str = f' | YOUR THESIS: "{thesis[:60]}"' if thesis else ""
                lines.append(
                    f"  {symbol}: {h['quantity']:.4f} @ ${h['value']/h['quantity'] if h['quantity'] > 0 else 0:.4f} "
                    f"({entry_str}, {pnl_str}{time_str}) - ${h['value']:.2f}, {h.get('percent', 0):.1f}%{thesis_str}"
                )

        # Recent trades section
        if recent_trades:
            lines.append("")
            lines.append("RECENT TRADES (last 10):")
            for trade in recent_trades[:10]:
                side = trade.get('side', 'unknown').upper()
                symbol = trade.get('symbol', 'unknown').replace('/USDT', '')
                qty = trade.get('filled_quantity') or trade.get('quantity', 0)
                price = trade.get('filled_price', 0)
                time_str = trade.get('created_at', '')[:16] if trade.get('created_at') else 'unknown'
                lines.append(f"  {time_str} | {side} {qty:.4f} {symbol} @ ${price:.4f}")

        lines.append("")

        # Market context
        lines.append("MARKET CONTEXT:")
        lines.append(
            f"- Fear & Greed Index: {fear_greed.get('value', 'N/A')} "
            f"({fear_greed.get('classification', 'Unknown')})"
        )

        # Find BTC in universe for market context
        btc = next((c for c in universe if c["symbol"] == "BTC/USDT"), None)
        if btc:
            lines.append(f"- BTC 24h: {btc.get('change_24h', 0):+.1f}%")

        lines.append("")

        # Universe table
        lines.append(f"TOP {len(universe)} COINS BY VOLUME:")
        lines.append("| Symbol | Price | 2h % | 4h % | 24h % | RSI | MACD | Vol |")
        lines.append("|--------|-------|------|------|-------|-----|------|-----|")

        for coin in universe[:30]:  # Limit to top 30 for token efficiency
            symbol = coin["symbol"].replace("/USDT", "")
            price = coin.get("price", 0)
            change_2h = coin.get("change_2h", 0)
            change_4h = coin.get("change_4h", 0)
            change_24h = coin.get("change_24h", 0)
            rsi = coin.get("rsi", 50)
            macd = coin.get("macd_signal", "neutral")[:4]  # Shorten for table
            vol_ratio = coin.get("volume_ratio", 1.0)

            lines.append(
                f"| {symbol:<6} | ${price:<7.2f} | {change_2h:+4.1f}% | {change_4h:+4.1f}% | {change_24h:+5.1f}% | "
                f"{rsi:3.0f} | {macd:<4} | {vol_ratio:3.1f}x |"
            )

        lines.append("")

        # Notable setups
        lines.append("NOTABLE SETUPS:")

        # Oversold coins
        oversold = [c for c in universe if c.get("rsi", 50) < 30]
        if oversold:
            lines.append(f"- Oversold (RSI<30): {', '.join(c['symbol'].replace('/USDT', '') for c in oversold[:5])}")

        # Overbought coins
        overbought = [c for c in universe if c.get("rsi", 50) > 70]
        if overbought:
            lines.append(f"- Overbought (RSI>70): {', '.join(c['symbol'].replace('/USDT', '') for c in overbought[:5])}")

        # Strong momentum
        momentum = [c for c in universe if c.get("change_24h", 0) > 10]
        if momentum:
            lines.append(f"- Strong momentum (>10%): {', '.join(c['symbol'].replace('/USDT', '') for c in momentum[:5])}")

        # Volume spikes
        vol_spikes = [c for c in universe if c.get("volume_ratio", 1) > 2]
        if vol_spikes:
            lines.append(f"- Volume spikes (>2x): {', '.join(c['symbol'].replace('/USDT', '') for c in vol_spikes[:5])}")

        lines.append("")
        lines.append("---")
        lines.append("Set your target portfolio allocation.")

        return "\n".join(lines)

    def _update_paper_portfolio(self, order) -> None:
        """Update paper trading portfolio after an order."""
        from moneymaker.models import OrderSide

        if order.side == OrderSide.BUY:
            cost = order.filled_quantity * order.filled_price
            self.portfolio.update_cash(-cost)
            self.portfolio.update_position(
                order.symbol, order.filled_quantity, order.filled_price
            )
        else:
            proceeds = order.filled_quantity * order.filled_price
            self.portfolio.update_cash(proceeds)
            self.portfolio.update_position(
                order.symbol, -order.filled_quantity, order.filled_price
            )

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
        self.console.print("[bold green]Starting MoneyMaker v2...[/]")
        import os
        env_mode = os.environ.get("TRADING_MODE", "NOT SET")
        self.console.print(f"[bold]Mode: {self.settings.trading_mode.value} (env: TRADING_MODE={repr(env_mode)})[/]")
        self.console.print(f"Initial capital: ${self.settings.initial_capital:.2f}")
        self.console.print(f"Universe: Top {self.settings.universe_size} by volume")
        self.console.print(f"Loop interval: {self.settings.loop_interval_minutes} minutes")
        self.console.print(f"Max position: {self.settings.max_position_pct:.0%}")
        self.console.print(f"Min cash: {self.settings.min_cash_pct:.0%}")

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
                import traceback
                traceback.print_exc()
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
