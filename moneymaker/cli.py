"""Command-line interface for MoneyMaker."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from moneymaker.config import Exchange, Settings, TradingMode, get_settings
from moneymaker.core.engine import TradingEngine

app = typer.Typer(
    name="moneymaker",
    help="Claude tries to make money trading crypto. What could go wrong?",
)
console = Console()


@app.command()
def run(
    symbols: list[str] = typer.Option(
        ["DOGE/USDT"],
        "--symbol", "-s",
        help="Trading pairs to trade (can specify multiple)",
    ),
    cycles: int = typer.Option(
        None,
        "--cycles", "-c",
        help="Number of cycles to run (default: infinite)",
    ),
    interval: int = typer.Option(
        60,
        "--interval", "-i",
        help="Minutes between trading cycles",
    ),
    paper: bool = typer.Option(
        True,
        "--paper/--live",
        help="Paper trading mode (simulated) or live mode (real money!)",
    ),
):
    """
    Run the trading bot.

    Examples:
        # Paper trade DOGE every hour
        moneymaker run

        # Paper trade multiple coins every 30 minutes
        moneymaker run -s DOGE/USDT -s SHIB/USDT -i 30

        # Run 10 cycles and stop
        moneymaker run -c 10

        # YOLO live trading (careful!)
        moneymaker run --live
    """
    settings = get_settings()
    settings.trading_mode = TradingMode.PAPER if paper else TradingMode.LIVE
    settings.loop_interval_minutes = interval

    if not paper:
        console.print("[bold red]⚠️  LIVE TRADING MODE ⚠️[/]")
        console.print("[red]Real money will be used. Are you sure?[/]")
        confirm = typer.confirm("Continue with live trading?")
        if not confirm:
            raise typer.Abort()

    engine = TradingEngine(settings)
    engine.symbols = symbols

    asyncio.run(engine.run(cycles=cycles))


@app.command()
def status():
    """Show current portfolio status and recent trades."""
    settings = get_settings()

    from moneymaker.core.portfolio import PortfolioManager

    portfolio = PortfolioManager(settings)
    portfolio.load_state()

    state = portfolio.get_state()

    # Portfolio summary
    console.print("\n[bold cyan]═══ Portfolio Status ═══[/]")
    pnl_style = "green" if state.total_pnl >= 0 else "red"

    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value")

    table.add_row("Cash Balance", f"${state.cash_balance:.2f}")
    table.add_row("Total Value", f"${state.total_value:.2f}")
    table.add_row(
        "Total P&L",
        f"[{pnl_style}]${state.total_pnl:+.2f} ({state.total_pnl_pct:+.1%})[/]"
    )

    console.print(table)

    # Positions
    if state.positions:
        console.print("\n[bold]Positions:[/]")
        pos_table = Table()
        pos_table.add_column("Symbol")
        pos_table.add_column("Quantity")
        pos_table.add_column("Entry Price")
        pos_table.add_column("Current Price")
        pos_table.add_column("P&L")

        for symbol, pos in state.positions.items():
            pnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
            pos_table.add_row(
                symbol,
                f"{pos.quantity:.4f}",
                f"${pos.average_entry_price:.6f}",
                f"${pos.current_price:.6f}",
                f"[{pnl_style}]${pos.unrealized_pnl:+.2f}[/]",
            )

        console.print(pos_table)

    # Recent trades
    trades = portfolio.get_trade_history(limit=10)
    if trades:
        console.print("\n[bold]Recent Trades:[/]")
        trade_table = Table()
        trade_table.add_column("Time")
        trade_table.add_column("Symbol")
        trade_table.add_column("Side")
        trade_table.add_column("Quantity")
        trade_table.add_column("Price")
        trade_table.add_column("Strategy")

        for trade in trades:
            side_style = "green" if trade["side"] == "buy" else "red"
            trade_table.add_row(
                trade["created_at"][:19],
                trade["symbol"],
                f"[{side_style}]{trade['side'].upper()}[/]",
                f"{trade['quantity']:.4f}",
                f"${trade['filled_price']:.6f}" if trade["filled_price"] else "-",
                trade["strategy_name"][:20] if trade["strategy_name"] else "-",
            )

        console.print(trade_table)


@app.command()
def strategies():
    """Show strategy performance and allocations."""
    settings = get_settings()

    from moneymaker.core.allocator import CapitalAllocator
    from moneymaker.strategies import (
        ClaudeVibesStrategy,
        ContrarianStrategy,
        MomentumStrategy,
        SentimentStrategy,
    )

    console.print("\n[bold cyan]═══ Strategy Overview ═══[/]")

    # Show default strategies
    table = Table()
    table.add_column("Strategy")
    table.add_column("Description")
    table.add_column("Default Allocation")

    strategies = [
        MomentumStrategy(),
        SentimentStrategy(),
        ContrarianStrategy(),
        ClaudeVibesStrategy(),
    ]

    for s in strategies:
        table.add_row(
            s.name,
            s.description,
            f"{s.default_allocation:.0%}",
        )

    console.print(table)


@app.command()
def backtest(
    symbol: str = typer.Option("DOGE/USDT", "--symbol", "-s"),
    days: int = typer.Option(7, "--days", "-d"),
):
    """Run a backtest on historical data (coming soon)."""
    console.print("[yellow]Backtesting not yet implemented![/]")
    console.print("This would test strategies on historical data.")


@app.command()
def config():
    """Show current configuration."""
    settings = get_settings()

    console.print("\n[bold cyan]═══ Configuration ═══[/]")

    table = Table()
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Trading Mode", settings.trading_mode.value)
    table.add_row("Initial Capital", f"${settings.initial_capital:.2f}")
    table.add_row("Base Currency", settings.base_currency)
    table.add_row("Preferred Exchange", settings.preferred_exchange.value)
    table.add_row("Loop Interval", f"{settings.loop_interval_minutes} minutes")
    table.add_row("Min Trade Size", f"${settings.min_trade_size_usd:.2f}")
    table.add_row("Max Position %", f"{settings.max_position_pct:.0%}")

    # Check API keys (show if configured, not the actual values)
    table.add_row("Anthropic API", "✓" if settings.anthropic_api_key else "✗")
    table.add_row("Coinbase API", "✓" if settings.coinbase_api_key else "✗")
    table.add_row("Binance API", "✓" if settings.binance_api_key else "✗")
    table.add_row("Reddit API", "✓" if settings.reddit_client_id else "✗")

    console.print(table)


@app.command()
def init():
    """Initialize a new .env file with example configuration."""
    env_path = Path(".env")
    example_path = Path(".env.example")

    if env_path.exists():
        console.print("[yellow].env file already exists![/]")
        overwrite = typer.confirm("Overwrite?")
        if not overwrite:
            raise typer.Abort()

    if example_path.exists():
        env_path.write_text(example_path.read_text())
        console.print("[green]Created .env from .env.example[/]")
        console.print("Edit .env to add your API keys.")
    else:
        console.print("[red].env.example not found![/]")


if __name__ == "__main__":
    app()
